# Nigiwai API. Build from the repository root:  docker build -f apps/api/Dockerfile -t nigiwai-api .
FROM node:24-slim AS node

FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/qloo-guard/pyproject.toml packages/qloo-guard/README.md packages/qloo-guard/
COPY packages/qloo-guard/src packages/qloo-guard/src
COPY packages/tribes/pyproject.toml packages/tribes/README.md packages/tribes/
COPY packages/tribes/src packages/tribes/src
COPY packages/fit/pyproject.toml packages/fit/README.md packages/fit/
COPY packages/fit/src packages/fit/src
COPY apps/api/pyproject.toml apps/api/
COPY apps/api/src apps/api/src
RUN uv sync --frozen --no-dev --package nigiwai-api

FROM python:3.13-slim AS runtime
# Node runs the Qloo harness (the preferred transport for agent work); REST is the automatic fallback.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 NIGIWAI_ENV=production
WORKDIR /app
RUN useradd --system --create-home --uid 10001 nigiwai
COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/packages /app/packages
COPY --from=build /app/apps /app/apps
COPY db /app/db
COPY package.json /app/package.json
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && cd /app && npm install --no-audit --no-fund --ignore-scripts \
 && chown -R nigiwai:nigiwai /app
USER nigiwai
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=4s --start-period=20s --retries=4 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"
CMD ["uvicorn", "nigiwai_api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
