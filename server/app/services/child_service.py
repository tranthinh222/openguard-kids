from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import sign_policy
from app.models.child import Child
from app.models.policy import Policy

from app.services.policy_service import default_policy_payload

DEFAULT_POLICY = default_policy_payload()

def create_child(db: Session, parent_id: str, display_name: str, birth_year: int | None) -> Child:
    child = Child(
        parent_id=parent_id,
        display_name=display_name,
        birth_year=birth_year,
    )

    db.add(child)
    db.flush()

    version = 1
    policy = Policy(
        child_id=child.id,
        version=version,
        payload=DEFAULT_POLICY,
        signature=sign_policy(DEFAULT_POLICY, version),
    )

    db.add(policy)
    db.commit()
    db.refresh(child)

    return child

def list_children(db: Session, parent_id: str) -> list[Child]:
    return list(
        db.scalars(
            select(Child)
            .where(Child.parent_id == parent_id)
            .order_by(Child.created_at.asc())
        )
    )

def get_owned_child(db: Session, parent_id: str, child_id: str) -> Child:
    child = db.scalar(
        select(Child).where(Child.parent_id == parent_id, Child.id == child_id)
    )

    if child is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Child not found")

    return child
