import hmac
from fastapi import HTTPException, Request, status

SESSION_COOKIE_NAME = "ogk_session"
LOGIN_CSRF_COOKIE_NAME = "ogk_login_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"

def verify_login_csrf(request: Request) -> None:
    cookie_token = request.cookies.get(LOGIN_CSRF_COOKIE_NAME, "")
    header_token = request.headers.get(CSRF_HEADER_NAME, "")

    if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid login CSRF token",
        )
