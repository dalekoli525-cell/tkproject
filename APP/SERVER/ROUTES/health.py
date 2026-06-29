"""Health endpoints that do not require external services."""

from fastapi import APIRouter

from APP.SHARED.settings import settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check():
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
    }


@router.get("/ready")
def readiness_check():
    # Keep this endpoint local-only for now. Real DB/Redis checks will be added
    # after the server endpoints are wired to production services.
    return {
        "status": "ready",
        "external_services_checked": False,
    }
