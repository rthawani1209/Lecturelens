import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .. import __version__
from ..config import get_settings
from .routes import auth, courses, health, lectures, media, search, study, uploads, watch

log = logging.getLogger(__name__)


def warm_models() -> None:
    """Load the ONNX models and run them once, so the first search isn't the one
    that waits several seconds for them."""
    if not (Path(get_settings().models_dir) / "minilm").exists():
        return  # running without models; search falls back to keywords
    try:
        from ..embed import clip_embedder, text_embedder

        text_embedder().embed(["warm up"])
        clip_embedder().embed_texts(["warm up"])
    except Exception:  # noqa: BLE001 - a cold first search is better than no API
        log.exception("couldn't warm the models")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # in the background: the API answers health checks and keyword search meanwhile
    threading.Thread(target=warm_models, name="warm-models", daemon=True).start()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.cookie_secure and settings.secret_key == "dev-only-not-secret":
        # https means a real deployment; the default key is in this public repo
        raise RuntimeError("set SECRET_KEY to a long random value")
    app = FastAPI(title="LectureLens API", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
        expose_headers=["Range"],  # resumable uploads report progress in it
    )

    # text with a NUL byte or half an emoji (lone surrogate) can't be stored in
    # Postgres; that's bad input, not a server error
    @app.exception_handler(psycopg.DataError)
    @app.exception_handler(UnicodeEncodeError)
    async def bad_text(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": "That text has characters we can't store."}, 422)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        # the default echoes the input back, and NaN or Infinity can't go in JSON
        errors = [{k: v for k, v in e.items() if k in ("loc", "msg", "type")} for e in exc.errors()]
        return JSONResponse({"detail": errors}, 422)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(courses.router)
    app.include_router(search.router)
    app.include_router(media.router)
    app.include_router(lectures.router)
    app.include_router(uploads.router)
    app.include_router(watch.router)
    app.include_router(study.router)
    return app


app = create_app()
