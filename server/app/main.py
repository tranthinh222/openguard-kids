from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import agent, auth, children, dashboard, enrollment, requests, commands
from app.core.config import settings
from app.core.exception_handlers import register_exception_handlers
from app.web.routes import auth as web_auth
from app.web.routes import children as web_children
from app.web.routes import dashboard as web_dashboard
from app.web.routes import policies as web_policies
from app.web.routes import requests as web_requests

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Database schema is managed by Alembic; do not create tables here
    yield

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

@app.get("/health", tags=["System"])
def health():
    return {"status": "ok"}

# Agent / programmatic API
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(children.router, prefix="/api/v1/children", tags=["Children"])
app.include_router(enrollment.router, prefix="/api/v1", tags=["Enrollment"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["Dashboard"])
app.include_router(agent.router, prefix="/api/v1/agent", tags=["Agent"])
app.include_router(requests.router, prefix="/api/v1", tags=["Requests"])
app.include_router(commands.router, prefix="/api/v1", tags=["Commands"])

# Parent dashboard web UI
app.include_router(web_auth.router, tags=["Web Auth"], include_in_schema=False)
app.include_router(web_children.router, tags=["Web Children"], include_in_schema=False)
app.include_router(web_dashboard.router, tags=["Web Dashboard"], include_in_schema=False)
app.include_router(web_policies.router, tags=["Web Policies"], include_in_schema=False)
app.include_router(web_requests.router, tags=["Web Requests"], include_in_schema=False)

BASE_DIR = Path(__file__).parents[1]
app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "dashboard" / "static")),
    name="static",
)

# Exception Handlers
register_exception_handlers(app)