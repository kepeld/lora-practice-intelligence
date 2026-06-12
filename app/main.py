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

from .api import router

app = FastAPI(
    title="ML Underground — API v1",
    description="Rare-but-works LoRA practices, validated against HuggingFace outcomes.",
)
app.include_router(router)

# Mounted last so /api/v1 wins; html=True serves index.html at "/".
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True),
          name="static")
