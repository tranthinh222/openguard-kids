import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import sign_policy
from app.models.policy import Policy
from app.models.activity import PolicyAudit
from app.schemas.policy import PolicyPayload
from app.schemas.policy import PolicyResponse
from app.models.device import Device
from app.services.realtime import manager

LOGGER = logging.getLogger(__name__)
POLICY_PUSH_TIMEOUT_SEC = 2.0


async def push_policy_update(db: Session, policy: Policy) -> None:
    """Best-effort notification after commit; heartbeat version checks remain authoritative."""
    device_ids = list(db.scalars(select(Device.id).where(
        Device.child_id == policy.child_id,
        Device.status == "active",
        Device.revoked_at.is_(None),
    )))
    message = {"type": "POLICY_UPDATED", "payload": PolicyResponse.model_validate(policy).model_dump(mode="json")}

    async def send(device_id: str) -> None:
        try:
            # An actual socket, not a recent last_seen timestamp, determines reachability.
            await asyncio.wait_for(manager.send(device_id, message), timeout=POLICY_PUSH_TIMEOUT_SEC)
        except Exception:
            LOGGER.warning("Policy push failed for device %s; heartbeat will retry synchronization", device_id, exc_info=True)

    await asyncio.gather(*(send(device_id) for device_id in device_ids))

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

def update_policy(db: Session, child_id: str, payload: PolicyPayload, actor_id: str | None = None) -> Policy:
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
    db.add(PolicyAudit(child_id=child_id, actor_id=actor_id, old_version=previous.version,
                       new_version=version, old_payload=previous.payload, new_payload=data))
    db.commit()
    db.refresh(policy)

    return policy
