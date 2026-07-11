import os
import sys
import asyncio
import logging
import mimetypes
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
from fastapi import FastAPI, Response, status
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

class SPAStaticFiles:
    """Static file server that ONLY handles GET/HEAD requests.

    FastAPI's app.mount("/", StaticFiles) catches ALL HTTP methods (POST, PUT, DELETE)
    for paths not matched by route handlers, returning 405. This wrapper restricts
    the static file server to GET/HEAD only, letting non-GET requests fall through
    to FastAPI's 404 handler instead of blocking API calls.
    """
    def __init__(self, directory: str, html: bool = False):
        self._app = StaticFiles(directory=directory, html=html)

    async def __call__(self, scope: Scope, receive, send):
        if scope["type"] == "http" and scope["method"] not in ("GET", "HEAD"):
            # Let FastAPI handle this — don't intercept POST/PUT/DELETE
            return
        # Add no-cache headers
        async def send_wrapper(message):
            if message['type'] == 'http.response.start':
                headers = dict(message.get('headers', []))
                headers[b'cache-control'] = b'no-cache, no-store, must-revalidate'
                headers[b'pragma'] = b'no-cache'
                headers[b'expires'] = b'0'
                message['headers'] = list(headers.items())
            await send(message)
        await self._app(scope, receive, send_wrapper)

from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .logging_config import setup_logging
from .league_list import get_all_available_leagues as get_lightweight_leagues

setup_logging()
logger = logging.getLogger(__name__)


def _log_uncaught_exceptions(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.getLogger("backend").critical(
        "Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback)
    )

sys.excepthook = _log_uncaught_exceptions

mimetypes.add_type('application/javascript', '.js')

from contextlib import asynccontextmanager


async def _delayed_task(name, coro_fn, delay=1.0):
    await asyncio.sleep(delay)
    await coro_fn()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    on_render = os.environ.get("RENDER") is not None
    logger.info("Starting application (render=%s)...", on_render)

    if not on_render:
        _start_schedulers()

    yield


def _register_all_routers(app: FastAPI):
    """Register all routers eagerly. Must happen before mounting static files."""
    from .api.router_history import router as history_router
    app.include_router(history_router, prefix="/api")

    from .api.router_backtest import router as backtest_router
    app.include_router(backtest_router, prefix="/api")

    from .api.router_scanner import router as scanner_router
    app.include_router(scanner_router, prefix="/api")


def _start_schedulers():
    """Start background schedulers (local dev only)."""
    from .scheduler import run_scheduler_loop, run_arbitrage_scheduler_loop, run_live_odds_tracker_loop, run_dutching_scheduler_loop
    from .cluster_ai_tracker import run_cluster_ai_alerts_loop

    try:
        from .data_loader import startup_data_quality_check
        import concurrent.futures
        _executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        _executor.submit(startup_data_quality_check)
    except Exception as e:
        logger.warning(f"Data quality check skipped: {e}")

    try:
        from .validate_corners_model import quick_validation
        import concurrent.futures
        _executor2 = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        _executor2.submit(quick_validation)
    except Exception as e:
        logger.warning(f"Corners model validation skipped: {e}")

    asyncio.create_task(_delayed_task("scheduler", run_scheduler_loop, 0.5))
    asyncio.create_task(_delayed_task("arbitrage", run_arbitrage_scheduler_loop, 0.5))
    asyncio.create_task(_delayed_task("live_odds", run_live_odds_tracker_loop, 0.5))
    asyncio.create_task(_delayed_task("cluster_ai", run_cluster_ai_alerts_loop, 2.0))
    asyncio.create_task(_delayed_task("dutching", run_dutching_scheduler_loop, 0.5))


# ---- App construction (order matters: routes before mount) ----
app = FastAPI(title="Sports Betting Backtester API", lifespan=lifespan)

app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "https://backtest.pgjs.onrender.com",
        "https://backtest-pgjs.onrender.com",
        "https://football-backtester.onrender.com",
        "https://football-backtester-*.onrender.com"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Lightweight endpoints (no pandas, no CSV — instant response)
@app.get('/api/health', include_in_schema=False)
async def health_check():
    return {"status": "ok", "render": os.environ.get("RENDER") is not None}

@app.get('/api/leagues')
async def leagues_endpoint(source: str = "footballdata"):
    return get_lightweight_leagues(source)

@app.get('/favicon.ico', include_in_schema=False)
async def favicon():
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# Register heavy routers BEFORE mounting static files (critical: mount at "/" catches all)
_register_all_routers(app)

# Mount frontend static files last — only matches GET paths not handled by routers above
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'frontend')
if os.path.exists(frontend_dir):
    app.mount("/", SPAStaticFiles(directory=frontend_dir, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
