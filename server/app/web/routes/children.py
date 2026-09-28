from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.web.templating import templates

router = APIRouter()


@router.get("/children", response_class=HTMLResponse)
def children_page(request: Request):
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
    return templates.TemplateResponse(
        request=request,
        name="children/detail.html",
        context={
            "page_name": "child-detail",
            "show_nav": True,
            "child_id": child_id,
        },
    )
