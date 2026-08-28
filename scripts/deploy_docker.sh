#!/usr/bin/env bash
# 一键推送镜像到 Docker Hub
# 用法：
#   ./scripts/deploy_docker.sh              # 推 latest 标签
#   ./scripts/deploy_docker.sh v1.0.0       # 推指定 tag
#   DOCKERHUB_USER=xxx ./scripts/deploy_docker.sh v1.0.0

set -e

# ── 配置 ──────────────────────────────────────────
# 优先从环境变量取，其次从 .env 取
if [ -f .env ]; then
  set -a; source .env; set +a
fi
DOCKERHUB_USER="${DOCKERHUB_USER:-${DOCKERHUB_USERNAME:-你的dockerhub用户名}}"
IMAGE_NAME="enterprise-text2sql"
TAG="${1:-latest}"
FULL_TAG="${DOCKERHUB_USER}/${IMAGE_NAME}:${TAG}"

# ── 前置检查 ──────────────────────────────────────
if [ "$DOCKERHUB_USER" = "你的dockerhub用户名" ]; then
  echo "❌ 请先设置 Docker Hub 用户名："
  echo "   export DOCKERHUB_USER=你的用户名"
  echo "   或者在 .env 里加 DOCKERHUB_USER=你的用户名"
  exit 1
fi

if ! command -v docker &> /dev/null; then
  echo "❌ Docker 未安装"
  exit 1
fi

# ── 执行 ──────────────────────────────────────────
echo "🐳 登录 Docker Hub..."
docker login -u "$DOCKERHUB_USER"

echo "🔨 构建镜像 $FULL_TAG ..."
docker build -t "$FULL_TAG" -t "${DOCKERHUB_USER}/${IMAGE_NAME}:latest" .

echo "📤 推送 $FULL_TAG ..."
docker push "$FULL_TAG"

# 默认也更新 latest
if [ "$TAG" != "latest" ]; then
  echo "📤 同时推送 latest ..."
  docker push "${DOCKERHUB_USER}/${IMAGE_NAME}:latest"
fi

echo ""
echo "✅ 完成！"
echo "   别人可以用以下命令运行："
echo "   docker pull $FULL_TAG"
echo "   docker run -p 8000:8000 --env-file .env $FULL_TAG"