from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import auth, pages, search
from app.core.elastic import close_es_client
from app.db.database import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    # The relational schema is tiny, so eager initialization keeps local setup simple.
    init_db()
    yield
    await close_es_client()


app = FastAPI(title="NK XiaoLingTong", lifespan=lifespan)

static_dir = Path(__file__).parent / "static"
image_dir = Path(__file__).resolve().parents[2] / "image"
app.mount("/static", StaticFiles(directory=static_dir), name="static")
app.mount("/images", StaticFiles(directory=image_dir, check_dir=False), name="images")

app.include_router(pages.router)
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(search.router, prefix="/api", tags=["search"])
