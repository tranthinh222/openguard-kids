from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
import logging
from sqlalchemy.exc import OperationalError

MESSAGES = {
    "missing": "This field is required.",
    "string_type": "This value must be a string.",
    "string_too_short": "Must have at least {min_length} characters.",
    "string_too_long": "Cannot exceed {max_length} characters.",
    "json_invalid": "Invalid JSON content.",
    "value_error": "Invalid field's value."
}

async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
):
    errors = []

    for error in exc.errors():
        template = MESSAGES.get(error["type"])
        # Do not echo custom validator input (which can contain secrets) into errors.
        message = template.format(**(error.get('ctx') or {})) if template else 'Invalid field value.'

        errors.append({
            "field": ".".join(str(part) for part in error["loc"]),
            "code": error["type"],
            "message": message,
        })

    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION_ERROR",
            "message": "Invalid input data.",
            "errors": errors,
        },
    )

async def http_exception_handler(
    _request: Request,
    exc: HTTPException,
):
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "code": f"HTTP_{exc.status_code}",
            "message": exc.detail,
        },
    )

def register_exception_handlers(app: FastAPI):
    async def unexpected_error(request, exc):
        request_id = getattr(request.state, 'request_id', '')
        # Exception text/SQL parameters can contain submitted secrets; log only the type and ID.
        logging.getLogger('openguard.server').error('Unhandled %s request_id=%s', type(exc).__name__, request_id)
        database_unavailable = isinstance(exc, OperationalError)
        headers = {'Cache-Control': 'no-store', 'X-Request-ID': request_id}
        if database_unavailable:
            headers['Retry-After'] = '5'
        return JSONResponse(status_code=503 if database_unavailable else 500,
                            content={'code': 'DATABASE_UNAVAILABLE' if database_unavailable else 'INTERNAL_ERROR',
                                     'message': 'Database temporarily unavailable' if database_unavailable else 'Internal server error',
                                     'request_id': request_id}, headers=headers)
    app.add_exception_handler(Exception, unexpected_error)
    app.add_exception_handler(
        RequestValidationError,
        validation_exception_handler,
    )
    app.add_exception_handler(HTTPException, http_exception_handler)
