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

EXPOSE 8000

# seed.py 幂等：库里没数据时写入演示数据（含 20 天前的历史错题，用于演示"顽固误区"识别）
CMD ["sh", "-c", "python seed.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
