from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime config comes from env vars (or a .env file). Defaults match docker-compose."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://lecturelens:lecturelens@localhost:5432/lecturelens"
    redis_url: str = "redis://localhost:6379/0"

    storage_backend: str = "s3"  # s3 | local
    local_storage_dir: str = "data/storage"
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "lectures"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"

    # Claude for Ask and flashcards. Without a key both fall back to extractive versions.
    anthropic_api_key: str = ""
    ai_model: str = "claude-opus-5-5"
    ai_per_minute: int = 6  # calls per user
    ai_daily_tokens: int = 200_000  # per user
    ai_monthly_tokens: int = 20_000_000  # whole site; a hard stop on spend

    # auth. secret_key signs upload URLs; set a long random value in production.
    secret_key: str = "dev-only-not-secret"
    app_url: str = "http://localhost:3000"  # the web app, where sign-in lands
    # the API as the browser sees it: behind the web app's /api proxy, so cookies stay first-party
    api_url: str = "http://localhost:3000/api"
    session_days: int = 30
    cookie_secure: bool = False  # true behind https
    google_client_id: str = ""
    google_client_secret: str = ""
    # empty smtp_url prints sign-in links to the log instead of emailing them
    smtp_url: str = ""  # smtp://user:pass@host:587
    mail_from: str = "LectureLens <noreply@lecturelens.local>"

    upload_dir: str = "data/uploads"
    upload_chunk_bytes: int = 8 * 1024**2

    # pretrained models, unpacked from the models-v1 release (scripts/get_models.sh)
    models_dir: str = "models"
    # TF Serving for the frame tagger; empty uses the CLIP probe fallback
    tagger_url: str = ""
    # TF Serving for the re-ranker; empty runs the same weights in NumPy
    reranker_url: str = ""
    rerank_top: int = 50
    # picked on the val questions: meaning-only tied hybrid + re-ranker there
    # (0.756 vs 0.759 NDCG@10) at 1/20 of the latency, see ml/rerank/README.md
    search_mode: str = "meaning"
    max_upload_bytes: int = 4 * 1024**3

    # search
    text_dim: int = 384  # all-MiniLM-L6-v2
    image_dim: int = 512  # CLIP ViT-B/32
    rrf_k: int = 60
    candidates: int = 50

    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
