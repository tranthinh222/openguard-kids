from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.api.deps import get_current_parent_for_write, get_db
from app.models.child import Child
from app.models.device import Device
from app.models.token import DeviceRefreshToken
from app.models.erasure import ErasureJob
from app.models.user import User
from app.core.security import hash_secret
from app.services.child_service import get_owned_child

router = APIRouter()


@router.delete("/children/{child_id}")
def erase_child(child_id: str, parent: User = Depends(get_current_parent_for_write),
                db: Session = Depends(get_db)):
    child = get_owned_child(db, parent.id, child_id)
    tokens = list(db.scalars(select(DeviceRefreshToken.token_hash).join(Device).where(
        Device.child_id == child.id)))
    for token in set(tokens):
        db.add(ErasureJob(token_hash=token))
    # One transaction: the receipt survives but all FK-linked personal data goes.
    db.flush()
    db.execute(delete(Child).where(Child.id == child.id))
    db.commit()
    return {"server_deleted": True, "local_cleanup_pending": bool(tokens)}


class ErasureCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str = Field(min_length=1, max_length=2048)
    acknowledge: bool = False


@router.post("/agent/erasure")
def erasure_check(payload: ErasureCheck, db: Session = Depends(get_db)):
    # Only a holder of the previous device secret can learn/ack its own erasure.
    # This grants no access to device or child data and remains usable after revocation.
    job = db.scalar(select(ErasureJob).where(ErasureJob.token_hash == hash_secret(payload.refresh_token)))
    pending = job is not None
    if job is not None and payload.acknowledge:
        db.delete(job)
        db.commit()
    return {"erase_local": pending and not payload.acknowledge, "acknowledged": payload.acknowledge}
