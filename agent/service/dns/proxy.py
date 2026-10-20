"""Bounded UDP/TCP DNS service, bound only to loopback (127.0.0.1 and, if available, ::1)."""
import logging
import socket
import socketserver
import errno
import struct
import threading
import time
from collections import OrderedDict
import dns.exception
import dns.flags
import dns.message
import dns.rcode
import dns.rdataclass
import tldextract
from service.content_rules import domain
from .safesearch import rewrite

_extract = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True)
LOGGER = logging.getLogger('openguard-agent.dns')

# Answered locally so the runtime can probe its own proxy without upstream traffic or events.
HEALTH_NAME = 'ogk-health.invalid'
# NXDOMAIN here tells Firefox to keep DoH off by default (Mozilla's canary domain).
DOH_CANARY = 'use-application-dns.net'
# Public DNS-over-HTTPS endpoints: a browser that cannot resolve them falls back to system DNS.
DOH_HOSTS = (
    'dns.google', 'dns.google.com', 'cloudflare-dns.com', 'mozilla.cloudflare-dns.com',
    'chrome.cloudflare-dns.com', 'one.one.one.one', '1dot1dot1dot1.cloudflare-dns.com',
    'dns.quad9.net', 'dns9.quad9.net', 'dns10.quad9.net', 'dns11.quad9.net', 'doh.opendns.com',
    'doh.familyshield.opendns.com', 'dns.nextdns.io', 'doh.cleanbrowsing.org', 'dns.adguard.com',
    'dns.adguard-dns.com', 'family.adguard-dns.com', 'doh.dns.sb', 'dns.alidns.com', 'doh.pub',
    'dns.controld.com', 'freedns.controld.com', 'doh.mullvad.net', 'dns.mullvad.net',
)


def event_domain(host):
    """Only registrable domain is persisted; arbitrary subdomain labels are not telemetry."""
    result = _extract(host)
    return result.top_domain_under_public_suffix or '.'.join(host.split('.')[-2:])


class DNSProcessor:
    def __init__(self, policy, matcher, resolver, emit, notify, now, monotonic=time.monotonic):
        self.policy, self.matcher, self.resolver = policy, matcher, resolver
        self.emit, self.notify, self.now, self.monotonic = emit, notify, now, monotonic
        self.recent = OrderedDict()
        self.lock = threading.Lock()

    def handle(self, wire, tcp=False):
        try:
            query = dns.message.from_wire(wire)
        except dns.exception.DNSException:
            return None
        response = dns.message.make_response(query)
        response.flags |= dns.flags.RA
        if query.flags & dns.flags.QR or query.opcode() or len(query.question) != 1 or query.question[0].rdclass != dns.rdataclass.IN:
            response.set_rcode(dns.rcode.REFUSED)
        else:
            try:
                host = domain(query.question[0].name.to_text())
            except (ValueError, UnicodeError):
                host = None
            if host in {HEALTH_NAME, DOH_CANARY}:
                # Health probe answers NOERROR; the canary is a browser signal, not child activity.
                if host == DOH_CANARY:
                    response.set_rcode(dns.rcode.NXDOMAIN)
                return self._wire(response, query, tcp)
            try:
                policy = self.policy()
                action, reason = self.matcher.decide(host, policy) if host else ('allow', 'local')
                if reason != 'safety_exemption' and host and any(host == item or host.endswith('.' + item) for item in DOH_HOSTS):
                    action, reason = 'block', 'doh_endpoint'
                if host and reason != 'safety_exemption':
                    subject = event_domain(host)
                    kind = 'blocked_domain' if action == 'block' else 'domain_query'
                    key = kind, subject, policy.version if policy else 0
                    with self.lock:
                        mono = self.monotonic()
                        if mono - self.recent.get(key, -1e20) >= 30:
                            self.emit(kind, self.now(), subject=subject, policy_id=policy.policy_id if policy else None)
                            self.recent[key] = mono
                            self.recent.move_to_end(key)
                            while len(self.recent) > 2048:
                                self.recent.popitem(last=False)
                            if action == 'block':
                                self.notify(dict(type='DOMAIN_BLOCKED', subject=subject, reason=reason))
                if action == 'block':
                    response.set_rcode(dns.rcode.NXDOMAIN)
                else:
                    rules = policy.payload.get('domains', {}) if policy else {}
                    safe = isinstance(rules, dict) and rules.get('safe_search', False)
                    response = (rewrite(query, host, self.resolver) if safe else None) or self.resolver.resolve(query)
            except Exception:
                # Fail closed on upstream/policy/queue failure; do not log raw query labels.
                response = dns.message.make_response(query)
                response.set_rcode(dns.rcode.SERVFAIL)
        return self._wire(response, query, tcp)

    @staticmethod
    def _wire(response, query, tcp):
        if tcp:
            return response.to_wire(max_size=65535)
        return response.to_wire(max_size=max(512, min(query.payload or 512, 1232)), prefer_truncation=True)


class BoundedThreads(socketserver.ThreadingMixIn):
    daemon_threads = True
    block_on_close = False

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


class UDPServer(BoundedThreads, socketserver.UDPServer):
    pass


class TCPServer(BoundedThreads, socketserver.TCPServer):
    pass


class UDPServer6(UDPServer):
    address_family = socket.AF_INET6


class TCPServer6(TCPServer):
    address_family = socket.AF_INET6


class UDPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        data, sock = self.request
        reply = self.server.processor.handle(data)
        if reply:
            sock.sendto(reply, self.client_address)


class TCPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(3)
        def read(count):
            data = b''
            while len(data) < count:
                chunk = self.request.recv(count - len(data))
                if not chunk:
                    raise EOFError
                data += chunk
            return data
        try:
            for _ in range(20):
                count = struct.unpack('!H', read(2))[0]
                reply = self.server.processor.handle(read(count), tcp=True)
                if reply:
                    self.request.sendall(struct.pack('!H', len(reply)) + reply)
        except (EOFError, OSError):
            return


class DNSBindError(OSError):
    """Retain the failed transport and Windows socket error for actionable UI feedback."""
    def __init__(self, protocol, port, cause):
        self.protocol, self.port = protocol, port
        self.code = getattr(cause, 'winerror', None) or cause.errno
        if self.code in {errno.EADDRINUSE, 10048}:
            reason = 'Cổng đang được ứng dụng khác sử dụng.'
        elif self.code in {errno.EACCES, errno.EPERM, 10013}:
            reason = 'Windows từ chối bind; cổng có thể bị giữ độc quyền hoặc bị hạn chế quyền truy cập.'
        else:
            reason = 'Không thể bind socket DNS.'
        hint = ' Đổi OGK_DNS_PORT sang cổng trống (ví dụ 15353) để test, rồi thoát và mở lại agent.' if port != 53 else ' Kiểm tra ứng dụng đang giữ cổng 53 và quyền bind của agent.'
        super().__init__(f'Không mở được DNS {protocol} tại 127.0.0.1:{port} (mã lỗi {self.code}). {reason}{hint}')


class DNSProxy:
    def __init__(self, processor, port=53, ipv6=True):
        self.processor, self.port, self.servers, self.threads = processor, port, [], []
        self.ipv6, self.ipv6_bound = ipv6, False

    def start(self):
        protocol = 'UDP'
        try:
            udp = UDPServer(('127.0.0.1', self.port), UDPHandler)
            self.servers.append(udp)
            self.port = udp.server_address[1]
            protocol = 'TCP'
            self.servers.append(TCPServer(('127.0.0.1', self.port), TCPHandler))
            if self.ipv6:
                # Without a ::1 listener, an adapter's IPv6 DNS servers would bypass the filter.
                v6 = []
                try:
                    v6.append(UDPServer6(('::1', self.port), UDPHandler))
                    v6.append(TCPServer6(('::1', self.port), TCPHandler))
                    self.servers.extend(v6)
                    self.ipv6_bound = True
                except OSError as exc:
                    for server in v6:
                        server.server_close()
                    LOGGER.warning('DNS proxy IPv6 loopback unavailable: %s', exc)
            for server in self.servers:
                server.processor, server.slots = self.processor, threading.BoundedSemaphore(32)
                thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .1}, daemon=True)
                thread.start()
                self.threads.append(thread)
        except OSError as exc:
            self.stop()
            raise DNSBindError(protocol, self.port, exc) from exc
        except Exception:
            self.stop()
            raise

    def stop(self):
        for index, server in enumerate(self.servers):
            if index < len(self.threads):
                server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join(timeout=2)
        self.servers, self.threads, self.ipv6_bound = [], [], False
