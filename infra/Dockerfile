FROM node:20-alpine AS web-build
WORKDIR /workspace
RUN corepack enable
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile
COPY apps/web apps/web
RUN pnpm --dir apps/web build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/
COPY apps/api/pyproject.toml apps/api/uv.lock apps/api/README.md ./
COPY apps/api/src ./src
RUN uv sync --no-dev --no-editable
COPY --from=web-build /workspace/apps/web/dist /app/static
EXPOSE 8080
CMD ["/app/.venv/bin/uvicorn", "newsroom_agent.main:app", "--host", "0.0.0.0", "--port", "8080"]
