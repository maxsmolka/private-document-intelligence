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
ENV NEXT_PUBLIC_PDI_API_URL=$NEXT_PUBLIC_PDI_API_URL
RUN npm run lint && npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup --system --gid 10001 pdi && adduser --system --uid 10001 --ingroup pdi pdi
COPY --from=builder --chown=pdi:pdi /app/public ./public
COPY --from=builder --chown=pdi:pdi /app/.next/standalone ./
COPY --from=builder --chown=pdi:pdi /app/.next/static ./.next/static
USER pdi
EXPOSE 3000
CMD ["node", "server.js"]
