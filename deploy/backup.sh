#!/bin/sh
# Stream SQLite 备份脚本（v1.0-e，随 cron 运行）
#
# 用法:   deploy/backup.sh [保留份数]        # 默认保留最近 14 份
# 说明:   数据在 gameplatform-scores 卷（容器内 /data/scores.db）；
#         备份写到同一卷的 /data/backups/（随卷持久化，不受容器重建影响）。
#         sqlite3 的在线 .backup API 保证一致性（WAL 下也安全）。
# cron 示例（每天 03:30）:
#   30 3 * * * cd /home/leoric/gameplatform && deploy/backup.sh 14 >> /var/log/gp-backup.log 2>&1
#
# 恢复演练:
#   cd ~/gameplatform && docker compose -f deploy/docker-compose.yml stop web
#   docker run --rm -v gameplatform_gameplatform-scores:/data python:3.12-slim \
#     sh -c 'cp /data/backups/scores-YYYYMMDD-HHMMSS.db /data/scores.db'
#   docker compose -f deploy/docker-compose.yml start web
#
set -eu
KEEP="${1:-14}"
CONTAINER="${GP_CONTAINER:-gameplatform-web}"
DB="/data/scores.db"
BACKUP_DIR="/data/backups"
STAMP="$(date +%Y%m%d-%H%M%S)"

docker exec "$CONTAINER" python -c "
import sqlite3, os
os.makedirs('$BACKUP_DIR', exist_ok=True)
src = sqlite3.connect('$DB')
dst = sqlite3.connect('$BACKUP_DIR/scores-$STAMP.db')
src.backup(dst)
dst.close()
src.close()
print('backup ok: $BACKUP_DIR/scores-$STAMP.db')
"

# 只保留最近 KEEP 份
docker exec "$CONTAINER" python -c "
import glob, os
files = sorted(glob.glob('$BACKUP_DIR/scores-*.db'))
for f in files[:-int('$KEEP')]:
    os.remove(f)
    print('pruned', f)
"

echo '--- current backups:'
docker exec "$CONTAINER" sh -c "ls -la $BACKUP_DIR"
