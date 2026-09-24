from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.policy import Policy

def get_latest_policy(db: Session, child_id: str) -> Policy:
    policy = db.scalar(
        select(Policy)
        .where(Policy.child_id == child_id)
        .order_by(Policy.version.desc())
        .limit(1)
    )

    if policy is None:
        raise RuntimeError("Child has no policy")

    return policy