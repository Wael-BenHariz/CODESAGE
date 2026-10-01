"""
CodeSage Backend - Main Application
FastAPI application entry point with middleware and route registration.
"""

import logging
from collections.abc import AsyncGenerator
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


# Exception handlers
def _json_safe_errors(errors: list) -> list:
    """Make pydantic errors JSON-serializable.

    ``value_error`` entries carry the live exception instance in ``ctx``
    (e.g. a validator's ValueError), which json.dumps cannot serialize —
    that turned every such 422 into a 500. Stringify non-primitive ctx.
    """

    for err in errors:
        ctx = err.get("ctx")
        if isinstance(ctx, dict):
            err["ctx"] = {
                key: (
                    value
                    if isinstance(value, (str, int, float, bool, type(None)))
                    else str(value)
                )
                for key, value in ctx.items()
            }
    return errors


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Handle request validation errors with structured response."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "Validation Error",
            "detail": _json_safe_errors(exc.errors()),
            "body": exc.body,
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
