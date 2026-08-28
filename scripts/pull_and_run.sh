#!/usr/bin/env bash
# 一键从 Docker Hub 拉取并启动
# 用法：
#   ./scripts/pull_and_run.sh
#   ./scripts/pull_and_run.sh v1.0.0
#   DOCKERHUB_USER=xxx ./scripts/pull_and_run.sh v1.0.0
#
# 需要同目录有 .env 文件（包含 DEEPSEEK_V4_FLASH_KEY 和 SILICONFLOW_API_KEY）

set -e

DOCKERHUB_USER="${DOCKERHUB_USER:-${DOCKERHUB_USERNAME:-你的dockerhub用户名}}"
IMAGE_NAME="enterprise-text2sql"
TAG="${1:-latest}"
FULL_TAG="${DOCKERHUB_USER}/${IMAGE_NAME}:${TAG}"
CONTAINER_NAME="enterprise-text2sql"
PORT="${PORT:-8000}"

if [ "$DOCKERHUB_USER" = "你的dockerhub用户名" ]; then
  echo "❌ 请指定 Docker Hub 用户名："
  echo "   DOCKERHUB_USER=xxx $0 v1.0.0"
  exit 1
fi

if [ ! -f .env ]; then
  echo "⚠️  当前目录没有 .env 文件，请先创建（含 DEEPSEEK_V4_FLASH_KEY 和 SILICONFLOW_API_KEY）"
  exit 1
fi

echo "📥 拉取镜像 $FULL_TAG ..."
docker pull "$FULL_TAG"

# 如果同名容器已存在，先停掉
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "🛑 停止已有容器 $CONTAINER_NAME ..."
  docker stop "$CONTAINER_NAME" >/dev/null
  docker rm "$CONTAINER_NAME" >/dev/null
fi

echo "🚀 启动容器 $CONTAINER_NAME ..."
docker run -d \
  --name "$CONTAINER_NAME" \
  -p "${PORT}:8000" \
  --env-file .env \
  --restart unless-stopped \
  "$FULL_TAG"

echo ""
echo "✅ 启动成功！"
echo "   聊天界面: http://localhost:${PORT}/demo"
echo "   健康检查: http://localhost:${PORT}/health"
echo ""
echo "查看日志: docker logs -f $CONTAINER_NAME"
echo "停止服务: docker stop $CONTAINER_NAME"