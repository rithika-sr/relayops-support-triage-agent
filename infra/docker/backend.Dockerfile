# RelayOps API and worker image (same image, different command).
FROM ghcr.io/astral-sh/uv:0.12.23 AS uv
FROM python:3.12-slim
# tesseract reads scanned PDF pages; the English model ships with the distro package.
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
COPY data/ /app/data/
COPY evals/ /app/evals/
RUN uv sync --frozen --no-dev
RUN useradd --create-home relayops && mkdir -p /app/.local && chown -R relayops /app
USER relayops
EXPOSE 8020
CMD ["uv", "run", "--no-sync", "uvicorn", "relayops.api.main:app", "--host", "0.0.0.0", "--port", "8020"]
