from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.web.templating import templates

router = APIRouter()


@router.get("/")
def root():
    return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="dashboard/index.html",
        context={
            "page_name": "dashboard", 
            "show_nav": True
        },
    )
