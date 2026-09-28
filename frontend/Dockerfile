# ─── сборка ────────────────────────────────────────────────────────────────
ARG REGISTRY=docker.io/library
FROM ${REGISTRY}/node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci || npm install

COPY . .
# Режим данных задаётся на этапе сборки: mock — автономное демо, api — боевой бэкенд
ARG VITE_DATA_SOURCE=api
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_DATA_SOURCE=$VITE_DATA_SOURCE
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

# ─── раздача ───────────────────────────────────────────────────────────────
FROM ${REGISTRY}/nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
