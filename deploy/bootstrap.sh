#!/bin/bash
# ============================================================
#  mhjc 服务器首次初始化（只需运行一次）
#  用法：sudo bash bootstrap.sh <github_repo_url>
# ============================================================
set -euo pipefail

REPO_URL="${1:-}"
DEPLOY_PATH="/var/www/mhjc"
BACKUP_PATH="/var/www/mhjc-backups"

if [ -z "$REPO_URL" ]; then
    echo "用法：sudo bash bootstrap.sh https://github.com/用户名/mhjc.git"
    exit 1
fi

echo "▶ 更新系统软件包…"
apt update -y

echo "▶ 安装基础环境…"
apt install -y git nginx python3 python3-pip python3-venv \
    rsync curl certbot python3-certbot-nginx

echo "▶ 首次拉取代码…"
mkdir -p /var/www
if [ ! -d "$DEPLOY_PATH/.git" ]; then
    git clone "$REPO_URL" "$DEPLOY_PATH"
fi

mkdir -p "$BACKUP_PATH"
cd "$DEPLOY_PATH"

echo "▶ 创建虚拟环境并安装依赖…"
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
./venv/bin/pip install gunicorn

echo "▶ 安装 systemd 服务…"
cp deploy/mhjc.service /etc/systemd/system/mhjc.service
systemctl daemon-reload
systemctl enable mhjc
systemctl restart mhjc

echo "▶ 配置 Nginx…"
cp deploy/nginx.conf /etc/nginx/sites-available/mhjc
ln -sf /etc/nginx/sites-available/mhjc /etc/nginx/sites-enabled/mhjc
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo "▶ 数据目录权限…"
chown -R www-data:www-data "$DEPLOY_PATH"
chmod -R 775 "$DEPLOY_PATH/data" "$DEPLOY_PATH/apps" 2>/dev/null || true

# 给部署用户 sudo 权限（无密码执行部署脚本）
DEPLOY_USER="${SUDO_USER:-root}"
SUDO_FILE="/etc/sudoers.d/mhjc-deploy"
echo "${DEPLOY_USER} ALL=(ALL) NOPASSWD: /bin/bash /var/www/mhjc/deploy/deploy.sh, /bin/bash /var/www/mhjc/deploy/rollback.sh, /bin/systemctl restart mhjc, /bin/systemctl reload nginx" \
    > "$SUDO_FILE"
chmod 440 "$SUDO_FILE"

echo ""
echo "════════════════════════════════════════"
echo "✅ 服务器初始化完成"
echo ""
echo "验证："
echo "  systemctl status mhjc"
echo "  curl http://127.0.0.1:5000/api/ping"
echo ""
echo "下一步：在 GitHub 仓库配置 Secrets："
echo "  SERVER_HOST    = $(curl -s ifconfig.me || echo '你的公网IP')"
echo "  SERVER_USER    = ${DEPLOY_USER}"
echo "  SERVER_SSH_KEY = <服务器上的私钥内容>"
echo "════════════════════════════════════════"
