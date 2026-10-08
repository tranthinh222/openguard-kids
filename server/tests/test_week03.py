import csv
import io
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.security import sign_policy, utc_now
from app.models.activity import ActivityEvent, ScreenUsage
from app.models.device import Device
from app.services.activity_service import cleanup_activity, report_timezone
from test_week02 import parent_headers, enrolled_device


@pytest.fixture
def family(client):
    parent = parent_headers(client)
    child, device = enrolled_device(client, parent)
    return parent, child, device, {"Authorization": f"Bearer {device['access_token']}"}


def event(kind="app_stop", subject="game.exe", seconds=60, **extra):
    return {"event_id": str(uuid4()), "ts": datetime.now(timezone.utc).isoformat(),
            "type": kind, "subject": subject, "duration_sec": seconds, **extra}


def ingest(client, auth, events):
    return client.post("/api/v1/agent/events/batch", headers=auth, json={"events": events})


def test_content_policy_roundtrip_audit_signature_and_legacy(client, family):
    parent, child, _, auth = family
    url = f"/api/v1/children/{child}/policy"
    payload = client.get(url, headers=parent).json()["payload"]
    payload["apps"] = [{"name": "GAME.EXE", "sha256": "A" * 64, "action": "block"}]
    payload["domains"] = {"allow": ["SCHOOL.edu.vn."], "block": ["example.com"],
                          "blocked_categories": ["games"], "safe_search": True}
    response = client.put(url, headers=parent, json={"payload": payload})
    assert response.status_code == 200
    data = response.json()
    assert data["payload"]["apps"][0]["name"] == "game.exe"
    assert data["payload"]["domains"]["allow"] == ["school.edu.vn"]
    assert data["signature"] == sign_policy(data["payload"], data["version"])
    assert client.get("/api/v1/agent/policy", headers=auth).json() == data
    view = client.get("/api/v1/agent/transparency", headers=auth).json()
    assert view["audit"][0]["new_payload"] == data["payload"]
    payload["apps"] = []
    payload["domains"] = []
    assert client.put(url, headers=parent, json={"payload": payload}).status_code == 200


@pytest.mark.parametrize("change", [
    {"apps": [{"name": "C:\\private\\game.exe", "action": "block"}]},
    {"apps": [{"name": "game.exe", "sha256": "invalid", "action": "block"}]},
    {"apps": [{"name": "game.exe", "action": "block"}, {"name": "GAME.exe", "action": "allow"}]},
    {"domains": {"allow": ["https://example.com/private"]}},
    {"domains": {"allow": ["example.com", "EXAMPLE.COM."]}},
    {"domains": {"allow": ["example.com"], "block": ["example.com"]}},
    {"domains": {"blocked_categories": ["invalid"]}},
    {"domains": {"allow": ["127.0.0.1"]}},
])
def test_policy_rejects_bad_rules(client, family, change):
    parent, child, _, _ = family
    result = client.put(f"/api/v1/children/{child}/policy", headers=parent, json={"payload": change})
    assert result.status_code == 422


def test_batch_retry_conflict_and_partial_ack(client, family, db_session):
    _, child, _, auth = family
    item = event()
    invalid = event("domain_query", "https://example.com/private", 0)
    result = ingest(client, auth, [item, item, invalid]).json()
    assert result["accepted"] == [item["event_id"], item["event_id"]]
    assert result["duplicates"] == [item["event_id"]]
    assert result["rejected"][0]["index"] == 2
    assert ingest(client, auth, [item]).json()["duplicates"] == [item["event_id"]]
    conflict = {**item, "duration_sec": 99}
    assert ingest(client, auth, [conflict]).json()["rejected"][0]["reason"] == "event_id_conflict"
    assert db_session.scalar(select(func.count()).select_from(ActivityEvent)) == 1
    assert db_session.scalar(select(ActivityEvent.child_id)) == child


def test_events_reject_identity_policy_and_private_fields(client, family):
    _, _, device, auth = family
    other_parent = parent_headers(client, "other@example.com")
    other_child, _ = enrolled_device(client, other_parent)
    other_policy = client.get(f"/api/v1/children/{other_child}/policy", headers=other_parent).json()["id"]
    inputs = [event(child_id=other_child), event(device_id=str(uuid4())), event(policy_id=other_policy),
              event(window_title="private"), event("domain_query", "example.com/path", 0),
              event("app_stop", "C:\\private\\game.exe", 10),
              event("locked", "some private message", 0), event(seconds=-1)]
    result = ingest(client, auth, inputs).json()
    assert len(result["rejected"]) == len(inputs) and not result["accepted"]
    assert "private" not in str(result)
    assert ingest(client, auth, [event(child_id=device.get("child_id"), device_id=device["device_id"])]).status_code == 200


def test_offline_events_future_time_and_retention(client, family, db_session):
    _, _, _, auth = family
    now = utc_now().replace(tzinfo=timezone.utc)
    old = event(ts=(now - timedelta(days=2)).isoformat())
    future = event(ts=(now + timedelta(days=365)).isoformat())
    expired = event(ts=(now - timedelta(days=91)).isoformat())
    result = ingest(client, auth, [old, future, expired]).json()
    assert result["accepted"] == [old["event_id"], future["event_id"]]
    assert result["rejected"][0]["reason"] == "outside_retention"
    saved_old = db_session.get(ActivityEvent, old["event_id"])
    saved_future = db_session.get(ActivityEvent, future["event_id"])
    assert saved_old.effective_at == saved_old.occurred_at
    assert saved_future.clock_trusted is False
    assert saved_future.effective_at == saved_future.received_at
    assert saved_future.occurred_at > saved_future.received_at
    saved_future.received_at = utc_now() - timedelta(days=91)
    db_session.commit()
    assert cleanup_activity(db_session) == 1
    assert db_session.get(ActivityEvent, old["event_id"]) is not None


def test_fresh_clock_drift_marks_event_untrusted(client, family, db_session):
    _, _, _, auth = family
    client.post("/api/v1/agent/heartbeat", headers=auth, json={
        "policy_version": 1, "agent_version": "test", "agent_wall_clock": "2040-01-01T00:00:00Z"})
    item = event(ts=(datetime.now(timezone.utc) - timedelta(hours=12)).isoformat())
    ingest(client, auth, [item])
    stored = db_session.get(ActivityEvent, item["event_id"])
    assert stored.clock_trusted is False and stored.effective_at == stored.received_at


def test_reports_transparency_csv_and_screen_time(client, family, db_session):
    parent, child, device, auth = family
    today = datetime.now(report_timezone()).date().isoformat()
    # High-water marks prevent repeat heartbeat counts; an undated legacy sample is omitted.
    hb = {"policy_version": 1, "agent_version": "test", "quota_used_sec": 800}
    client.post("/api/v1/agent/heartbeat", headers=auth, json=hb)
    assert db_session.scalar(select(func.count()).select_from(ScreenUsage)) == 0
    for used in (120, 120, 90, 180):
        client.post("/api/v1/agent/heartbeat", headers=auth, json={**hb, "quota_used_sec": used, "quota_date": today})
    entries = [event(seconds=60), event(seconds=30), event("app_start", "game.exe", 0),
               event("domain_query", "example.com", 0), event("blocked_domain", "example.com", 0)]
    ingest(client, auth, entries)
    ingest(client, auth, entries)
    base = f"/api/v1/children/{child}/reports"
    report = client.get(base + "/summary", headers=parent).json()
    assert report["screen_time_sec"] == 180 and report["app_duration_sec"] == 90
    assert report["blocked_count"] == 1
    assert report["top_apps"][0]["duration_sec"] == 90
    assert report["top_domains"][0]["count"] == 1
    assert len(report["daily"]) == 7
    assert client.get(base + "/apps", headers=parent).json() == report["top_apps"]
    assert client.get(base + "/domains", headers=parent).json() == report["top_domains"]
    assert client.get(base + "/blocks", headers=parent).json() == report["blocks"]
    assert client.get("/api/v1/agent/transparency", headers=auth).json()["summary"] == report
    stored_device = db_session.get(Device, device["device_id"])
    stored_device.device_name = "=1+1"
    db_session.commit()
    exported = client.get(base + "/export.csv", headers=parent)
    rows = list(csv.reader(io.StringIO(exported.text.lstrip("\ufeff"))))
    assert rows[0] == ["timestamp", "type", "subject", "duration_sec", "device"]
    assert len(rows) == 6 and all(row[-1] == "'=1+1" for row in rows[1:])


def test_report_date_filter_and_idor(client, family):
    parent, child, _, auth = family
    other = parent_headers(client, "outsider@example.com")
    for kind in ["summary", "apps", "domains", "blocks", "export.csv"]:
        url = f"/api/v1/children/{child}/reports/{kind}"
        assert client.get(url, headers=other).status_code == 404
        assert client.get(url, headers=auth).status_code == 403
        assert client.get(url).status_code == 401
        assert client.get(url + "?start=2020-01-01&end=2026-01-01", headers=parent).status_code == 422
    assert client.get("/api/v1/agent/transparency", headers=parent).status_code == 403
    assert ingest(client, parent, [event()]).status_code == 403
    assert ingest(client, auth, [event()] * 501).status_code == 422


def test_cross_device_event_id_does_not_leak_or_duplicate(client, family):
    _, _, _, auth = family
    parent = parent_headers(client, "second@example.com")
    _, device = enrolled_device(client, parent)
    second = {"Authorization": f"Bearer {device['access_token']}"}
    item = event()
    ingest(client, auth, [item])
    result = ingest(client, second, [item]).json()
    assert result["rejected"][0]["reason"] == "event_id_conflict"
    assert client.get("/api/v1/agent/transparency", headers=second).json()["activity"] == []


def test_reports_page_and_categories(client, family):
    parent, _, _, auth = family
    page = client.get("/reports")
    assert page.status_code == 200 and 'id="report-child"' in page.text
    assert 'href="/reports"' in page.text
    assert client.get("/api/v1/domain-categories", headers=parent).json() == client.get("/api/v1/agent/domain-categories", headers=auth).json()


def test_cookie_policy_write_still_requires_csrf(client, family):
    import re
    _, child, _, _ = family
    credentials = {"email": "week2@example.com", "password": "StrongPass123!"}
    page = client.get("/login")
    csrf = re.search(r'data-login-csrf="([^"]+)"', page.text).group(1)
    assert client.post("/api/v1/auth/login", json=credentials, headers={"X-CSRF-Token": csrf}).status_code == 200
    body = {"payload": {"apps": [{"name": "game.exe", "action": "block"}]}}
    url = f"/api/v1/children/{child}/policy"
    assert client.put(url, json=body).status_code == 403
    csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
    assert client.put(url, json=body, headers={"X-CSRF-Token": csrf}).status_code == 200


def test_report_range_filters_events_and_preserves_timezone_day(client, family):
    parent, child, _, auth = family
    today = datetime.now(report_timezone()).date()
    previous = today - timedelta(days=1)
    yesterday = datetime.combine(previous, datetime.min.time(), report_timezone()).replace(hour=12)
    ingest(client, auth, [event(ts=yesterday.isoformat(), seconds=77), event(seconds=33)])
    url = f"/api/v1/children/{child}/reports/summary?start={previous}&end={previous}"
    data = client.get(url, headers=parent).json()
    assert data["app_duration_sec"] == 77
    assert len(data["daily"]) == 1


def test_revoked_device_cannot_ingest_or_read_transparency(client, family, db_session):
    _, _, device, auth = family
    db_session.get(Device, device["device_id"]).revoked_at = utc_now()
    db_session.commit()
    assert ingest(client, auth, [event()]).status_code == 401
    assert client.get("/api/v1/agent/transparency", headers=auth).status_code == 401


def test_retention_loop_runs_cleanup_then_waits_one_day(monkeypatch):
    import asyncio
    from app.services import retention
    calls = []
    monkeypatch.setattr(retention, "cleanup_once", lambda: calls.append("cleaned"))

    async def stop_after_sleep(seconds):
        calls.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(retention.asyncio, "sleep", stop_after_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(retention.retention_loop())
    assert calls == ["cleaned", 86400]


def test_delayed_history_does_not_extend_retention(client, family, db_session):
    _, _, _, auth = family
    item = event(ts=(datetime.now(timezone.utc) - timedelta(days=89)).isoformat())
    assert ingest(client, auth, [item]).json()["accepted"] == [item["event_id"]]
    assert cleanup_activity(db_session, utc_now() + timedelta(days=2)) == 1


def test_known_bad_past_clock_preserves_event_using_receipt_time(client, family, db_session):
    _, _, _, auth = family
    client.post("/api/v1/agent/heartbeat", headers=auth, json={
        "policy_version": 1, "agent_version": "test", "agent_wall_clock": "2000-01-01T00:00:00Z"})
    item = event(ts="2000-01-01T00:00:00Z")
    assert ingest(client, auth, [item]).json()["accepted"] == [item["event_id"]]
    stored = db_session.get(ActivityEvent, item["event_id"])
    assert stored.clock_trusted is False and stored.effective_at == stored.received_at
