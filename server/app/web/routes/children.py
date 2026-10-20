from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.web.templating import templates

router = APIRouter()


@router.get("/children", response_class=HTMLResponse)
def children_page(request: Request):
    legacy_view = request.query_params.get("view")
    if legacy_view == "policies":
        return RedirectResponse(url="/policies", status_code=307)
    if legacy_view == "requests":
        return RedirectResponse(url="/requests", status_code=307)

    return templates.TemplateResponse(
        request=request,
        name="children/index.html",
        context={
            "page_name": "children", 
            "show_nav": True
        },
    )


@router.get("/children/new", response_class=HTMLResponse)
def child_create_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="children/create.html",
        context={
            "page_name": "child-create", 
            "show_nav": True
        },
    )


@router.get("/children/{child_id}", response_class=HTMLResponse)
def child_detail(child_id: str, request: Request):
    legacy_view = request.query_params.get("view")
    if legacy_view == "policies":
        return RedirectResponse(url=f"/policies/{child_id}", status_code=307)
    if legacy_view == "requests":
        return RedirectResponse(url=f"/requests?child_id={child_id}", status_code=307)

    return templates.TemplateResponse(
        request=request,
        name="children/detail.html",
        context={
            "page_name": "child-detail",
            "show_nav": True,
            "child_id": child_id,
        },
    )
