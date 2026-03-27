from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.v1.routes import router as api_router
from backend.app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    static_dir = Path(__file__).resolve().parent / "static"
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Python-first MVP for JD-tailored resumes.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["health"])
    def healthcheck() -> dict:
        return {"status": "ok", "app": settings.app_name, "version": settings.app_version}

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/app/")

    app.mount("/app", StaticFiles(directory=static_dir, html=True), name="app")
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
