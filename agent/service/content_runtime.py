"""Content protection and network sync run independently of screen-time ticks."""
import logging
import threading
import time
from datetime import timedelta, timezone
from service.apps.monitor import AppMonitor
from service.dns.matcher import DomainMatcher
from service.dns.proxy import DNSProcessor, DNSProxy, DNSBindError
from service.dns.resolver import Resolver

LOGGER = logging.getLogger('openguard-agent.content')


class ContentRuntime:
    def __init__(self, client, notify):
        self.client, self.notify = client, notify
        self.stop_event = threading.Event()
        self.threads = []

    def start(self):
        if self.threads:
            return
        for target in (self._protect, self._sync):
            thread = threading.Thread(target=target, daemon=True, name='openguard-content')
            thread.start()
            self.threads.append(thread)

    def _protect(self):
        client, proxy, monitor = self.client, None, None
        try:
            policy = lambda: client.policy_manager.current if client.policy_manager else None
            now = lambda: client.clock_monitor.trusted_now() if client.clock_monitor.ready else client.clock_monitor.local_now().astimezone(
                timezone(timedelta(minutes=client.config.report_timezone_offset_minutes)))
            monitor = AppMonitor(policy, client.events.emit, self.notify, now)
            matcher = DomainMatcher(client.events.cached('categories'))
            processor = DNSProcessor(policy, matcher, Resolver(client.config.dns_upstream),
                                     client.events.emit, self.notify, now)
            if client.config.dns_enabled:
                proxy = DNSProxy(processor, client.config.dns_port)
                try:
                    proxy.start()
                    self.notify(dict(type='DNS_STARTED', port=proxy.port))
                except DNSBindError as exc:
                    LOGGER.error('%s', exc)
                    self.notify(dict(type='CONTENT_ERROR', message=str(exc)))
            while not self.stop_event.is_set():
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
            if proxy:
                proxy.stop()
            if monitor:
                monitor.close()

    def _sync(self):
        next_categories, backoff = 0, self.client.config.event_sync_sec
        while not self.stop_event.is_set():
            try:
                if not self.client.clock_monitor.ready:
                    self.stop_event.wait(.5)
                    continue
                self.client.events.sync(self.client._authorized_post)
                if time.monotonic() >= next_categories:
                    dataset = self.client.authorized_get('/api/v1/agent/domain-categories')
                    DomainMatcher(dataset)  # Reject malformed updates, keep last known good.
                    self.client.events.cache('categories', dataset)
                    self.client.events.prune(self.client.clock_monitor.trusted_now())
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
