from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import agent, auth, children, enrollment
from app.core.config import settings
from app.core.exception_handlers import register_exception_handlers

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

app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(children.router, prefix="/api/v1/children", tags=["Children"])
app.include_router(enrollment.router, prefix="/api/v1", tags=["Enrollment"])
app.include_router(agent.router, prefix="/api/v1/agent", tags=["Agent"])

register_exception_handlers(app)