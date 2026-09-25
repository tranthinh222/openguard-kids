import secrets

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.core.config import settings
from app.core.web_security import LOGIN_CSRF_COOKIE_NAME
from app.web.templating import templates

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    # This web route only serves the HTML shell. Actual authentication is
    # performed by POST /api/v1/auth/login from browser JavaScript.
    login_csrf = secrets.token_urlsafe(32)
    response = templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={
            "page_name": "login",
            "show_nav": False,
            "login_csrf": login_csrf,
        },
    )
    
    response.set_cookie(
        LOGIN_CSRF_COOKIE_NAME,
        login_csrf,
        httponly=True,
        secure=settings.web_cookie_secure,
        samesite="lax",
        max_age=600,
        path="/",
    )

    return response
