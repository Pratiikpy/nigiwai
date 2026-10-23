# Nigiwai web app. Build from the repository root:  docker build -f apps/web/Dockerfile -t nigiwai-web .
FROM node:24-slim AS build
RUN corepack enable
WORKDIR /repo
COPY pnpm-workspace.yaml package.json pnpm-lock.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile --filter @nigiwai/web...
COPY apps/web apps/web
# The API origin is baked into the rewrite at build time; override with --build-arg for another host.
ARG NIGIWAI_API_ORIGIN=http://api:8000
ENV NIGIWAI_API_ORIGIN=$NIGIWAI_API_ORIGIN NEXT_TELEMETRY_DISABLED=1
RUN pnpm --filter @nigiwai/web build

FROM node:24-slim AS runtime
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /app
RUN useradd --system --create-home --uid 10001 nigiwai
COPY --from=build --chown=nigiwai:nigiwai /repo/apps/web/.next/standalone ./
COPY --from=build --chown=nigiwai:nigiwai /repo/apps/web/.next/static ./apps/web/.next/static
COPY --from=build --chown=nigiwai:nigiwai /repo/apps/web/public ./apps/web/public
USER nigiwai
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=4s --start-period=15s --retries=4 \
  CMD node -e "fetch('http://127.0.0.1:3000/login').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "apps/web/server.js"]
