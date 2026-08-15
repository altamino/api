FROM debian:trixie-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

RUN useradd -U -u 1000 -m appuser && \
    mkdir -p /home/appuser/.cache/uv && \
    apt-get update && apt-get install -y --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    chown -R 1000:1000 /app /home/appuser/

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY --chown=1000:1000 . .

USER 1000

RUN uv sync

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8081"]
