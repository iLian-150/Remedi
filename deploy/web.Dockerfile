# Remedi 前端镜像：多阶段构建（node 打包 → nginx 托管 + 反代 /api）
# 构建上下文为仓库根目录
FROM node:22-alpine AS build

WORKDIR /app
COPY frontend/package*.json ./
ARG NPM_REGISTRY=https://registry.npmjs.org
RUN npm ci --registry="$NPM_REGISTRY"
COPY frontend/ ./
# VITE_API_BASE_URL 为空 → 走相对路径 /api，由同容器 nginx 反代到后端
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
