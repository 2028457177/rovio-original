# syntax=docker/dockerfile:1
# 前端：Vite 构建 + nginx 静态服务 + API 反代到后端微服务
# 构建上下文为项目根（compose 中 context: .）

# ── 构建阶段 ──
FROM node:20-slim AS build
WORKDIR /app
RUN npm config set registry https://registry.npmmirror.com
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── 运行阶段 ──
FROM nginx:1.27-alpine AS runtime
COPY deploy/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY deploy/docker/microservice_proxy.conf /etc/nginx/snippets/microservice_proxy.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
