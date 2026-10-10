#!/bin/bash
# ============================================================
#  mhjc 服务器端部署脚本
#  用法：sudo bash deploy.sh <打包文件名> <版本号>
# ============================================================
set -euo pipefail

ARCHIVE="${1:-}"
VERSION="${2:-unknown}"
DEPLOY_PATH="/var/www/mhjc"
BACKUP_PATH="/var/www/mhjc-backups"
SERVICE_NAME="mhjc"
KEEP_BACKUPS=5

# 颜色输出
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[deploy]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC}   $*"; }
err()  { echo -e "${RED}[error]${NC}  $*" >&2; }

if [ -z "$ARCHIVE" ]; then
    err "缺少打包文件名"
    exit 1
fi

ARCHIVE_PATH="/tmp/${ARCHIVE}"
if [ ! -f "$ARCHIVE_PATH" ]; then
    err "打包文件不存在：$ARCHIVE_PATH"
    exit 1
fi

log "开始部署 mhjc 版本 ${VERSION}"
mkdir -p "$BACKUP_PATH"

# ─────────────────────────────────────────────
# 1. 备份当前版本
# ─────────────────────────────────────────────
if [ -d "$DEPLOY_PATH" ] && [ -f "$DEPLOY_PATH/server.py" ]; then
    BACKUP_FILE="${BACKUP_PATH}/mhjc-$(date +%Y%m%d-%H%M%S).tar.gz"
    log "备份当前版本 → ${BACKUP_FILE}"
    tar -czf "$BACKUP_FILE" \
        -C "$DEPLOY_PATH" \
        --exclude='venv' --exclude='data' --exclude='apps' \
        --exclude='__pycache__' --exclude='*.pyc' \
        . 2>/dev/null || true
fi

# ─────────────────────────────────────────────
# 2. 准备临时目录并解压
# ─────────────────────────────────────────────
TMP_NEW="/tmp/mhjc-new-$$"
rm -rf "$TMP_NEW"
mkdir -p "$TMP_NEW"
log "解压新版本到临时目录…"
tar -xzf "$ARCHIVE_PATH" -C "$TMP_NEW"

if [ ! -f "$TMP_NEW/server.py" ]; then
    err "解压后找不到 server.py，打包文件损坏"
    rm -rf "$TMP_NEW"
    exit 1
fi

# ─────────────────────────────────────────────
# 3. 保留数据目录
# ─────────────────────────────────────────────
mkdir -p "$DEPLOY_PATH/data" "$DEPLOY_PATH/apps"
# 把新代码合入部署目录（不覆盖 data/apps/venv）
log "合入新代码…"
rsync -a --delete \
    --exclude='data/' \
    --exclude='apps/' \
    --exclude='venv/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    "$TMP_NEW/" "$DEPLOY_PATH/"

rm -rf "$TMP_NEW"
rm -f  "$ARCHIVE_PATH"

# ─────────────────────────────────────────────
# 4. 安装 / 更新依赖
# ─────────────────────────────────────────────
cd "$DEPLOY_PATH"
if [ ! -d "venv" ]; then
    log "创建虚拟环境…"
    python3 -m venv venv
fi

log "更新 Python 依赖…"
./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install -r requirements.txt -q
./venv/bin/pip install gunicorn -q

# ─────────────────────────────────────────────
# 5. 权限
# ─────────────────────────────────────────────
chown -R www-data:www-data "$DEPLOY_PATH"
chmod -R 755 "$DEPLOY_PATH"
chmod -R 775 "$DEPLOY_PATH/data" "$DEPLOY_PATH/apps" 2>/dev/null || true

# ─────────────────────────────────────────────
# 6. 重启服务
# ─────────────────────────────────────────────
log "重启 ${SERVICE_NAME} 服务…"
systemctl restart "$SERVICE_NAME"
sleep 3

if ! systemctl is-active --quiet "$SERVICE_NAME"; then
    err "服务启动失败，查看日志："
    journalctl -u "$SERVICE_NAME" -n 40 --no-pager
    exit 1
fi

log "服务已启动"

# ─────────────────────────────────────────────
# 7. 本地健康检查
# ─────────────────────────────────────────────
log "本地健康检查…"
for i in 1 2 3 4 5; do
    if curl -fsS --max-time 3 http://127.0.0.1:5000/api/ping >/dev/null 2>&1; then
        log "健康检查通过 ✅"
        break
    fi
    if [ "$i" = "5" ]; then
        err "健康检查失败，服务可能无法正常工作"
        journalctl -u "$SERVICE_NAME" -n 40 --no-pager
        exit 1
    fi
    warn "第 ${i} 次失败，3 秒后重试…"
    sleep 3
done

# ─────────────────────────────────────────────
# 8. 清理旧备份（保留最近 N 个）
# ─────────────────────────────────────────────
log "清理旧备份（保留最近 ${KEEP_BACKUPS} 个）…"
cd "$BACKUP_PATH"
ls -1t mhjc-*.tar.gz 2>/dev/null | tail -n +$((KEEP_BACKUPS + 1)) | xargs -r rm -f
cd - >/dev/null

# ─────────────────────────────────────────────
# 9. 记录部署日志
# ─────────────────────────────────────────────
echo "$(date '+%Y-%m-%d %H:%M:%S') | version=${VERSION} | status=success" \
    >> "$DEPLOY_PATH/.deploy-history.log"

log "部署完成 🎉 版本 ${VERSION}"
