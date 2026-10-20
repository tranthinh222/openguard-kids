from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.web.templating import templates

router = APIRouter()

@router.get("/requests", response_class=HTMLResponse)
def request_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="requests/index.html",
        context={
            "page_name": "requests",
            "show_nav": True,
        },
    )