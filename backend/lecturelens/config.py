from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime config comes from env vars (or a .env file). Defaults match docker-compose."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://lecturelens:lecturelens@localhost:5432/lecturelens"
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "lectures"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"

    anthropic_api_key: str = ""

    # search
    text_dim: int = 384  # all-MiniLM-L6-v2
    image_dim: int = 512  # CLIP ViT-B/32
    rrf_k: int = 60
    candidates: int = 50

    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
