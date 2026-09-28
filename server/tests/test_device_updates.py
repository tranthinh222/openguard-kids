from datetime import timedelta
from unittest.mock import patch

from app.core.security import utc_now


def parent_headers(client, email):
    credentials = {"email": email, "password": "StrongPass123!"}
    assert client.post("/api/v1/auth/register", json=credentials).status_code == 201
    response = client.post("/api/v1/auth/token", json=credentials)
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_enrollment_heartbeat_and_timeout_update_all_parent_views(client):
    headers = parent_headers(client, "parent@example.com")
    child = client.post("/api/v1/children", headers=headers, json={"display_name": "An", "birth_year": 2020})
    assert child.status_code == 201
    child_id = child.json()["id"]
    devices_url = f"/api/v1/children/{child_id}/devices"
    assert client.get(devices_url, headers=headers).json() == []
    code = client.post(f"/api/v1/children/{child_id}/enrollment", headers=headers)
    assert code.status_code == 201
    enrolled = client.post("/api/v1/agent/enroll", json={
        "code": code.json()["code"], "device_name": "Laptop An", "fingerprint": "test-device-fingerprint",
    })
    assert enrolled.status_code == 201
    device_token = enrolled.json()["access_token"]

    def assert_views(online):
        devices = client.get(devices_url, headers=headers).json()
        assert len(devices) == 1
        assert devices[0]["device_name"] == "Laptop An"
        assert devices[0]["online"] is online
        children = client.get("/api/v1/children", headers=headers).json()
        assert children[0]["device_count"] == 1
        assert children[0]["online_count"] == int(online)
        summary = client.get("/api/v1/dashboard/summary", headers=headers).json()
        assert summary["device_count"] == 1
        assert summary["online_count"] == int(online)
        assert summary["offline_count"] == int(not online)
        assert summary["recent_devices"][0]["online"] is online
        if online:
            assert devices[0]["last_seen_at"].endswith("Z")
            assert summary["recent_devices"][0]["last_seen_at"].endswith("Z")

    # A paired device appears even before its first heartbeat.
    assert_views(False)
    now = utc_now()
    with patch("app.services.device_service.utc_now", return_value=now):
        heartbeat = client.post("/api/v1/agent/heartbeat", headers={"Authorization": f"Bearer {device_token}"}, json={"agent_version": "test", "policy_version": 1})
        assert heartbeat.status_code == 200
        assert_views(True)
    with patch("app.services.device_service.utc_now", return_value=now + timedelta(seconds=119)):
        assert_views(True)
    with patch("app.services.device_service.utc_now", return_value=now + timedelta(seconds=120)):
        assert_views(False)
    with patch("app.services.device_service.utc_now", return_value=now + timedelta(seconds=121)):
        assert client.post("/api/v1/agent/heartbeat", headers={"Authorization": f"Bearer {device_token}"}, json={"agent_version": "test", "policy_version": 1}).status_code == 200
        assert_views(True)

    other = parent_headers(client, "other@example.com")
    assert client.get(devices_url, headers=other).status_code == 404
    assert client.get("/api/v1/children", headers=other).json() == []
    assert client.get("/api/v1/dashboard/summary", headers=other).json()["device_count"] == 0
    assert client.get(devices_url).status_code == 401


def test_enrollment_status_tracks_exact_code_and_checks_ownership(client, db_session):
    from app.models.enrollment import EnrollmentCode

    headers = parent_headers(client, "pairing@example.com")
    child_id = client.post("/api/v1/children", headers=headers, json={"display_name": "An"}).json()["id"]
    base = f"/api/v1/children/{child_id}/enrollment"
    first = client.post(base, headers=headers).json()
    second = client.post(base, headers=headers).json()
    first_url = f"{base}/{first['enrollment_id']}"
    second_url = f"{base}/{second['enrollment_id']}"
    assert client.get(first_url, headers=headers).json() == {"enrollment_id": first["enrollment_id"], "status": "pending"}
    payload = {"code": first["code"], "device_name": "Laptop", "fingerprint": "pairing-test-fingerprint"}
    assert client.post("/api/v1/agent/enroll", json=payload).status_code == 201
    assert client.get(first_url, headers=headers).json()["status"] == "used"
    # A different code for the same child is still pending.
    assert client.get(second_url, headers=headers).json()["status"] == "pending"
    assert client.post("/api/v1/agent/enroll", json=payload).status_code == 409

    for enrollment_id in [first["enrollment_id"], second["enrollment_id"]]:
        db_session.get(EnrollmentCode, enrollment_id).expires_at = utc_now() - timedelta(seconds=1)
    db_session.commit()
    assert client.get(first_url, headers=headers).json()["status"] == "used"
    assert client.get(second_url, headers=headers).json()["status"] == "expired"
    assert client.get(first_url).status_code == 401
    other = parent_headers(client, "other-pairing@example.com")
    assert client.get(first_url, headers=other).status_code == 404
    sibling = client.post("/api/v1/children", headers=headers, json={"display_name": "Binh"}).json()["id"]
    assert client.get(f"/api/v1/children/{sibling}/enrollment/{first['enrollment_id']}", headers=headers).status_code == 404
    assert client.get(f"{base}/missing", headers=headers).status_code == 404
