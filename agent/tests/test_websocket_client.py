import json

from service.realtime.websocket_client import WebSocketWorker, websocket_url


class FakeSocket:
    def __init__(self, worker):
        self.worker = worker
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def recv(self, timeout):
        assert timeout == 1
        return json.dumps({"command_id": "c1", "type": "UNLOCK", "payload": {}})

    def send(self, value):
        self.sent.append(json.loads(value))
        self.worker.stop()


class FakeHandler:
    def handle(self, command):
        from service.commands import CommandResult
        assert command["command_id"] == "c1"
        return CommandResult("c1", "completed")


def test_websocket_url_and_ack():
    assert websocket_url("https://example.test") == "wss://example.test/api/v1/agent/ws"
    sockets = []
    worker = WebSocketWorker("https://example.test", lambda: "token", FakeHandler())

    def connector(url, **kwargs):
        assert url == "wss://example.test/api/v1/agent/ws"
        assert kwargs["additional_headers"]["Authorization"] == "Bearer token"
        socket = FakeSocket(worker)
        sockets.append(socket)
        return socket

    worker.connector = connector
    worker._run()
    assert sockets[0].sent == [{
        "type": "ack", "command_id": "c1", "status": "completed", "error": None,
    }]
