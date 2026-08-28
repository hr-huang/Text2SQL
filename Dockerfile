# Enterprise Text2SQL Docker image
# 用法：
#   docker build -t enterprise-text2sql:latest .
#   docker compose up

FROM python:3.11-slim

# 系统依赖：jieba / rank_bm25 需要编译环境
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖（缓存友好）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目
COPY . .

# 数据/缓存目录（容器内可写）
RUN mkdir -p /app/chroma_data /app/output

# 容器内默认环境
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# 启动入口
ENTRYPOINT ["python", "-m", "app.main"]