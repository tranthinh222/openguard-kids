from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_parent, get_db
from app.models.user import User
from app.schemas.dashboard import DashboardSummaryResponse
from app.services.dashboard_service import dashboard_summary

router = APIRouter()


@router.get("/summary", response_model=DashboardSummaryResponse)
def summary(
    parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    return dashboard_summary(db, parent.id)
