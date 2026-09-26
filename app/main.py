"""FastAPI application entrypoint: wiring, lifespan, and routers."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db
from app.routers import auth, pages, runs


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="AgentFlow", lifespan=lifespan)
app.include_router(pages.router)
app.include_router(auth.router)
app.include_router(runs.router)
