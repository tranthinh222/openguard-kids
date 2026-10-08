import hashlib
import json
from datetime import timedelta, timezone

from pydantic import ValidationError
from sqlalchemy import delete, select, func, or_
from sqlalchemy.dialects.sqlite import insert

from app.core.config import settings
from app.core.security import utc_now
from app.models.activity import ActivityEvent, PolicyAudit, ScreenUsage
from app.models.policy import Policy
from app.schemas.activity import EventInput


def report_timezone():
    return timezone(timedelta(minutes=settings.report_timezone_offset_minutes))


def ingest_events(db, device, entries):
    now = utc_now()
    accepted, duplicates, rejected = [], [], []
    for index, raw in enumerate(entries):
        event_id = None
        try:
            item = EventInput.model_validate(raw)
            event_id = str(item.event_id)
            if ((item.device_id and str(item.device_id) != device.id) or
                    (item.child_id and str(item.child_id) != device.child_id)):
                raise ValueError("identity_mismatch")
            policy_id = str(item.policy_id) if item.policy_id else None
            if policy_id and db.scalar(select(Policy.id).where(
                Policy.id == policy_id, Policy.child_id == device.child_id
            )) is None:
                raise ValueError("invalid_policy")
            canonical = item.model_dump(mode="json", exclude={"device_id", "child_id"})
            digest = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
            previous = db.get(ActivityEvent, event_id)
            if previous:
                if previous.device_id != device.id or previous.payload_hash != digest:
                    raise ValueError("event_id_conflict")
                accepted.append(event_id)
                duplicates.append(event_id)
                continue
            occurred = item.ts.astimezone(timezone.utc).replace(tzinfo=None)
            # Offline history is valid. A fresh known-bad wall clock or a future
            # timestamp makes its occurrence time unsuitable for aggregation.
            fresh = device.last_seen_at and now - device.last_seen_at < timedelta(seconds=120)
            bad_clock = fresh and device.clock_drift_sec is not None and abs(device.clock_drift_sec) > settings.agent_clock_drift_threshold_sec
            if occurred < now - timedelta(days=90) and not bad_clock:
                raise ValueError("outside_retention")
            trusted = not bad_clock and occurred <= now + timedelta(seconds=settings.agent_clock_drift_threshold_sec)
            values = dict(event_id=event_id, child_id=device.child_id, device_id=device.id,
                          type=item.type, subject=item.subject, duration_sec=item.duration_sec,
                          policy_id=policy_id, occurred_at=occurred, received_at=now,
                          effective_at=min(occurred, now) if trusted else now,
                          clock_trusted=bool(trusted), payload_hash=digest)
            result = db.execute(insert(ActivityEvent).values(**values).on_conflict_do_nothing(index_elements=["event_id"]))
            if result.rowcount == 0:
                previous = db.get(ActivityEvent, event_id)
                if previous.device_id != device.id or previous.payload_hash != digest:
                    raise ValueError("event_id_conflict")
                duplicates.append(event_id)
            accepted.append(event_id)
        except ValidationError:
            rejected.append({"index": index, "event_id": event_id, "reason": "invalid_event"})
        except ValueError as exc:
            rejected.append({"index": index, "event_id": event_id, "reason": str(exc)})
    db.commit()
    return {"accepted": accepted, "duplicates": duplicates, "rejected": rejected}


def record_screen_usage(db, device, now, day=None):
    today = now.replace(tzinfo=timezone.utc).astimezone(report_timezone()).date()
    # Legacy agents cannot identify the quota's day after a restart. Do not
    # silently attribute yesterday's persisted quota to today's report.
    if day is None or not today - timedelta(days=89) <= day <= today:
        return
    seconds = min(86400, max(0, device.quota_used_sec))
    statement = insert(ScreenUsage).values(device_id=device.id, child_id=device.child_id,
                                            day=day, duration_sec=seconds)
    db.execute(statement.on_conflict_do_update(
        index_elements=["device_id", "day"],
        set_={"duration_sec": func.max(ScreenUsage.duration_sec, seconds)},
    ))


def cleanup_activity(db, now=None):
    now = now or utc_now()
    cutoff = now - timedelta(days=90)
    # History uploaded late must not get another full 90 days of retention;
    # receipt time also bounds retention for untrusted future timestamps.
    count = db.execute(delete(ActivityEvent).where(or_(
        ActivityEvent.received_at < cutoff, ActivityEvent.effective_at < cutoff
    ))).rowcount
    db.execute(delete(ScreenUsage).where(ScreenUsage.day < cutoff.replace(tzinfo=timezone.utc).astimezone(report_timezone()).date()))
    db.execute(delete(PolicyAudit).where(PolicyAudit.created_at < cutoff))
    db.commit()
    return count
