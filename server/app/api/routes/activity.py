import csv
import io
from datetime import date, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_device, get_current_parent, get_db
from app.models.activity import ActivityEvent, PolicyAudit
from app.models.device import Device
from app.models.user import User
from app.schemas.activity import EventBatch
from app.schemas.content_rules import CATEGORIES
from app.services.activity_service import ingest_events
from app.services.child_service import get_owned_child
from app.services.policy_service import get_latest_policy
from app.services.report_service import event_filter, grouped_report, report_range, report_summary

router = APIRouter()

CATEGORY_DATASET = {
    "version": 1,
    "categories": CATEGORIES,
    "domains": {"khanacademy.org": "education", "wikipedia.org": "education",
                "hcmus.edu.vn": "education", "scratch.mit.edu": "education",
                "youtube.com": "entertainment", "facebook.com": "social",
                "instagram.com": "social", "tiktok.com": "social",
                "roblox.com": "games", "steampowered.com": "games",
                "age-restricted.example.test": "age_inappropriate"},
    "default_category": "unknown",
    "rule_priority": ["explicit_allow", "explicit_block", "category", "default_allow"],
    "match_subdomains": True,
}


@router.post("/agent/events/batch")
def batch(payload: EventBatch, device: Device = Depends(get_current_device), db: Session = Depends(get_db)):
    return ingest_events(db, device, payload.events)


@router.get("/agent/domain-categories")
def agent_categories(device: Device = Depends(get_current_device)):
    return CATEGORY_DATASET


@router.get("/domain-categories")
def parent_categories(parent: User = Depends(get_current_parent)):
    return CATEGORY_DATASET


@router.get("/children/{child_id}/reports/summary")
def summary(child_id: str, start: date | None = None, end: date | None = None,
            parent: User = Depends(get_current_parent), db: Session = Depends(get_db)):
    get_owned_child(db, parent.id, child_id)
    return report_summary(db, child_id, start, end)


def csv_cell(value):
    value = str(value or "")
    # Neutralize spreadsheet formulas, including leading whitespace/control chars.
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")) else value


@router.get("/children/{child_id}/reports/export.csv")
def export(child_id: str, start: date | None = None, end: date | None = None,
           parent: User = Depends(get_current_parent), db: Session = Depends(get_db)):
    get_owned_child(db, parent.id, child_id)
    _, _, lower, upper = report_range(start, end)
    rows = db.execute(select(ActivityEvent, Device.device_name).join(Device, Device.id == ActivityEvent.device_id)
                      .where(*event_filter(child_id, lower, upper))
                      .order_by(ActivityEvent.effective_at, ActivityEvent.event_id).limit(10001)).all()
    if len(rows) > 10000:
        raise HTTPException(422, "Export exceeds 10000 events; choose a shorter date range")
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["timestamp", "type", "subject", "duration_sec", "device"])
    for event, device_name in rows:
        writer.writerow([event.effective_at.replace(tzinfo=timezone.utc).isoformat(), event.type,
                         csv_cell(event.subject), event.duration_sec, csv_cell(device_name)])
    return Response("\ufeff" + buffer.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="openguard-report.csv"',
                             "Cache-Control": "no-store"})


@router.get("/children/{child_id}/reports/{kind}")
def detail(child_id: str, kind: str, start: date | None = None, end: date | None = None,
           parent: User = Depends(get_current_parent), db: Session = Depends(get_db)):
    get_owned_child(db, parent.id, child_id)
    if kind not in {"apps", "domains", "blocks"}:
        raise HTTPException(404, "Report not found")
    _, _, lower, upper = report_range(start, end)
    return grouped_report(db, child_id, lower, upper, kind)


@router.get("/agent/transparency")
def transparency(start: date | None = None, end: date | None = None,
                 device: Device = Depends(get_current_device), db: Session = Depends(get_db)):
    summary = report_summary(db, device.child_id, start, end)
    _, _, lower, upper = report_range(start, end)
    events = db.scalars(select(ActivityEvent).where(*event_filter(device.child_id, lower, upper))
                        .order_by(ActivityEvent.effective_at.desc(), ActivityEvent.event_id).limit(100)).all()
    audits = db.scalars(select(PolicyAudit).where(PolicyAudit.child_id == device.child_id,
                        PolicyAudit.created_at >= lower, PolicyAudit.created_at < upper)
                        .order_by(PolicyAudit.created_at.desc()).limit(100)).all()
    policy = get_latest_policy(db, device.child_id)
    return {"summary": summary, "policy": {"version": policy.version, "payload": policy.payload},
            "activity": [{"type": e.type, "subject": e.subject, "duration_sec": e.duration_sec,
                          "timestamp": e.effective_at.replace(tzinfo=timezone.utc), "clock_trusted": e.clock_trusted} for e in events],
            "audit": [{"timestamp": a.created_at.replace(tzinfo=timezone.utc), "actor": "parent",
                       "old_version": a.old_version, "new_version": a.new_version,
                       "old_payload": a.old_payload, "new_payload": a.new_payload} for a in audits],
            "privacy": {"collected": ["executable name", "domain", "duration", "timestamp"],
                        "never_collected": ["messages", "keystrokes", "screenshots", "full URLs", "window titles"],
                        "retention_days": 90},
            "activity_limit": 100, "audit_limit": 100}
