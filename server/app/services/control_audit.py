from app.models.control_audit import ControlAudit


def record(db, child_id, actor_id, source_ip, action, old=None, new=None):
    db.add(ControlAudit(child_id=child_id, actor_id=actor_id, source_ip=source_ip,
                        action=action, old_value=old or {}, new_value=new or {}))
