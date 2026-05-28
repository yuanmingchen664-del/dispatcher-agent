from fastapi import FastAPI

from backend.app.api.routes import router
from backend.app.core.config import get_settings
from backend.app.db.session import init_db


settings = get_settings()

app = FastAPI(title=settings.app_name)
app.include_router(router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()

