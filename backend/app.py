import os
import asyncio
import mimetypes
from fastapi import FastAPI, Response, status
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

# Force correct MIME type mapping for .js files on Windows
mimetypes.add_type('application/javascript', '.js')

# Import modular routers
from .api.router_history import router as history_router
from .api.router_backtest import router as backtest_router
from .api.router_scanner import router as scanner_router

from contextlib import asynccontextmanager

from .scheduler import run_scheduler_loop, run_arbitrage_scheduler_loop, run_live_odds_tracker_loop, run_dutching_scheduler_loop
from .cluster_ai_tracker import run_cluster_ai_alerts_loop


async def _delayed_task(name, coro_fn, delay=1.0):
    await asyncio.sleep(delay)
    await coro_fn()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting background scheduler...")
    asyncio.create_task(_delayed_task("scheduler", run_scheduler_loop, 0.5))
    asyncio.create_task(_delayed_task("arbitrage", run_arbitrage_scheduler_loop, 0.5))
    asyncio.create_task(_delayed_task("live_odds", run_live_odds_tracker_loop, 0.5))
    asyncio.create_task(_delayed_task("cluster_ai", run_cluster_ai_alerts_loop, 2.0))
    asyncio.create_task(_delayed_task("dutching", run_dutching_scheduler_loop, 0.5))
    yield


app = FastAPI(title="Sports Betting Backtester API", lifespan=lifespan)

# Enable Gzip compression for API responses (saves bandwidth on large payloads)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Restrict CORS to safe development origins and production domains
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000", "https://backtest.pgjs.onrender.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Serves a 204 No Content for favicon to prevent 404 logs in browsers
@app.get('/favicon.ico', include_in_schema=False)
async def favicon():
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# Include APIRouters with prefix "/api"
app.include_router(history_router, prefix="/api")
app.include_router(backtest_router, prefix="/api")
app.include_router(scanner_router, prefix="/api")

# Serve frontend static files
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'frontend')
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
