# AgentFlow container image — small, non-root, runs the ASGI app with uvicorn.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install the project (and its dependencies) first so this layer caches
# across source-only changes. README.md is referenced by pyproject metadata.
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --upgrade pip && pip install .

# Drop privileges and give the app a writable per-run workspace directory.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/workspaces \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Bind $PORT when the platform provides one (Render/Railway/Fly/Heroku set it);
# fall back to 8000 for local `docker run` / compose. `exec` hands signals
# straight to uvicorn for clean shutdowns.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
