from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import calls, incidents, metrics, ws
from app.config import settings
from app.db import dispose_db, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await dispose_db()


app = FastAPI(title="trace911", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(calls.router, prefix="/api", tags=["calls"])
app.include_router(incidents.router, prefix="/api", tags=["incidents"])
app.include_router(metrics.router, prefix="/api", tags=["metrics"])
app.include_router(ws.router, tags=["ws"])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
