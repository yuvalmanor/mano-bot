"""FastAPI entry point. Task 1: health check only."""

from __future__ import annotations

import logging

from fastapi import FastAPI

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Mano Bot")


@app.get("/")
async def health() -> dict[str, str]:
    return {"status": "ok"}
