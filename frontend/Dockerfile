# ── build stage ───────────────────────────────────────────────────────────
# React 19 + Vite 7 + Tailwind 3 + shadcn SPA against the real API. By default the
# bundle carries NO absolute API URL (same-origin via the nginx proxy below); the
# origin override comes from .env through the compose build arg.
FROM node:22-alpine AS build
WORKDIR /app

# Install deps first for better layer caching.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# Vite reads import.meta.env.VITE_* at build time — bake the .env-provided value.
ARG VITE_API_BASE=
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

# ── serve stage ───────────────────────────────────────────────────────────
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
