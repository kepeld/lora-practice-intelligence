"""ML Underground app: the v1 API + the dashboard, one service.

    uvicorn app.main:app --port 8000

The dashboard is plain static files (app/static) fetching /api/v1 — no build
step. DUCKDB_PATH selects the warehouse; `python -m app.demo_seed` creates a
small demo file for local work.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

try:
    # Local runs read secrets from the repo-root .env like the compose stack
    # does; in the container the file is absent and real env vars are set.
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

from .api import router

app = FastAPI(
    title="ML Underground — API v1",
    description="Rare-but-works LoRA practices, validated against HuggingFace outcomes.",
)
app.include_router(router)


@app.middleware("http")
async def static_no_cache(request, call_next):
    """Dashboard assets revalidate on every load (cheap 304s via ETag) —
    browsers otherwise cache them heuristically and serve stale JS/CSS."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


# Mounted last so /api/v1 wins; html=True serves index.html at "/".
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True),
          name="static")
