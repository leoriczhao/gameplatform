#!/bin/sh
# 在服务器上把 web 切到指定镜像（CD 的 Deploy 工作流调用，也可手动执行）
#
# 用法:   deploy/release.sh <镜像> <发布标识>
#   例:   deploy/release.sh ghcr.io/leoriczhao/gameplatform:v1.2.0 v1.2.0
# 步骤:   拉镜像 → backup.sh 备份数据库 → 当前镜像另存为 gameplatform:before-<发布标识>
#         → 新镜像打成 gameplatform:latest → 只重建 web（tunnel 不动）→ 等容器 healthy。
#         不健康则自动切回 before 镜像并返回非零。数据卷从不替换。
# 手动回滚:
#   docker tag gameplatform:before-<发布标识> gameplatform:latest
#   docker compose -f deploy/docker-compose.yml up -d --no-deps --no-build web
#
set -eu
IMAGE="$1"
RELEASE="$2"
CONTAINER="${GP_CONTAINER:-gameplatform-web}"
cd "$(dirname "$0")/.."
compose() { docker compose -f deploy/docker-compose.yml "$@"; }

docker pull "$IMAGE"

if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  sh deploy/backup.sh 14
fi

PREV=""
if docker image inspect gameplatform:latest >/dev/null 2>&1; then
  PREV="gameplatform:before-$RELEASE"
  docker tag gameplatform:latest "$PREV"
  echo "previous image kept as $PREV"
fi
docker tag "$IMAGE" "gameplatform:$RELEASE"
docker tag "$IMAGE" gameplatform:latest
compose up -d --no-deps --no-build web

# compose 健康检查：interval 15s × retries 5，约 90s 内会给出结论
status=starting
for _ in $(seq 1 60); do
  status="$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null || echo missing)"
  case "$status" in
    healthy) echo "deployed $RELEASE: $CONTAINER healthy"; exit 0 ;;
    unhealthy) break ;;
  esac
  sleep 3
done

echo "deploy $RELEASE failed: $CONTAINER is $status" >&2
docker logs --tail 80 "$CONTAINER" >&2 || true
if [ -n "$PREV" ]; then
  docker tag "$PREV" gameplatform:latest
  compose up -d --no-deps --no-build web
  echo "rolled back to $PREV" >&2
fi
exit 1
