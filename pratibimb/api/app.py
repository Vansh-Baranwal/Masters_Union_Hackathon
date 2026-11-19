"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.database import init_db
from api.routers import trips, inbox, records, decisions, challenge, audit, export, ingest


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Pratibimb API",
        description=(
            "Every screenshot gets an owner, a trail and an honest label "
            "for how well it is supported."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(trips.router)
    app.include_router(inbox.router)
    app.include_router(records.router)
    app.include_router(decisions.router)
    app.include_router(challenge.router)
    app.include_router(audit.router)
    app.include_router(export.router)
    app.include_router(ingest.router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
