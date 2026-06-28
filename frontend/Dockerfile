# ── build stage ───────────────────────────────────────────────────────────
# Mock-data SPA (React 19 + Vite 7 + Tailwind 3 + shadcn). No backend calls —
# everything is served from the in-memory mock store, so no build-time API URL.
FROM node:22-alpine AS build
WORKDIR /app

# Install deps first for better layer caching.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# ── serve stage ───────────────────────────────────────────────────────────
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
