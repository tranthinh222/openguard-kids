from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.web.templating import templates

router = APIRouter()

@router.get("/policies", response_class=HTMLResponse)
def policies_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="policies/index.html",
        context={
            "page_name": "policies",
            "show_nav": True,
        },
    )

@router.get("/policies/{child_id}", response_class=HTMLResponse)
def policy_detail_page(child_id: str, request: Request):
    return templates.TemplateResponse(
        request=request,
        name="policies/detail.html",
        context={
            "page_name": "policy-detail",
            "show_nav": True,
            "child_id": child_id,
        },
    )