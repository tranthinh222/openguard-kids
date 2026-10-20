"""Bounded requests and in-process rate limits for the supported single-worker deployment."""
import hashlib
import time
import uuid
from collections import OrderedDict
from starlette.responses import JSONResponse


class SecurityMiddleware:
    def __init__(self, app, config):
        self.app, self.config = app, config
        self.buckets = OrderedDict()

    def allowed(self, key, limit):
        now = time.monotonic()
        # Never keep raw credentials or IPs in limiter keys; bound memory growth.
        start, count = self.buckets.pop(key, (now, 0))
        if now - start >= 60:
            start, count = now, 0
        self.buckets[key] = (start, count + 1)
        while len(self.buckets) > 10000:
            self.buckets.popitem(last=False)
        return count < limit, max(1, int(60 - (now - start)))

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        path = scope.get('path', '')
        request_id = uuid.uuid4().hex
        scope.setdefault('state', {})['request_id'] = request_id
        async def secured_send(message):
            if message['type'] == 'http.response.start':
                headers = list(message.get('headers', []))
                names = {key.lower() for key, _ in headers}
                defaults = {b'x-content-type-options': b'nosniff', b'x-frame-options': b'DENY',
                            b'referrer-policy': b'same-origin', b'x-request-id': request_id.encode(),
                            b'cache-control': b'no-cache' if path.startswith('/static/') else b'no-store',
                            b'content-security-policy': b"frame-ancestors 'none'; base-uri 'self'; object-src 'none'"}
                if scope.get('scheme') == 'https':
                    defaults[b'strict-transport-security'] = b'max-age=31536000'
                headers.extend((key, value) for key, value in defaults.items() if key not in names)
                message['headers'] = headers
            await send(message)
        async def reject(status, text, headers=None):
            await JSONResponse({'code': f'HTTP_{status}', 'message': text}, status_code=status,
                               headers=headers)(scope, receive, secured_send)
        headers = dict(scope.get('headers', []))
        auth_path = path.startswith('/api/v1/auth/') or path in {'/api/v1/agent/enroll', '/api/v1/agent/token/refresh'}
        if self.config.rate_limit_enabled and path.startswith('/api/'):
            peer = (scope.get('client') or ('unknown',))[0]
            # An IP ceiling also prevents rotating fake bearer tokens from bypassing limits.
            peer_key = hashlib.sha256(str(peer).encode()).hexdigest()
            limit = self.config.auth_requests_per_minute if auth_path and scope['method'] == 'POST' else self.config.api_requests_per_minute
            ok, retry = self.allowed(('auth' if auth_path and scope['method'] == 'POST' else 'api', peer_key), limit)
            if not ok:
                return await reject(429, 'Too many requests; retry later', {'Retry-After': str(retry)})
        try:
            if int(headers.get(b'content-length', b'0')) > self.config.max_request_bytes:
                return await reject(413, 'Request body too large')
        except ValueError:
            return await reject(400, 'Invalid Content-Length')
        # Buffer only a bounded body; this also limits chunked uploads without Content-Length.
        chunks, total = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body = message.get('body', b'')
            total += len(body)
            if total > self.config.max_request_bytes:
                return await reject(413, 'Request body too large')
            chunks.append(body)
            if not message.get('more_body', False):
                break
        delivered = False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': b''.join(chunks), 'more_body': False}
            return await receive()
        await self.app(scope, replay, secured_send)
