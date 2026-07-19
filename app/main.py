"""DrawTally API — FastAPI application entry point."""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.exceptions import DrawTallyError, RateLimitError
from app.core.logging import configure_logging, get_logger
from app.routers import analyze, export, health, tally, upload
from app.utils.file_utils import cleanup_expired_jobs
from app.utils.response import fail

configure_logging()
logger = get_logger(__name__)

async def _cleanup_loop():
    while True:
        try:
            removed = cleanup_expired_jobs()
            if removed:
                logger.info("Cleaned up %d expired job(s).", removed)
        except Exception:
            logger.exception("Cleanup loop error")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("%s v%s starting up.", settings.APP_NAME, settings.VERSION)
    cleanup_task = asyncio.create_task(_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        logger.info("%s shutting down.", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description="Engineering drawing vs BOM quantity verification API.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── lightweight in-memory rate limiting (per client IP, sliding window) ──
_request_log: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path.startswith("/api/upload"):
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        window = 60.0
        log = _request_log[client_ip]
        while log and now - log[0] > window:
            log.popleft()
        if len(log) >= settings.RATE_LIMIT_PER_MINUTE:
            err = RateLimitError(
                f"Rate limit exceeded: max {settings.RATE_LIMIT_PER_MINUTE} uploads/minute."
            )
            return JSONResponse(
                status_code=err.status_code,
                content=fail(err.code, err.message, err.details),
            )
        log.append(now)
    return await call_next(request)


# ── error handling ───────────────────────────────────────────────────────
@app.exception_handler(DrawTallyError)
async def drawtally_error_handler(request: Request, exc: DrawTallyError):
    logger.warning("%s: %s", exc.code, exc.message, extra={"extra_fields": {"path": str(request.url)}})
    return JSONResponse(
        status_code=exc.status_code,
        content=fail(exc.code, exc.message, exc.details),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s", request.url)
    return JSONResponse(
        status_code=500,
        content=fail("INTERNAL_ERROR", "An unexpected error occurred."),
    )


# ── routers ───────────────────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(upload.router)
app.include_router(analyze.router)
app.include_router(tally.router)
app.include_router(export.router)


from fastapi.responses import HTMLResponse
import os

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Serve the single-page frontend."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "drawtally.html")
    if not os.path.exists(path):
        path = "drawtally.html"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except Exception as e:
        logger.exception("Failed to read drawtally.html")
        return HTMLResponse(content=f"Error loading UI: {e}", status_code=500)



