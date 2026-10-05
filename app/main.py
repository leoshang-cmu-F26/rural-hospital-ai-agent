import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.services.cost_report_service import get_cost_report_datasets


logger = logging.getLogger(__name__)

# Resolve the frontend relative to this file so the app works no
# matter which directory uvicorn is started from.
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def _warm_cost_report_catalog() -> None:
    """
    Download the CMS catalog in the background at startup so the
    first financial request does not pay for the 17 MB download.
    """
    try:
        get_cost_report_datasets()
    except Exception:  # noqa: BLE001 - best effort only
        logger.exception("Could not warm the CMS cost report catalog")


@asynccontextmanager
async def lifespan(_: FastAPI):
    threading.Thread(
        target=_warm_cost_report_catalog,
        name="cms-catalog-warmup",
        daemon=True,
    ).start()
    yield


app = FastAPI(
    title="Rural Hospital AI Agent",
    version="0.2.0",
    lifespan=lifespan,
)


app.include_router(router)
app.mount(
    "/demo",
    StaticFiles(
        directory=FRONTEND_DIR,
        html=True,
    ),
    name="demo",
)
