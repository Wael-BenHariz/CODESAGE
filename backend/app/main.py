"""
CodeSage Backend - Main Application
FastAPI application entry point with middleware and route registration.
"""

import logging
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import api_router
from app.config import settings
from app.db import close_db, init_db
from app.redis import close_redis

logger = logging.getLogger(__name__)

# Starlette >= 1.x renamed these status constants; accessing the old names
# emits deprecation warnings (and future versions remove them).
_CONTENT_TOO_LARGE_413 = getattr(status, "HTTP_413_CONTENT_TOO_LARGE", 413)
_UNPROCESSABLE_422 = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)

# The API process had no root handler, so every `app.*` INFO line (webhook
# queued/ignored/skipped decisions, the console-mail invitation link) was
# dropped before reaching uvicorn's output. Mirrors app/workers/main.py.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """
    Application lifespan manager.
    Handles startup and shutdown tasks.
    """
    # Startup
    await init_db()
    yield
    # Shutdown
    await close_db()
    await close_redis()


# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI-powered code review platform with GitHub integration",
    docs_url="/api/docs" if settings.ENABLE_API_DOCS else None,
    redoc_url="/api/redoc" if settings.ENABLE_API_DOCS else None,
    openapi_url="/api/openapi.json" if settings.ENABLE_API_DOCS else None,
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def limit_local_review_body(request: Request, call_next):
    """Reject oversized local-review requests before JSON parsing.

    The schema validator enforces the precise per-file/total limits; this
    middleware is the cheap first line of defense for the dev endpoint.
    """
    if (
        settings.LOCAL_REVIEW_DEV_MODE
        and request.method == "POST"
        and request.url.path == f"{settings.API_V1_PREFIX}/local-reviews/dev"
    ):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                size = int(content_length)
            except ValueError:
                size = 0
            if size > settings.LOCAL_REVIEW_DEV_MAX_BYTES + 1_000_000:
                return JSONResponse(
                    status_code=_CONTENT_TOO_LARGE_413,
                    content={"detail": "Request body too large"},
                )
    return await call_next(request)


# Exception handlers
def _json_safe_errors(errors: Sequence) -> Sequence:
    """Return only safe, client-relevant validation fields.

    Pydantic errors can contain ``input`` (a request value, potentially a whole
    source file) and ``ctx`` (live exception objects). Echoing them leaks source
    code and is not needed by the SPA or the VS Code extension, so whitelist the
    field location, message, and type only.
    """

    safe = []
    for err in errors:
        if not isinstance(err, dict):
            continue
        safe.append(
            {
                "loc": list(err.get("loc") or []),
                "msg": str(err.get("msg") or "Invalid value"),
                "type": str(err.get("type") or "value_error"),
            }
        )
    return safe


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Handle request validation errors with structured response."""
    safe_errors = _json_safe_errors(exc.errors())
    logger.warning(
        "Request validation failed on %s %s: %s",
        request.method,
        request.url.path,
        safe_errors,
    )
    return JSONResponse(
        status_code=_UNPROCESSABLE_422,
        content={
            "error": "Validation Error",
            "detail": safe_errors,
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Handle uncaught exceptions."""
    # Full traceback stays server-side; the response stays generic.
    logger.error(
        "Unhandled exception on %s %s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal Server Error",
            "message": str(exc) if settings.DEBUG else "An unexpected error occurred",
        },
    )


# Include API routes
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


# Root endpoint
@app.get("/", tags=["Root"])
async def root():
    """Root endpoint returning API information."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/api/docs",
    }


# Run with uvicorn (for development)
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
