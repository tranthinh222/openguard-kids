from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.security import utc_now
from app.models.activity import ActivityEvent as Event, ScreenUsage
from app.services.activity_service import report_timezone


def report_range(start: date | None, end: date | None):
    today = utc_now().replace(tzinfo=timezone.utc).astimezone(report_timezone()).date()
    end = end or today
    start = start or end - timedelta(days=6)
    if start > end or (end - start).days >= 90 or end > today:
        raise HTTPException(422, "Choose a date range of 1–90 days, ending no later than today")
    tz = report_timezone()
    lower = datetime.combine(start, time.min, tz).astimezone(timezone.utc).replace(tzinfo=None)
    upper = datetime.combine(end + timedelta(days=1), time.min, tz).astimezone(timezone.utc).replace(tzinfo=None)
    return start, end, lower, upper


def event_filter(child_id, lower, upper, device_id=None):
    filters = [Event.child_id == child_id, Event.effective_at >= lower, Event.effective_at < upper]
    if device_id:
        filters.append(Event.device_id == device_id)
    return filters


def grouped_report(db, child_id, lower, upper, kind, device_id=None):
    kinds = {"apps": ["app_stop"], "domains": ["domain_query"], "blocks": ["blocked_app", "blocked_domain"]}
    metric = func.sum(Event.duration_sec) if kind == "apps" else func.count()
    query = select(Event.subject, Event.type, metric.label("value")).where(
        *event_filter(child_id, lower, upper, device_id), Event.type.in_(kinds[kind])
    ).group_by(Event.subject, Event.type).order_by(metric.desc(), Event.subject).limit(10)
    return [{"subject": subject, "type": event_type,
             "duration_sec" if kind == "apps" else "count": value} for subject, event_type, value in db.execute(query)]


def report_summary(db, child_id, start=None, end=None, device_id=None):
    start, end, lower, upper = report_range(start, end)
    filters = event_filter(child_id, lower, upper, device_id)
    usage_filters = [ScreenUsage.child_id == child_id, ScreenUsage.day >= start, ScreenUsage.day <= end]
    if device_id:
        usage_filters.append(ScreenUsage.device_id == device_id)
    totals = dict(db.execute(select(ScreenUsage.day, func.sum(ScreenUsage.duration_sec)).where(
        *usage_filters).group_by(ScreenUsage.day)).all())
    daily = [{"date": (start + timedelta(days=i)).isoformat(),
              "screen_time_sec": totals.get(start + timedelta(days=i), 0),
              "has_data": start + timedelta(days=i) in totals} for i in range((end - start).days + 1)]
    return {
        "child_id": child_id, "start": start.isoformat(), "end": end.isoformat(),
        "timezone_offset_minutes": int(report_timezone().utcoffset(None).total_seconds() / 60),
        "screen_time_sec": sum(totals.values()), "screen_time_source": "heartbeat_daily_max",
        "has_screen_time_data": bool(totals), "daily": daily,
        "app_duration_sec": db.scalar(select(func.coalesce(func.sum(Event.duration_sec), 0)).where(*filters, Event.type == "app_stop")),
        "blocked_count": db.scalar(select(func.count()).select_from(Event).where(*filters, Event.type.in_(["blocked_app", "blocked_domain"]))),
        "untrusted_event_count": db.scalar(select(func.count()).select_from(Event).where(*filters, Event.clock_trusted.is_(False))),
        "top_apps": grouped_report(db, child_id, lower, upper, "apps", device_id),
        "top_domains": grouped_report(db, child_id, lower, upper, "domains", device_id),
        "blocks": grouped_report(db, child_id, lower, upper, "blocks", device_id),
    }
