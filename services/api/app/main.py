from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.errors import install_error_handling
from app.core.logging import configure_logging
from app.modules.ai.redaction_router import (
    listing_redactions_router,
    media_redactions_router,
    redactions_router,
)
from app.modules.ai.router import router as ai_router
from app.modules.ai.router import runs_router as ai_runs_router
from app.modules.apikeys import middleware as apikeys_middleware
from app.modules.apikeys.router import router as apikeys_router
from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.collaboration.router import comments_router, notifications_router
from app.modules.collaboration.router import listing_router as collaboration_router
from app.modules.compliance.router import compliance_router, listing_scans_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.health.router import router as health_router
from app.modules.imports.router import imports_router, listing_import_router
from app.modules.jobs.router import router as jobs_router
from app.modules.listings.router import listings_router, properties_router
from app.modules.media.router import listing_media_router, media_router
from app.modules.organisations.router import public_router as invitations_router
from app.modules.organisations.router import router as organisations_router
from app.modules.outbox import models as _outbox_models  # noqa: F401  # no routes; registers the table
from app.modules.review import models as _review_models  # noqa: F401  # no routes; registers tables
from app.modules.valuation.router import listing_valuations_router, valuations_router
from app.modules.webhooks.router import router as webhooks_router
from app.modules.workflow.router import listing_workflows_router, workflows_router

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
    # Added before the error handling, so it runs inside it and sees the request ID.
    apikeys_middleware.install(app)
    install_error_handling(app)

    # Each module registers its router here. A module reads another module's data only
    # through that module's service functions, never by querying its tables.
    v1 = APIRouter(prefix=API_PREFIX)
    v1.include_router(health_router)
    v1.include_router(auth_router)
    v1.include_router(organisations_router)
    v1.include_router(invitations_router)
    v1.include_router(audit_router)
    v1.include_router(dashboard_router)
    v1.include_router(properties_router)
    v1.include_router(listings_router)
    v1.include_router(listing_media_router)
    v1.include_router(media_router)
    v1.include_router(ai_router)
    v1.include_router(ai_runs_router)
    v1.include_router(media_redactions_router)
    v1.include_router(listing_redactions_router)
    v1.include_router(redactions_router)
    v1.include_router(imports_router)
    v1.include_router(listing_import_router)
    v1.include_router(listing_scans_router)
    v1.include_router(compliance_router)
    v1.include_router(listing_valuations_router)
    v1.include_router(valuations_router)
    v1.include_router(listing_workflows_router)
    v1.include_router(workflows_router)
    v1.include_router(jobs_router)
    v1.include_router(apikeys_router)
    v1.include_router(webhooks_router)
    v1.include_router(collaboration_router)
    v1.include_router(comments_router)
    v1.include_router(notifications_router)
    app.include_router(v1)

    if settings.web_dist_dir is not None:
        # Registered last, so /api routes win. The web app uses hash routing, so
        # index.html at "/" plus its asset files is everything it needs.
        app.mount("/", StaticFiles(directory=settings.web_dist_dir, html=True), name="web")
    return app


app = create_app()
