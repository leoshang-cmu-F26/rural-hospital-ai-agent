from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router


app = FastAPI(
    title="Rural Hospital AI Agent",
    version="0.1.0",
)


app.include_router(router)
app.mount(
    "/demo",
    StaticFiles(
        directory="frontend",
        html=True,
    ),
    name="demo",
)