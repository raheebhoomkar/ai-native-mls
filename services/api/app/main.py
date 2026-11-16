from fastapi import APIRouter, FastAPI

from app.core.config import get_settings
from app.core.errors import install_error_handling
from app.core.logging import configure_logging
from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.health.router import router as health_router
from app.modules.organisations.router import router as organisations_router

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    docs_enabled = settings.environment != "production"
    app = FastAPI(
        title="AI-Native MLS API",
        version="0.1.0",
        docs_url=f"{API_PREFIX}/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json" if docs_enabled else None,
    )
    install_error_handling(app)

    # Each module registers its router here. A module reads another module's data only
    # through that module's service functions, never by querying its tables.
    v1 = APIRouter(prefix=API_PREFIX)
    v1.include_router(health_router)
    v1.include_router(auth_router)
    v1.include_router(organisations_router)
    v1.include_router(audit_router)
    app.include_router(v1)
    return app


app = create_app()
