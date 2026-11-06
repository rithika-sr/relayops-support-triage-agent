# RelayOps web image (Next.js standalone output).
FROM node:24-slim AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ENV NEXT_TELEMETRY_DISABLED=1
ARG RELAYOPS_API_INTERNAL_URL=http://api:8020
ENV RELAYOPS_API_INTERNAL_URL=$RELAYOPS_API_INTERNAL_URL
RUN npm run build

FROM node:24-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3020 HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
USER node
EXPOSE 3020
CMD ["node", "server.js"]
