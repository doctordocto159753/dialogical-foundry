FROM node:22-alpine AS frontend-build
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FOUNDRY_DATA_DIR=/app/data \
    FOUNDRY_HOST=0.0.0.0 \
    FOUNDRY_PORT=8000
WORKDIR /app
RUN groupadd --system foundry && useradd --system --gid foundry --home /app foundry
COPY pyproject.toml README.md ./
COPY engine/ engine/
COPY server/ server/
COPY pipelines/ pipelines/
RUN pip install --no-cache-dir .
COPY PROMPTS.md SPEC.md ./
COPY --from=frontend-build /src/frontend/dist frontend/dist
RUN mkdir -p /app/data && chown -R foundry:foundry /app
USER foundry
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
