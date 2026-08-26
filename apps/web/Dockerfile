# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

FROM node:22-alpine AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_PDI_API_URL=http://localhost:8000
ARG PDI_VERSION=1.1.2
ARG PDI_REVISION=unknown
ARG PDI_BUILD_TIME=unknown
ENV NEXT_PUBLIC_PDI_API_URL=$NEXT_PUBLIC_PDI_API_URL \
    NEXT_PUBLIC_PDI_VERSION=$PDI_VERSION NEXT_PUBLIC_PDI_REVISION=$PDI_REVISION \
    NEXT_PUBLIC_PDI_BUILD_TIME=$PDI_BUILD_TIME
RUN npm run lint && npm run build

FROM node:22-alpine AS runtime
ARG PDI_VERSION=1.1.2
ARG PDI_REVISION=unknown
ARG PDI_BUILD_TIME=unknown
ARG PDI_SOURCE=https://github.com/maxsmolka/private-document-intelligence
LABEL org.opencontainers.image.title="PDI web" \
      org.opencontainers.image.description="Private Document Intelligence web application" \
      org.opencontainers.image.version=$PDI_VERSION \
      org.opencontainers.image.revision=$PDI_REVISION \
      org.opencontainers.image.source=$PDI_SOURCE \
      org.opencontainers.image.licenses="MIT"
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0 \
    PDI_WEB_VERSION=$PDI_VERSION PDI_WEB_REVISION=$PDI_REVISION \
    PDI_WEB_BUILD_TIME=$PDI_BUILD_TIME
RUN addgroup --system --gid 10001 pdi && adduser --system --uid 10001 --ingroup pdi pdi
COPY --from=builder --chown=pdi:pdi /app/public ./public
COPY --from=builder --chown=pdi:pdi /app/.next/standalone ./
COPY --from=builder --chown=pdi:pdi /app/.next/static ./.next/static
USER pdi
EXPOSE 3000
CMD ["node", "server.js"]
