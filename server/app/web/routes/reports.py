from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from app.web.templating import templates

router = APIRouter()


@router.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request):
    return templates.TemplateResponse(request=request, name="reports/index.html",
                                      context={"page_name": "reports", "show_nav": True})
