from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

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
        message = (
            error["msg"]
            if error["msg"]
            else template.format(**(error.get("ctx") or {}))
        )

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
    app.add_exception_handler(
        RequestValidationError,
        validation_exception_handler,
    )
    app.add_exception_handler(HTTPException, http_exception_handler)