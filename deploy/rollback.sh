#!/bin/bash
# ============================================================
#  mhjc 回滚脚本：从最近备份恢复
# ============================================================
set -euo pipefail

DEPLOY_PATH="/var/www/mhjc"
BACKUP_PATH="/var/www/mhjc-backups"
SERVICE_NAME="mhjc"

log() { echo "[rollback] $*"; }

LATEST=$(ls -1t "$BACKUP_PATH"/mhjc-*.tar.gz 2>/dev/null | head -1)
if [ -z "$LATEST" ]; then
    echo "[rollback] 没有可用备份，跳过回滚"
    exit 0
fi

log "从备份恢复：$LATEST"
TMP=$(mktemp -d)
tar -xzf "$LATEST" -C "$TMP"

rsync -a --delete \
    --exclude='data/' \
    --exclude='apps/' \
    --exclude='venv/' \
    "$TMP/" "$DEPLOY_PATH/"

rm -rf "$TMP"
chown -R www-data:www-data "$DEPLOY_PATH"

systemctl restart "$SERVICE_NAME"
sleep 3

if systemctl is-active --quiet "$SERVICE_NAME"; then
    log "回滚成功 ✅"
    echo "$(date '+%Y-%m-%d %H:%M:%S') | rollback from ${LATEST} | status=success" \
        >> "$DEPLOY_PATH/.deploy-history.log"
else
    log "回滚后服务仍然异常，请人工介入 ❌"
    exit 1
fi
