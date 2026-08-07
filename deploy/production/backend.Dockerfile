FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONNOUSERSITE=1 \
    PYTHONSAFEPATH=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN groupadd --gid 10001 poker \
    && useradd --uid 10001 --gid poker --no-create-home --shell /usr/sbin/nologin poker \
    && python -m pip install --no-cache-dir uv==0.11.3

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/poker_arena ./poker_arena
COPY backend/models ./models
RUN uv sync --frozen --no-dev \
    && mkdir -p /var/lib/poker/logs \
    && chown -R poker:poker /var/lib/poker

USER 10001:10001
EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "poker_arena.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
