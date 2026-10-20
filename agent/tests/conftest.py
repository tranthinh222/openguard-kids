import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest


@pytest.fixture(autouse=True)
def isolated_server_encryption_key(monkeypatch):
    import os
    import base64
    module = sys.modules.get("app.core.config")
    if module:
        monkeypatch.setattr(module.settings, "data_encryption_key", base64.b64encode(os.urandom(32)).decode())
