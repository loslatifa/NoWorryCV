from pathlib import Path
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.v1.routes import router as api_router
from backend.app.api.v1.profiles import router as profiles_router
from backend.app.api.v1.history import router as history_router
from backend.app.api.v1.applications import router as applications_router
from backend.app.api.v1.quality import router as quality_router
from backend.app.api.v1.interviews import router as interviews_router
from backend.app.api.v1.materials import router as materials_router
from backend.app.services.materials import get_material_store
from backend.app.api.v1.positions import router as positions_router
from backend.app.api.v1.templates import router as templates_router
from backend.app.services.interviews import get_interview_store
from backend.app.core.config import get_settings
from backend.app.services.rate_limit import SlidingWindowRateLimiter
from backend.app.services.runs.store import get_run_store
from backend.app.services.runs.queue import get_task_queue
from backend.app.services.runs.worker import start_task_workers
from backend.app.services.applications import get_application_store
from backend.app.services.quality import get_quality_store


logger = logging.getLogger(__name__)


@asynccontextmanager
async def app_lifespan(_app: FastAPI):
    start_task_workers()
    try:
        yield
    finally:
        get_task_queue().stop()
        close = getattr(get_run_store(), "close", None)
        if close:
            close()


def create_app() -> FastAPI:
    settings = get_settings()
    static_dir = Path(__file__).resolve().parent / "static"
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Python-first MVP for JD-tailored resumes.",
        lifespan=app_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[item.strip() for item in settings.cors_allowed_origins.split(",") if item.strip()],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    rate_limiter = SlidingWindowRateLimiter(
        settings.rate_limit_requests,
        settings.rate_limit_window_seconds,
    )
    limited_paths = {
        "{0}/resume/parse-upload".format(settings.api_prefix),
        "{0}/tailor-runs/upload".format(settings.api_prefix),
        "{0}/tailor-runs/upload-jobs".format(settings.api_prefix),
        "{0}/tailor-runs/confirmed-jobs".format(settings.api_prefix),
    }

    @app.middleware("http")
    async def limit_expensive_requests(request: Request, call_next):
        get_run_store().cleanup_expired()
        get_task_queue().cleanup_expired()
        get_application_store().cleanup_expired()
        get_quality_store().cleanup_expired()
        get_interview_store().cleanup_expired()
        get_material_store().cleanup_expired()
        profile_prefix = "{0}/candidate-profiles".format(settings.api_prefix)
        if request.method == "POST" and (
            request.url.path in limited_paths
            or request.url.path.endswith("/materials")
            or ("/interviews" in request.url.path and request.url.path.endswith(("/interviews", "/answers")))
            or request.url.path == profile_prefix
            or (request.url.path.startswith(profile_prefix + "/")
                and request.url.path.endswith(("/preview", "/jobs", "/applications")))
        ):
            client_host = request.client.host if request.client else "unknown"
            allowed, retry_after = rate_limiter.check(client_host)
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "请求过于频繁，请稍后再试。"},
                    headers={"Retry-After": str(retry_after)},
                )
        return await call_next(request)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API error for %s", request.url.path, exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "服务暂时不可用，请稍后重试。"})

    get_run_store().cleanup_expired()

    @app.get("/health", tags=["health"])
    def healthcheck() -> dict:
        return {"status": "ok", "app": settings.app_name, "version": settings.app_version}

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/app/")

    app.mount("/app", StaticFiles(directory=static_dir, html=True), name="app")
    app.include_router(api_router, prefix=settings.api_prefix)
    app.include_router(profiles_router, prefix=settings.api_prefix)
    app.include_router(history_router, prefix=settings.api_prefix)
    app.include_router(applications_router, prefix=settings.api_prefix)
    app.include_router(quality_router, prefix=settings.api_prefix)
    app.include_router(interviews_router, prefix=settings.api_prefix)
    app.include_router(materials_router, prefix=settings.api_prefix)
    app.include_router(positions_router, prefix=settings.api_prefix)
    app.include_router(templates_router, prefix=settings.api_prefix)
    return app


app = create_app()
