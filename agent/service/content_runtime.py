"""Content protection and network sync run independently of screen-time ticks."""
import logging
import threading
import time
from datetime import timedelta, timezone
from service.apps.monitor import AppMonitor
from service.dns.matcher import DomainMatcher
from service.dns.proxy import HEALTH_NAME, DNSProcessor, DNSProxy, DNSBindError
from service.dns.resolver import Resolver

LOGGER = logging.getLogger('openguard-agent.content')
DNS_PROBE_SEC = 15
DNS_REBIND_SEC = 30


def probe_dns(port, timeout=2.0):
    """Ask our own proxy for the local health name; True only for a NOERROR answer."""
    import dns.message
    import dns.query
    import dns.rcode
    try:
        reply = dns.query.udp(dns.message.make_query(HEALTH_NAME, 'A'), '127.0.0.1', port=port, timeout=timeout)
        return reply.rcode() == dns.rcode.NOERROR
    except Exception:
        return False


class ContentRuntime:
    def __init__(self, client, notify):
        self.client, self.notify = client, notify
        self.stop_event = threading.Event()
        self.threads = []
        self.proxy, self.dns_healthy = None, None
        self._dns_failures, self._next_bind, self._next_probe, self._bind_reported = 0, 0.0, 0.0, False

    def start(self):
        if self.threads:
            return
        for target in (self._protect, self._sync):
            thread = threading.Thread(target=target, daemon=True, name='openguard-content')
            thread.start()
            self.threads.append(thread)

    def _protect(self):
        # A crash in app/DNS protection is retried with backoff instead of leaving the child
        # unprotected until someone restarts the Agent.
        backoff = 1.0
        while not self.stop_event.is_set():
            started = time.monotonic()
            self._protect_once()
            if time.monotonic() - started > 60:
                backoff = 1.0
            self.stop_event.wait(backoff)
            backoff = min(backoff * 2, 60.0)

    def _set_dns_health(self, healthy):
        if healthy != self.dns_healthy:
            self.dns_healthy = healthy
            self.notify(dict(type='DNS_HEALTH', healthy=healthy, port=self.proxy.port if self.proxy else None,
                             ipv6=bool(self.proxy and self.proxy.ipv6_bound)))

    def _stop_proxy(self):
        if self.proxy:
            self.proxy.stop()
            self.proxy = None

    def _dns_tick(self, processor):
        """Keep the proxy bound and answering; a dead proxy is rebound instead of left broken."""
        mono = time.monotonic()
        if self.proxy is None:
            if mono < self._next_bind:
                return
            proxy = DNSProxy(processor, self.client.config.dns_port)
            try:
                proxy.start()
            except DNSBindError as exc:
                self._next_bind = mono + DNS_REBIND_SEC
                self._set_dns_health(False)
                if not self._bind_reported:  # One notice per failure streak, not every retry.
                    self._bind_reported = True
                    LOGGER.error('%s', exc)
                    self.notify(dict(type='CONTENT_ERROR', message=str(exc)))
                return
            self.proxy, self._bind_reported, self._dns_failures, self._next_probe = proxy, False, 0, mono
            self.notify(dict(type='DNS_STARTED', port=proxy.port, ipv6=proxy.ipv6_bound))
        if mono < self._next_probe:
            return
        self._next_probe = mono + DNS_PROBE_SEC
        if probe_dns(self.proxy.port):
            self._dns_failures = 0
            self._set_dns_health(True)
            return
        self._dns_failures += 1
        LOGGER.warning('DNS proxy health probe failed (%s in a row)', self._dns_failures)
        if self._dns_failures >= 2:
            self._stop_proxy()
            self._next_bind = mono
            self._set_dns_health(False)

    def _protect_once(self):
        client, monitor = self.client, None
        try:
            policy = lambda: client.policy_manager.current if client.policy_manager else None
            now = lambda: client.clock_monitor.trusted_now() if client.clock_monitor.ready else client.clock_monitor.local_now().astimezone(
                timezone(timedelta(minutes=client.config.report_timezone_offset_minutes)))
            monitor = AppMonitor(policy, client.events.emit, self.notify, now, snapshot=client.host.processes)
            matcher = DomainMatcher(client.events.cached('categories'))
            processor = DNSProcessor(policy, matcher, Resolver(client.config.dns_upstream),
                                     client.events.emit, self.notify, now)
            while not self.stop_event.is_set():
                if client.config.dns_enabled:
                    self._dns_tick(processor)
                cached = client.events.cached('categories')
                if cached:
                    matcher.update(cached)
                if client.config.apps_enabled:
                    monitor.tick()
                self.stop_event.wait(client.config.app_poll_sec)
        except Exception:
            LOGGER.exception('Content protection stopped')
            self.notify(dict(type='CONTENT_ERROR', message='Bảo vệ app/domain gặp lỗi. Hãy mở lại agent và kiểm tra cấu hình.'))
        finally:
            self._stop_proxy()
            if self.dns_healthy is not None:
                self._set_dns_health(False)
            if monitor:
                monitor.close()

    def _sync(self):
        next_categories, next_prune, backoff = 0, 0, self.client.config.event_sync_sec
        while not self.stop_event.is_set():
            try:
                if not self.client.clock_monitor.ready:
                    self.stop_event.wait(.5)
                    continue
                if self.client.clock_monitor.verified and time.monotonic() >= next_prune:
                    self.client.events.prune(self.client.clock_monitor.trusted_now())
                    next_prune = time.monotonic() + 3600
                self.client.events.sync(self.client._authorized_post)
                if time.monotonic() >= next_categories:
                    dataset = self.client.authorized_get('/api/v1/agent/domain-categories')
                    DomainMatcher(dataset)  # Reject malformed updates, keep last known good.
                    self.client.events.cache('categories', dataset)
                    next_categories = time.monotonic() + 3600
                backoff = self.client.config.event_sync_sec
            except Exception:
                LOGGER.warning('Content sync unavailable; pending events retained')
                backoff = min(max(backoff * 2, 1), 60)
            self.stop_event.wait(backoff)

    def stop(self):
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=self.client.config.request_timeout_sec * 3 + 4)
        self.threads = []
