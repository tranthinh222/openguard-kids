from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_parent, get_db
from app.models.user import User
from app.schemas.child import ChildCreateRequest, ChildResponse
from app.services.child_service import create_child, get_owned_child, list_children

router = APIRouter()

@router.post("", response_model=ChildResponse, status_code=status.HTTP_201_CREATED)
def create(
    payload: ChildCreateRequest,
    parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    return create_child(
        db=db,
        parent_id=parent.id,
        display_name=payload.display_name,
        birth_year=payload.birth_year,
    )

@router.get("", response_model=list[ChildResponse], status_code=status.HTTP_200_OK)
def list_all(
    parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    return list_children(db, parent.id)

@router.get("/{child_id}", response_model=ChildResponse)
def get_one(
    child_id: str,
    parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    return get_owned_child(db, parent.id, child_id)
