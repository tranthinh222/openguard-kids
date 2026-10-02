from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import sign_policy
from app.models.policy import Policy
from app.schemas.policy import PolicyPayload

def default_policy_payload() -> dict:
    return PolicyPayload().model_dump(mode="json")

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

def update_policy(db: Session, child_id: str, payload: PolicyPayload) -> Policy:
    previous = get_latest_policy(db, child_id)
    version = previous.version + 1
    data = payload.model_dump(mode="json")
    policy = Policy(
        child_id=child_id,
        version=version,
        payload=data,
        signature=sign_policy(data, version),
    )

    db.add(policy)
    db.commit()
    db.refresh(policy)

    return policy
