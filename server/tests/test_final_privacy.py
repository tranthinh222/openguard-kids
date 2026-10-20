from sqlalchemy import select
from app.models.enrollment import EnrollmentCode
from app.models.command import DeviceCommand
from test_week04 import family

CONSENT = {"consent": True, "privacy_notice_version": "2026-10-20-v1"}


def test_consent_required_and_recorded(client, db_session):
    parent, child, _, _ = family(client)
    url = f"/api/v1/children/{child}/enrollment"
    before = len(list(db_session.scalars(select(EnrollmentCode))))
    for body in ({}, {**CONSENT, "consent": False}, {**CONSENT, "consent": "true"},
                 {**CONSENT, "privacy_notice_version": "old"}):
        assert client.post(url, headers=parent, json=body).status_code == 422
    assert len(list(db_session.scalars(select(EnrollmentCode)))) == before
    result = client.post(url, headers=parent, json=CONSENT)
    assert result.status_code == 201
    row = db_session.get(EnrollmentCode, result.json()["enrollment_id"])
    assert row.consent_at and row.privacy_notice_version == CONSENT["privacy_notice_version"]


def test_false_block_dedup_response_and_subject_privacy(client, db_session):
    parent, child, device, auth = family(client)
    url = "/api/v1/agent/requests"
    for subject in ("https://example.com/private", "C:\\private\\game.exe"):
        assert client.post(url, headers=auth, json={"type": "false_block", "subject": subject}).status_code == 422
    body = {"type": "false_block", "subject": "drive.google.com"}
    first = client.post(url, headers=auth, json=body).json()
    assert first["requested_minutes"] == 0
    assert client.post(url, headers=auth, json=body).json()["id"] == first["id"]
    another = client.post(url, headers=auth, json={**body, "subject": "game.exe"}).json()
    assert another["id"] != first["id"]
    endpoint = f"/api/v1/children/{child}/requests/{first['id']}/approve"
    assert client.post(endpoint, headers=auth, json={}).status_code == 403
    assert client.post(endpoint, headers=parent, json={"response": "Đã ghi nhận"}).status_code == 200
    assert client.post(endpoint, headers=parent, json={}).status_code == 409
    command = db_session.scalar(select(DeviceCommand).where(DeviceCommand.type == "REQUEST_REVIEWED"))
    assert command.payload["subject"] == body["subject"] and command.payload["approved"]


def test_delete_cascades_and_offline_erasure_ack_is_idempotent(client, db_session):
    from app.models.child import Child
    from app.models.device import Device
    from app.models.erasure import ErasureJob
    from app.models.policy import Policy
    from app.models.token import DeviceRefreshToken
    parent, child, device, auth = family(client)
    token = device["refresh_token"]
    assert client.post("/api/v1/agent/erasure", json={"refresh_token": token}).json()["erase_local"] is False
    assert client.delete(f"/api/v1/children/{child}", headers=auth).status_code == 403
    result = client.delete(f"/api/v1/children/{child}", headers=parent)
    assert result.json() == {"server_deleted": True, "local_cleanup_pending": True}
    db_session.expire_all()
    for model in (Child, Device, Policy, EnrollmentCode, DeviceRefreshToken):
        assert list(db_session.scalars(select(model))) == []
    assert client.get("/api/v1/agent/policy", headers=auth).status_code == 401
    assert client.post("/api/v1/agent/erasure", json={"refresh_token": "unrelated"}).json()["erase_local"] is False
    assert client.post("/api/v1/agent/erasure", json={"refresh_token": token}).json()["erase_local"] is True
    for _ in range(2):  # Lost ACK response must be safe to retry.
        assert client.post("/api/v1/agent/erasure", json={
            "refresh_token": token, "acknowledge": True}).json()["acknowledged"] is True
    assert list(db_session.scalars(select(ErasureJob))) == []


def test_sensitive_fields_are_ciphertext_at_rest(client, db_session):
    from sqlalchemy import text
    parent, child, _, _ = family(client)
    raw = db_session.execute(text("SELECT display_name FROM children WHERE id=:id"), {"id": child}).scalar()
    assert raw.startswith("ogk:gcm:v1:")
    assert client.get(f"/api/v1/children/{child}", headers=parent).json()["display_name"] != raw


def test_roles_separate_child_read_and_admin_from_parent_control(client, db_session):
    from app.models.user import User
    from app.core.security import create_access_token
    parent, child, device, _ = family(client)
    token = client.post(f"/api/v1/children/{child}/devices/{device['device_id']}/child-view-token",
                        headers=parent).json()["access_token"]
    view = {"Authorization": "Bearer " + token}
    assert client.get("/api/v1/agent/transparency", headers=view).status_code == 200
    assert client.post("/api/v1/agent/requests", headers=view, json={}).status_code == 403
    assert client.delete(f"/api/v1/children/{child}", headers=view).status_code == 403
    assert client.get("/api/v1/admin/summary", headers=parent).status_code == 403
    admin = User(email="operator@example.com", password_hash="unused", role="admin")
    db_session.add(admin)
    db_session.commit()
    auth = {"Authorization": "Bearer " + create_access_token(admin.id, "admin", 15)}
    assert client.get("/api/v1/admin/summary", headers=auth).status_code == 200
    assert client.get(f"/api/v1/children/{child}", headers=auth).status_code == 403
