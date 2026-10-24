# Remedi 后端镜像
FROM python:3.11-slim

WORKDIR /app

ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"
RUN python -m venv "$VIRTUAL_ENV"

COPY requirements.txt .
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir -r requirements.txt --index-url "$PIP_INDEX_URL"

COPY . .
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# 默认不生成演示数据；需要时可显式设置 SEED_DEMO_DATA=true。
ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]
