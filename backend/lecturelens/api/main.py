from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .. import __version__
from ..config import get_settings
from .routes import auth, courses, health, lectures, media, search, uploads


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="LectureLens API", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
        expose_headers=["Range"],  # resumable uploads report progress in it
    )
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(courses.router)
    app.include_router(search.router)
    app.include_router(media.router)
    app.include_router(lectures.router)
    app.include_router(uploads.router)
    return app


app = create_app()
