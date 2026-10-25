FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# workers handle untrusted video files, so nothing runs as root
RUN useradd --create-home --uid 10001 app
WORKDIR /app

COPY pyproject.toml ./
COPY lecturelens ./lecturelens
COPY migrations ./migrations
RUN pip install --no-cache-dir . && mkdir -p data/uploads && chown -R app data

USER app
EXPOSE 8000
CMD ["uvicorn", "lecturelens.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
