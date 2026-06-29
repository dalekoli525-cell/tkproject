"""Server entrypoint."""

from fastapi import FastAPI

from APP.SERVER.ROUTES import admin_config
from APP.SERVER.ROUTES import admin_panel
from APP.SERVER.ROUTES import auth
from APP.SERVER.ROUTES import client
from APP.SERVER.ROUTES import collection
from APP.SERVER.ROUTES import environments
from APP.SERVER.ROUTES import health
from APP.SERVER.ROUTES import tasks
from APP.SHARED.settings import settings
from APP.SERVER.security import ensure_default_users


def create_app() -> FastAPI:
    ensure_default_users()
    api = FastAPI(
        title=settings.app_name,
        version="0.1.0",
    )
    api.include_router(health.router)
    api.include_router(auth.router)
    api.include_router(client.router)
    api.include_router(environments.router)
    api.include_router(collection.router)
    api.include_router(tasks.router)
    api.include_router(admin_config.router)
    api.include_router(admin_panel.router)
    return api


app = create_app()
