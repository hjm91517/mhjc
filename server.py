#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mhjc 服务器
-----------
一个类 macOS 网页桌面系统的后端：
  · 用户注册 / 登录（设备指纹唯一注册）
  · 管理员后台（默认密码 1）
  · AppStore 应用投稿、审核、上架、更新
  · 用户应用的 HTML 运行与 Python 后端沙箱
  · MJ 通用货币：充值 / 转账 / 消费（防刷）
  · 内置 QQ 即时聊天
  · 壁纸 / 系统参数持久化
  · 完整调试接口

启动：
    pip install -r requirements.txt
    python server.py
然后访问：http://127.0.0.1:5000/        前台
         http://127.0.0.1:5000/admin   后台
"""

import os
import sys
import json
import time
import secrets
import sqlite3
import importlib.util
import traceback
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, request, jsonify, Blueprint, send_from_directory,
    Response, redirect, abort
)
from werkzeug.security import generate_password_hash, check_password_hash

try:
    from flask_cors import CORS
except ImportError:
    CORS = None


# ================================================================
#  路径与全局配置
# ================================================================
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(BASE_DIR, 'data')
APPS_DIR   = os.path.join(BASE_DIR, 'apps')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
DB_PATH    = os.path.join(DATA_DIR, 'mhjc.db')

for _d in (DATA_DIR, APPS_DIR, STATIC_DIR):
    os.makedirs(_d, exist_ok=True)

# 应用后端的模块缓存
_BACKEND_CACHE = {}

# 默认 AI 提示词模板
DEFAULT_PROMPT_TEMPLATE = """你是一名资深的 HTML 前端开发者。请帮我生成一个名为「{{app_name}}」的 Web 应用。

这个应用将运行在 mhjc 桌面系统的沙箱 iframe 中，请严格遵循下面的接口与规范。

## 一、可用的 mhjc 原生接口（无需自己实现登录注册）

1. 获取当前登录用户：
   const user = await window.mhjc.getUser();
   // user = { id, username, nickname, balance }

2. 本地持久化存储（按应用隔离）：
   await window.mhjc.storage.set("key", value);
   const v = await window.mhjc.storage.get("key");

3. 调用本应用专属后端（若勾选「需要 Python 后端」）：
   const res = await window.mhjc.fetch("/hello", {
     method: "POST",
     body: JSON.stringify({ /* ... */ })
   });
   const data = await res.json();

4. 发起 MJ 支付：
   const ok = await window.mhjc.pay.request(10, "购买道具");
   if (ok) { /* 支付成功 */ }

5. 系统通知：
   window.mhjc.notify("操作成功");

6. 关闭当前窗口：
   window.mhjc.close();

## 二、技术要求

1. 所有代码写在一个 HTML 文件中（HTML + CSS + JS 内联），不依赖外部 CDN。
2. 使用 CSS3 transition / animation，所有交互必须有丝滑过渡动画。
3. 必须同时适配鼠标与键盘操作，常用操作提供键盘快捷键。
4. 响应式布局，最小支持 600px 宽度的窗口。
5. 配色请使用深色玻璃拟态风格，与 macOS 视觉一致。
6. 代码必须无语法错误，可直接运行。

## 三、应用需求

{{user_idea}}

## 四、输出要求

请直接输出完整的 HTML 代码，不要有多余解释。"""


# ================================================================
#  Flask 初始化
# ================================================================
app = Flask(__name__, static_folder=None, static_url_path='')
app.config['SECRET_KEY'] = secrets.token_hex(32)
app.config['JSON_AS_ASCII'] = False
if CORS:
    CORS(app, supports_credentials=True)


# ================================================================
#  数据库
# ================================================================
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    # ---------- 用户 ----------
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        username           TEXT    UNIQUE NOT NULL,
        nickname           TEXT,
        password_hash      TEXT    NOT NULL,
        balance            REAL    DEFAULT 0,
        device_fingerprint TEXT    UNIQUE,
        banned             INTEGER DEFAULT 0,
        token              TEXT,
        token_expires      TEXT,
        created_at         TEXT
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_users_token ON users(token)')

    # ---------- 管理员 ----------
    c.execute('''CREATE TABLE IF NOT EXISTS admin (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        password_hash TEXT    NOT NULL,
        token         TEXT,
        token_expires TEXT
    )''')

    # ---------- 应用 ----------
    c.execute('''CREATE TABLE IF NOT EXISTS apps (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        name           TEXT    NOT NULL,
        icon           TEXT,
        description    TEXT,
        category       TEXT,
        version        TEXT    DEFAULT '1.0.0',
        html           TEXT,
        has_backend    INTEGER DEFAULT 0,
        backend_code   TEXT,
        developer_id   INTEGER,
        status         TEXT    DEFAULT 'pending',
        reject_reason  TEXT,
        downloads      INTEGER DEFAULT 0,
        created_at     TEXT,
        updated_at     TEXT
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_apps_status ON apps(status)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_apps_dev ON apps(developer_id)')

    # ---------- 安装 ----------
    c.execute('''CREATE TABLE IF NOT EXISTS installs (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL,
        app_id     INTEGER NOT NULL,
        version    TEXT,
        created_at TEXT,
        UNIQUE(user_id, app_id)
    )''')

    # ---------- 私信 ----------
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id   INTEGER NOT NULL,
        receiver_id INTEGER NOT NULL,
        content     TEXT    NOT NULL,
        read        INTEGER DEFAULT 0,
        created_at  TEXT
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_msg_pair ON messages(sender_id, receiver_id)')

    # ---------- 交易 ----------
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER NOT NULL,
        amount       REAL    NOT NULL,
        type         TEXT    NOT NULL,
        note         TEXT,
        related_user INTEGER,
        created_at   TEXT
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_tx_created ON transactions(created_at)')

    # ---------- 应用私有存储 ----------
    c.execute('''CREATE TABLE IF NOT EXISTS app_storage (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        app_id  INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        key     TEXT    NOT NULL,
        value   TEXT,
        UNIQUE(app_id, user_id, key)
    )''')

    # ---------- 系统设置 ----------
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT
    )''')

    # ---------- 默认管理员（密码 1） ----------
    row = c.execute('SELECT COUNT(*) FROM admin').fetchone()
    if row[0] == 0:
        c.execute(
            'INSERT INTO admin (password_hash) VALUES (?)',
            (generate_password_hash('1'),)
        )
        print('[init] 已创建默认管理员，密码：1')

    # ---------- 默认设置 ----------
    defaults = {
        'wallpaper':       'default',
        'welcome_mj':      '0',
        'prompt_template': DEFAULT_PROMPT_TEMPLATE,
    }
    for k, v in defaults.items():
        if not c.execute('SELECT 1 FROM settings WHERE key=?', (k,)).fetchone():
            c.execute('INSERT INTO settings (key, value) VALUES (?, ?)', (k, v))

    conn.commit()
    conn.close()


# ================================================================
#  通用工具
# ================================================================
def now_iso():
    return datetime.now().isoformat(timespec='seconds')


def user_public(u):
    """用户公开字段"""
    if not u:
        return None
    return {
        'id':       u['id'],
        'username': u['username'],
        'nickname': u['nickname'],
        'balance':  float(u['balance'] or 0),
    }


def get_setting(key, default=None):
    conn = get_db()
    row = conn.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    conn.close()
    return row['value'] if row else default


def set_setting(key, value):
    conn = get_db()
    conn.execute(
        'INSERT INTO settings (key, value) VALUES (?, ?) '
        'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
        (key, str(value))
    )
    conn.commit()
    conn.close()


def bearer_token():
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        return auth[7:].strip()
    return auth.strip()


def get_user_by_token(token):
    if not token:
        return None
    conn = get_db()
    u = conn.execute(
        '''SELECT * FROM users
           WHERE token=?
             AND (token_expires IS NULL OR token_expires > ?)''',
        (token, datetime.now().isoformat())
    ).fetchone()
    conn.close()
    return u


def get_admin_by_token(token):
    if not token:
        return None
    conn = get_db()
    a = conn.execute(
        '''SELECT * FROM admin
           WHERE token=?
             AND token_expires IS NOT NULL
             AND token_expires > ?''',
        (token, datetime.now().isoformat())
    ).fetchone()
    conn.close()
    return a


def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = get_user_by_token(bearer_token())
        if not user:
            return jsonify({'error': '登录已失效，请重新登录'}), 401
        if user['banned']:
            return jsonify({'error': '账号已被封禁'}), 403
        request.user = user
        return f(*args, **kwargs)
    return wrapper


def require_admin(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        admin = get_admin_by_token(bearer_token())
        if not admin:
            return jsonify({'error': '管理员未登录或会话已过期'}), 401
        request.admin = admin
        return f(*args, **kwargs)
    return wrapper


# ================================================================
#  用户 API
# ================================================================
@app.route('/api/ping', methods=['GET'])
def api_ping():
    return jsonify({'pong': True, 'time': now_iso()})


@app.route('/api/register', methods=['POST'])
def api_register():
    data      = request.get_json(silent=True) or {}
    username  = (data.get('username') or '').strip()
    password  = data.get('password') or ''
    nickname  = (data.get('nickname') or username).strip()
    device_id = (data.get('device_id') or '').strip()

    if len(username) < 2:
        return jsonify({'error': '用户名至少 2 个字符'}), 400
    if not password:
        return jsonify({'error': '密码不能为空'}), 400
    if not device_id:
        return jsonify({'error': '缺少设备标识，无法完成注册'}), 400

    conn = get_db()
    # 一设备一号
    if conn.execute('SELECT id FROM users WHERE device_fingerprint=?',
                    (device_id,)).fetchone():
        conn.close()
        return jsonify({'error': '该设备已注册过账号，一个设备仅可注册一个账号'}), 400

    if conn.execute('SELECT id FROM users WHERE username=?',
                    (username,)).fetchone():
        conn.close()
        return jsonify({'error': '用户名已被使用'}), 400

    try:
        welcome = float(get_setting('welcome_mj', '0') or 0)
    except Exception:
        welcome = 0.0

    token   = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(days=30)).isoformat()

    cur = conn.execute(
        '''INSERT INTO users
             (username, nickname, password_hash, balance,
              device_fingerprint, token, token_expires, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (username, nickname, generate_password_hash(password), welcome,
         device_id, token, expires, now_iso())
    )
    uid = cur.lastrowid

    if welcome > 0:
        conn.execute(
            '''INSERT INTO transactions
                 (user_id, amount, type, note, created_at)
               VALUES (?, ?, 'welcome', ?, ?)''',
            (uid, welcome, '注册赠送', now_iso())
        )

    conn.commit()
    user = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    conn.close()

    return jsonify({'token': token, 'user': user_public(user)})


@app.route('/api/login', methods=['POST'])
def api_login():
    data     = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    if not username or not password:
        return jsonify({'error': '请输入用户名和密码'}), 400

    conn = get_db()
    u = conn.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()

    if not u or not check_password_hash(u['password_hash'], password):
        conn.close()
        return jsonify({'error': '用户名或密码错误'}), 400

    if u['banned']:
        conn.close()
        return jsonify({'error': '该账号已被封禁'}), 403

    token   = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(days=30)).isoformat()

    conn.execute(
        'UPDATE users SET token=?, token_expires=? WHERE id=?',
        (token, expires, u['id'])
    )
    conn.commit()
    u = conn.execute('SELECT * FROM users WHERE id=?', (u['id'],)).fetchone()
    conn.close()

    return jsonify({'token': token, 'user': user_public(u)})


@app.route('/api/logout', methods=['POST'])
@require_auth
def api_logout():
    conn = get_db()
    conn.execute('UPDATE users SET token=NULL WHERE id=?', (request.user['id'],))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/me', methods=['GET'])
@require_auth
def api_me():
    return jsonify({'user': user_public(request.user)})


@app.route('/api/profile', methods=['POST'])
@require_auth
def api_profile():
    data = request.get_json(silent=True) or {}
    nick = (data.get('nickname') or '').strip()
    if not nick:
        return jsonify({'error': '昵称不能为空'}), 400
    if len(nick) > 32:
        return jsonify({'error': '昵称过长'}), 400

    conn = get_db()
    conn.execute('UPDATE users SET nickname=? WHERE id=?', (nick, request.user['id']))
    conn.commit()
    u = conn.execute('SELECT * FROM users WHERE id=?', (request.user['id'],)).fetchone()
    conn.close()
    return jsonify({'user': user_public(u)})


@app.route('/api/password', methods=['POST'])
@require_auth
def api_change_password():
    data = request.get_json(silent=True) or {}
    old  = data.get('old') or ''
    new  = data.get('new') or ''

    if not old or not new:
        return jsonify({'error': '请填写完整'}), 400
    if not check_password_hash(request.user['password_hash'], old):
        return jsonify({'error': '当前密码错误'}), 400
    if len(new) < 1:
        return jsonify({'error': '新密码不能为空'}), 400

    conn = get_db()
    conn.execute(
        'UPDATE users SET password_hash=? WHERE id=?',
        (generate_password_hash(new), request.user['id'])
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ================================================================
#  应用 API（前台）
# ================================================================
@app.route('/api/apps', methods=['GET'])
@require_auth
def api_apps_list():
    conn = get_db()
    rows = conn.execute(
        '''SELECT a.*, u.username AS developer_name
           FROM apps a
           LEFT JOIN users u ON u.id = a.developer_id
           WHERE a.status='published'
           ORDER BY a.updated_at DESC'''
    ).fetchall()
    conn.close()

    apps = [{
        'id':             r['id'],
        'name':           r['name'],
        'icon':           r['icon'],
        'description':    r['description'],
        'category':       r['category'],
        'version':        r['version'],
        'has_backend':    r['has_backend'],
        'downloads':      r['downloads'],
        'developer_name': r['developer_name'] or '匿名',
        'created_at':     r['created_at'],
        'updated_at':     r['updated_at'],
    } for r in rows]

    return jsonify({'apps': apps})


@app.route('/api/apps/mine', methods=['GET'])
@require_auth
def api_my_submissions():
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM apps WHERE developer_id=? ORDER BY updated_at DESC',
        (request.user['id'],)
    ).fetchall()
    conn.close()
    return jsonify({'apps': [dict(r) for r in rows]})


@app.route('/api/apps/submit', methods=['POST'])
@require_auth
def api_app_submit():
    data = request.get_json(silent=True) or {}

    name = (data.get('name') or '').strip()
    html = data.get('html') or ''
    if not name:
        return jsonify({'error': '请填写应用名称'}), 400
    if len(html) < 20:
        return jsonify({'error': 'HTML 代码太短'}), 400
    if len(html) > 2 * 1024 * 1024:
        return jsonify({'error': 'HTML 代码过长（上限 2MB）'}), 400

    has_backend = 1 if data.get('has_backend') else 0
    backend_code = (data.get('backend_code') or '') if has_backend else ''

    if has_backend and 'def handle' not in backend_code and \
       'def register' not in backend_code:
        return jsonify({'error': '后端代码必须包含 handle 函数或 register 函数'}), 400

    conn = get_db()
    cur = conn.execute(
        '''INSERT INTO apps
             (name, icon, description, category, version, html,
              has_backend, backend_code, developer_id,
              status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)''',
        (name,
         (data.get('icon') or '📦').strip(),
         (data.get('description') or '').strip(),
         (data.get('category') or '工具').strip(),
         (data.get('version') or '1.0.0').strip(),
         html,
         has_backend,
         backend_code,
         request.user['id'],
         now_iso(), now_iso())
    )
    app_id = cur.lastrowid
    conn.commit()
    conn.close()

    # 若含后端，落盘
    if has_backend and backend_code:
        _write_app_backend(app_id, backend_code)

    return jsonify({'id': app_id, 'message': '投稿成功，等待审核'})


@app.route('/api/apps/<int:app_id>', methods=['PUT'])
@require_auth
def api_app_update(app_id):
    data = request.get_json(silent=True) or {}

    conn = get_db()
    row = conn.execute('SELECT * FROM apps WHERE id=?', (app_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': '应用不存在'}), 404
    if row['developer_id'] != request.user['id']:
        conn.close()
        return jsonify({'error': '无权修改他人应用'}), 403

    name = (data.get('name') or row['name']).strip()
    html = data.get('html', row['html'])
    has_backend = 1 if data.get('has_backend', row['has_backend']) else 0
    backend_code = data.get('backend_code', row['backend_code'] or '')

    conn.execute(
        '''UPDATE apps SET
             name=?, icon=?, description=?, category=?, version=?,
             html=?, has_backend=?, backend_code=?,
             status='pending', reject_reason=NULL, updated_at=?
           WHERE id=?''',
        (name,
         (data.get('icon') or row['icon'] or '📦').strip(),
         (data.get('description') or row['description'] or '').strip(),
         (data.get('category') or row['category'] or '工具').strip(),
         (data.get('version') or row['version'] or '1.0.0').strip(),
         html, has_backend, backend_code,
         now_iso(), app_id)
    )
    conn.commit()
    conn.close()

    # 更新落盘
    if has_backend:
        _write_app_backend(app_id, backend_code)
    else:
        _remove_app_backend(app_id)
    _BACKEND_CACHE.pop(app_id, None)

    return jsonify({'message': '已更新，等待重新审核'})


@app.route('/api/apps/<int:app_id>/install', methods=['POST'])
@require_auth
def api_app_install(app_id):
    conn = get_db()
    a = conn.execute(
        "SELECT * FROM apps WHERE id=? AND status='published'", (app_id,)
    ).fetchone()
    if not a:
        conn.close()
        return jsonify({'error': '应用不存在或未上架'}), 404

    existing = conn.execute(
        'SELECT id FROM installs WHERE user_id=? AND app_id=?',
        (request.user['id'], app_id)
    ).fetchone()

    if existing:
        conn.execute(
            'UPDATE installs SET version=?, created_at=? WHERE id=?',
            (a['version'], now_iso(), existing['id'])
        )
    else:
        conn.execute(
            'INSERT INTO installs (user_id, app_id, version, created_at) VALUES (?, ?, ?, ?)',
            (request.user['id'], app_id, a['version'], now_iso())
        )
        conn.execute('UPDATE apps SET downloads=downloads+1 WHERE id=?', (app_id,))

    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/myapps', methods=['GET'])
@require_auth
def api_my_installs():
    conn = get_db()
    rows = conn.execute(
        'SELECT app_id, version, created_at FROM installs WHERE user_id=?',
        (request.user['id'],)
    ).fetchall()
    conn.close()
    return jsonify({'apps': [dict(r) for r in rows]})


# ================================================================
#  应用存储桥接
# ================================================================
@app.route('/api/appstore/<int:app_id>/storage/get', methods=['POST'])
@require_auth
def api_appstore_storage_get(app_id):
    data = request.get_json(silent=True) or {}
    key = data.get('key')
    if not key:
        return jsonify({'value': None})
    conn = get_db()
    row = conn.execute(
        'SELECT value FROM app_storage WHERE app_id=? AND user_id=? AND key=?',
        (app_id, request.user['id'], key)
    ).fetchone()
    conn.close()
    if not row:
        return jsonify({'value': None})
    try:
        return jsonify({'value': json.loads(row['value'])})
    except Exception:
        return jsonify({'value': row['value']})


@app.route('/api/appstore/<int:app_id>/storage/set', methods=['POST'])
@require_auth
def api_appstore_storage_set(app_id):
    data = request.get_json(silent=True) or {}
    key = data.get('key')
    if not key:
        return jsonify({'error': '缺少 key'}), 400
    try:
        val = json.dumps(data.get('value'), ensure_ascii=False)
    except Exception:
        val = str(data.get('value'))

    conn = get_db()
    conn.execute(
        '''INSERT INTO app_storage (app_id, user_id, key, value)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(app_id, user_id, key) DO UPDATE SET value=excluded.value''',
        (app_id, request.user['id'], key, val)
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ================================================================
#  MJ 货币：充值 / 转账 / 消费
# ================================================================
@app.route('/api/pay/recharge', methods=['POST'])
@require_auth
def api_pay_recharge():
    data = request.get_json(silent=True) or {}
    try:
        amount = float(data.get('amount') or 0)
    except Exception:
        return jsonify({'error': '金额无效'}), 400

    if amount <= 0:
        return jsonify({'error': '金额必须大于 0'}), 400
    if amount > 10000:
        return jsonify({'error': '单次充值不能超过 10000 MJ'}), 400

    # 防刷：每分钟最多 1 次
    conn = get_db()
    one_min_ago = (datetime.now() - timedelta(minutes=1)).isoformat()
    recent = conn.execute(
        '''SELECT COUNT(*) AS n FROM transactions
           WHERE user_id=? AND type='recharge' AND created_at > ?''',
        (request.user['id'], one_min_ago)
    ).fetchone()['n']

    if recent >= 1:
        conn.close()
        return jsonify({'error': '充值过于频繁，请稍后再试'}), 429

    # 每日上限（防止刷 MJ）
    day_ago = (datetime.now() - timedelta(days=1)).isoformat()
    day_total = conn.execute(
        '''SELECT COALESCE(SUM(amount), 0) AS s FROM transactions
           WHERE user_id=? AND type='recharge' AND created_at > ?''',
        (request.user['id'], day_ago)
    ).fetchone()['s']
    if day_total + amount > 50000:
        conn.close()
        return jsonify({'error': '今日充值已达上限（50000 MJ）'}), 429

    conn.execute('UPDATE users SET balance = balance + ? WHERE id=?',
                 (amount, request.user['id']))
    conn.execute(
        '''INSERT INTO transactions (user_id, amount, type, note, created_at)
           VALUES (?, ?, 'recharge', '自助充值', ?)''',
        (request.user['id'], amount, now_iso())
    )
    conn.commit()
    new_bal = conn.execute(
        'SELECT balance FROM users WHERE id=?', (request.user['id'],)
    ).fetchone()['balance']
    conn.close()

    return jsonify({'success': True, 'balance': float(new_bal)})


@app.route('/api/pay/transfer', methods=['POST'])
@require_auth
def api_pay_transfer():
    data = request.get_json(silent=True) or {}
    to_name = (data.get('to') or '').strip()
    try:
        amount = float(data.get('amount') or 0)
    except Exception:
        return jsonify({'error': '金额无效'}), 400
    note = (data.get('note') or '').strip() or '转账'

    if not to_name:
        return jsonify({'error': '缺少收款人'}), 400
    if amount <= 0:
        return jsonify({'error': '金额必须大于 0'}), 400
    if to_name == request.user['username']:
        return jsonify({'error': '不能给自己转账'}), 400

    conn = get_db()
    target = conn.execute('SELECT * FROM users WHERE username=?', (to_name,)).fetchone()
    if not target:
        conn.close()
        return jsonify({'error': '收款人不存在'}), 404
    if target['banned']:
        conn.close()
        return jsonify({'error': '收款人已被封禁'}), 403

    bal = float(request.user['balance'] or 0)
    if bal < amount:
        conn.close()
        return jsonify({'error': '余额不足'}), 400

    conn.execute('UPDATE users SET balance = balance - ? WHERE id=?',
                 (amount, request.user['id']))
    conn.execute('UPDATE users SET balance = balance + ? WHERE id=?',
                 (amount, target['id']))
    conn.execute(
        '''INSERT INTO transactions
             (user_id, amount, type, note, related_user, created_at)
           VALUES (?, ?, 'transfer_out', ?, ?, ?)''',
        (request.user['id'], -amount, '转给 ' + to_name + '：' + note,
         target['id'], now_iso())
    )
    conn.execute(
        '''INSERT INTO transactions
             (user_id, amount, type, note, related_user, created_at)
           VALUES (?, ?, 'transfer_in', ?, ?, ?)''',
        (target['id'], amount,
         '来自 ' + request.user['username'] + '：' + note,
         request.user['id'], now_iso())
    )
    conn.commit()
    new_bal = conn.execute(
        'SELECT balance FROM users WHERE id=?', (request.user['id'],)
    ).fetchone()['balance']
    conn.close()

    return jsonify({'success': True, 'balance': float(new_bal)})


@app.route('/api/pay/pay', methods=['POST'])
@require_auth
def api_pay_pay():
    data = request.get_json(silent=True) or {}
    try:
        amount = float(data.get('amount') or 0)
    except Exception:
        return jsonify({'error': '金额无效'}), 400
    reason = (data.get('reason') or '应用内支付').strip()[:100]
    app_id = data.get('app_id')

    if amount <= 0:
        return jsonify({'error': '金额必须大于 0'}), 400

    conn = get_db()
    bal = float(request.user['balance'] or 0)
    if bal < amount:
        conn.close()
        return jsonify({'error': '余额不足'}), 400

    conn.execute('UPDATE users SET balance = balance - ? WHERE id=?',
                 (amount, request.user['id']))
    conn.execute(
        '''INSERT INTO transactions
             (user_id, amount, type, note, created_at)
           VALUES (?, ?, 'consume', ?, ?)''',
        (request.user['id'], -amount,
         '应用 #' + str(app_id) + '：' + reason, now_iso())
    )
    conn.commit()
    new_bal = conn.execute(
        'SELECT balance FROM users WHERE id=?', (request.user['id'],)
    ).fetchone()['balance']
    conn.close()

    return jsonify({'success': True, 'balance': float(new_bal)})


@app.route('/api/pay/logs', methods=['GET'])
@require_auth
def api_pay_logs():
    conn = get_db()
    rows = conn.execute(
        '''SELECT * FROM transactions
           WHERE user_id=?
           ORDER BY id DESC LIMIT 50''',
        (request.user['id'],)
    ).fetchall()
    conn.close()
    return jsonify({'logs': [dict(r) for r in rows]})


# ================================================================
#  聊天
# ================================================================
@app.route('/api/chat/contacts', methods=['GET'])
@require_auth
def api_chat_contacts():
    conn = get_db()
    rows = conn.execute(
        '''SELECT id, username, nickname,
             (SELECT COUNT(*) FROM messages m
              WHERE m.sender_id = u.id
                AND m.receiver_id = ?
                AND m.read = 0) AS unread
           FROM users u
           WHERE u.id != ? AND u.banned = 0
           ORDER BY u.id DESC LIMIT 100''',
        (request.user['id'], request.user['id'])
    ).fetchall()
    conn.close()
    return jsonify({'contacts': [dict(r) for r in rows]})


@app.route('/api/chat/messages/<int:peer_id>', methods=['GET'])
@require_auth
def api_chat_messages(peer_id):
    conn = get_db()
    # 拉取并标记已读
    conn.execute(
        '''UPDATE messages SET read=1
           WHERE sender_id=? AND receiver_id=? AND read=0''',
        (peer_id, request.user['id'])
    )
    rows = conn.execute(
        '''SELECT * FROM messages
           WHERE (sender_id=? AND receiver_id=?)
              OR (sender_id=? AND receiver_id=?)
           ORDER BY id ASC LIMIT 200''',
        (request.user['id'], peer_id, peer_id, request.user['id'])
    ).fetchall()
    conn.commit()
    conn.close()
    return jsonify({'messages': [dict(r) for r in rows]})


@app.route('/api/chat/send', methods=['POST'])
@require_auth
def api_chat_send():
    data = request.get_json(silent=True) or {}
    to = data.get('to')
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'error': '消息不能为空'}), 400
    if len(content) > 2000:
        return jsonify({'error': '消息过长'}), 400

    conn = get_db()
    target = conn.execute('SELECT id, banned FROM users WHERE id=?', (to,)).fetchone()
    if not target:
        conn.close()
        return jsonify({'error': '对方不存在'}), 404
    if target['banned']:
        conn.close()
        return jsonify({'error': '对方已被封禁'}), 403

    conn.execute(
        'INSERT INTO messages (sender_id, receiver_id, content, created_at) VALUES (?, ?, ?, ?)',
        (request.user['id'], target['id'], content, now_iso())
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ================================================================
#  调试接口（前台）
# ================================================================
@app.route('/api/debug/status', methods=['GET'])
@require_auth
def api_debug_status():
    conn = get_db()
    users = conn.execute('SELECT COUNT(*) AS n FROM users').fetchone()['n']
    apps  = conn.execute("SELECT COUNT(*) AS n FROM apps WHERE status='published'").fetchone()['n']
    db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    conn.close()
    return jsonify({
        'users':       users,
        'apps':        apps,
        'db_size':     db_size,
        'server_time': now_iso(),
        'ok':          True,
    })


# ================================================================
#  应用运行：HTML + Python 后端
# ================================================================
def _app_dir(app_id):
    return os.path.join(APPS_DIR, str(app_id))


def _write_app_backend(app_id, code):
    d = _app_dir(app_id)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'backend.py'), 'w', encoding='utf-8') as f:
        f.write(code or '')
    _BACKEND_CACHE.pop(app_id, None)


def _remove_app_backend(app_id):
    d = _app_dir(app_id)
    fp = os.path.join(d, 'backend.py')
    if os.path.exists(fp):
        try:
            os.remove(fp)
        except Exception:
            pass
    _BACKEND_CACHE.pop(app_id, None)


def _load_app_backend(app_id):
    if app_id in _BACKEND_CACHE:
        return _BACKEND_CACHE[app_id]
    fp = os.path.join(_app_dir(app_id), 'backend.py')
    if not os.path.exists(fp):
        return None
    try:
        spec = importlib.util.spec_from_file_location(
            'mhjc_app_%d' % app_id, fp
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _BACKEND_CACHE[app_id] = mod
        return mod
    except Exception as e:
        print('[app %s] 加载后端失败: %s' % (app_id, e))
        traceback.print_exc()
        return None


@app.route('/app/<int:app_id>', methods=['GET'])
def serve_app_html(app_id):
    """返回注入桥接脚本的应用 HTML"""
    conn = get_db()
    a = conn.execute(
        "SELECT * FROM apps WHERE id=? AND status='published'", (app_id,)
    ).fetchone()
    conn.close()
    if not a:
        return Response('应用不存在或未上架', status=404, mimetype='text/plain; charset=utf-8')

    bridge = _build_bridge(app_id)

    html = a['html'] or '<!DOCTYPE html><html><body><h1>无内容</h1></body></html>'
    low = html.lower()
    if '</body>' in low:
        idx = low.rfind('</body>')
        html = html[:idx] + bridge + html[idx:]
    else:
        html += bridge

    return Response(html, mimetype='text/html; charset=utf-8')


def _build_bridge(app_id):
    return """
<script>
(function(){
  const APP_ID = %d;
  let rid = 0;
  const callbacks = {};

  window.addEventListener('message', function(e){
    const d = e.data;
    if (d && d.__mhjc_res && callbacks[d.rid]){
      const cb = callbacks[d.rid];
      delete callbacks[d.rid];
      if (d.error) cb.reject(new Error(d.error));
      else cb.resolve(d.result);
    }
  });

  function call(method){
    const args = Array.prototype.slice.call(arguments, 1);
    return new Promise(function(resolve, reject){
      const id = ++rid;
      callbacks[id] = { resolve, reject };
      window.parent.postMessage(
        { __mhjc: true, rid: id, method: method, args: args }, '*'
      );
    });
  }

  function apiFetch(path, opts){
    const token = new URLSearchParams(location.search).get('token') || '';
    const url = '/app/' + APP_ID + '/api' + path;
    const headers = Object.assign(
      { 'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + token },
      (opts && opts.headers) || {}
    );
    return fetch(url, Object.assign({}, opts || {}, { headers: headers }));
  }

  window.mhjc = {
    getUser: function(){ return call('getUser'); },
    storage: {
      get: function(k){ return call('storage.get', k); },
      set: function(k, v){ return call('storage.set', k, v); }
    },
    pay: {
      request: function(amount, reason){
        return call('pay.request', amount, reason);
      }
    },
    fetch: apiFetch,
    notify: function(msg){ return call('notify', msg); },
    close: function(){ return call('close'); }
  };

  // 触达一次，说明 bridge 已就绪
  window.parent.postMessage({ __mhjc_ready: true, appId: APP_ID }, '*');
})();
</script>
""" % app_id


@app.route('/app/<int:app_id>/api/<path:subpath>',
           methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
def serve_app_backend(app_id, subpath):
    """调用用户应用的后端"""
    # 应用需上架
    conn = get_db()
    a = conn.execute(
        "SELECT * FROM apps WHERE id=? AND status='published'", (app_id,)
    ).fetchone()
    conn.close()
    if not a or not a['has_backend']:
        return jsonify({'error': '应用不存在或未提供后端'}), 404

    # 认证
    user = get_user_by_token(bearer_token())
    if not user:
        return jsonify({'error': '未登录'}), 401

    mod = _load_app_backend(app_id)
    if not mod:
        return jsonify({'error': '后端加载失败'}), 500

    handler = getattr(mod, 'handle', None)
    if not callable(handler):
        return jsonify({'error': '后端缺少 handle 函数'}), 500

    try:
        result = handler(
            method=request.method,
            path=subpath,
            data=request.get_json(silent=True) or {},
            args=dict(request.args),
            user=user_public(user),
            app_id=app_id,
            headers={k: v for k, v in request.headers.items()},
        )
        if isinstance(result, tuple) and len(result) == 2:
            body, status = result
            if isinstance(body, (dict, list)):
                return jsonify(body), status
            return Response(str(body), status=status)
        if isinstance(result, (dict, list)):
            return jsonify(result)
        return jsonify({'result': result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': '后端执行错误: ' + str(e)}), 500


# ================================================================
#  管理后台 API
# ================================================================
admin_bp = Blueprint('admin_api', __name__, url_prefix='/api/admin')


@admin_bp.route('/login', methods=['POST'])
def admin_login():
    data = request.get_json(silent=True) or {}
    pwd  = data.get('password') or ''
    if not pwd:
        return jsonify({'error': '请输入密码'}), 400

    conn = get_db()
    a = conn.execute('SELECT * FROM admin ORDER BY id LIMIT 1').fetchone()
    if not a or not check_password_hash(a['password_hash'], pwd):
        conn.close()
        return jsonify({'error': '密码错误'}), 400

    token   = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(days=7)).isoformat()
    conn.execute(
        'UPDATE admin SET token=?, token_expires=? WHERE id=?',
        (token, expires, a['id'])
    )
    conn.commit()
    conn.close()
    return jsonify({'token': token})


@admin_bp.route('/logout', methods=['POST'])
def admin_logout():
    token = bearer_token()
    if token:
        conn = get_db()
        conn.execute('UPDATE admin SET token=NULL WHERE token=?', (token,))
        conn.commit()
        conn.close()
    return jsonify({'success': True})


@admin_bp.route('/password', methods=['POST'])
@require_admin
def admin_change_password():
    data = request.get_json(silent=True) or {}
    old, new = data.get('old') or '', data.get('new') or ''
    if not old or not new:
        return jsonify({'error': '请填写完整'}), 400

    conn = get_db()
    a = conn.execute('SELECT * FROM admin WHERE id=?', (request.admin['id'],)).fetchone()
    if not check_password_hash(a['password_hash'], old):
        conn.close()
        return jsonify({'error': '当前密码错误'}), 400

    conn.execute(
        'UPDATE admin SET password_hash=?, token=NULL WHERE id=?',
        (generate_password_hash(new), request.admin['id'])
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@admin_bp.route('/stats', methods=['GET'])
@require_admin
def admin_stats():
    conn = get_db()
    users = conn.execute('SELECT COUNT(*) AS n FROM users').fetchone()['n']
    apps  = conn.execute("SELECT COUNT(*) AS n FROM apps WHERE status='published'").fetchone()['n']
    pend  = conn.execute("SELECT COUNT(*) AS n FROM apps WHERE status='pending'").fetchone()['n']
    total = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS s FROM transactions WHERE type='recharge'"
    ).fetchone()['s']
    conn.close()

    size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    if size > 1024 * 1024:
        size_str = '%.2f MB' % (size / 1024 / 1024)
    elif size > 1024:
        size_str = '%.2f KB' % (size / 1024)
    else:
        size_str = str(size) + ' B'

    return jsonify({
        'users':        users,
        'apps':         apps,
        'pending_apps': pend,
        'total_recharge': float(total or 0),
        'db_size':      size_str,
        'server_time':  now_iso(),
        'uptime':       '运行中',
    })


@admin_bp.route('/users', methods=['GET'])
@require_admin
def admin_users():
    page  = max(1, int(request.args.get('page', 1)))
    limit = min(100, max(1, int(request.args.get('limit', 20))))
    q     = (request.args.get('q') or '').strip()

    conn = get_db()
    where, params = '1=1', []
    if q:
        where += ' AND (username LIKE ? OR nickname LIKE ? OR device_fingerprint LIKE ?)'
        like = '%' + q + '%'
        params = [like, like, like]

    total = conn.execute('SELECT COUNT(*) AS n FROM users WHERE ' + where, params).fetchone()['n']
    rows  = conn.execute(
        'SELECT * FROM users WHERE ' + where + ' ORDER BY id DESC LIMIT ? OFFSET ?',
        params + [limit, (page - 1) * limit]
    ).fetchall()
    conn.close()

    return jsonify({
        'total': total,
        'page':  page,
        'users': [{
            'id':                 r['id'],
            'username':           r['username'],
            'nickname':           r['nickname'],
            'balance':            float(r['balance'] or 0),
            'device_fingerprint': r['device_fingerprint'],
            'banned':             r['banned'],
            'created_at':         r['created_at'],
        } for r in rows]
    })


@admin_bp.route('/users/<int:uid>/ban', methods=['POST'])
@require_admin
def admin_user_ban(uid):
    data   = request.get_json(silent=True) or {}
    banned = 1 if data.get('banned') else 0

    conn = get_db()
    conn.execute(
        'UPDATE users SET banned=?, token=NULL WHERE id=?',
        (banned, uid)
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@admin_bp.route('/users/<int:uid>/balance', methods=['POST'])
@require_admin
def admin_user_balance(uid):
    data   = request.get_json(silent=True) or {}
    mode   = data.get('mode', 'delta')
    try:
        amount = float(data.get('amount') or 0)
    except Exception:
        return jsonify({'error': '金额无效'}), 400
    note = (data.get('note') or '管理员调整').strip()[:80]

    conn = get_db()
    u = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    if not u:
        conn.close()
        return jsonify({'error': '用户不存在'}), 404

    if mode == 'set':
        new_bal = amount
        delta = new_bal - float(u['balance'] or 0)
    else:
        delta = amount
        new_bal = float(u['balance'] or 0) + delta

    if new_bal < 0:
        conn.close()
        return jsonify({'error': '余额不能为负数'}), 400

    conn.execute('UPDATE users SET balance=? WHERE id=?', (new_bal, uid))
    conn.execute(
        '''INSERT INTO transactions
             (user_id, amount, type, note, created_at)
           VALUES (?, ?, 'admin', ?, ?)''',
        (uid, delta, note, now_iso())
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'balance': new_bal})


@admin_bp.route('/users/<int:uid>/password', methods=['POST'])
@require_admin
def admin_user_password(uid):
    data = request.get_json(silent=True) or {}
    pwd  = data.get('password') or ''
    if not pwd:
        return jsonify({'error': '密码不能为空'}), 400

    conn = get_db()
    conn.execute(
        'UPDATE users SET password_hash=?, token=NULL WHERE id=?',
        (generate_password_hash(pwd), uid)
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@admin_bp.route('/users/<int:uid>/kick', methods=['POST'])
@require_admin
def admin_user_kick(uid):
    conn = get_db()
    conn.execute('UPDATE users SET token=NULL WHERE id=?', (uid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@admin_bp.route('/apps', methods=['GET'])
@require_admin
def admin_apps_list():
    status = request.args.get('status', 'all')
    q      = (request.args.get('q') or '').strip()

    conn = get_db()
    where, params = '1=1', []
    if status != 'all':
        where += ' AND a.status=?'
        params.append(status)
    if q:
        where += ' AND (a.name LIKE ? OR u.username LIKE ?)'
        like = '%' + q + '%'
        params += [like, like]

    rows = conn.execute(
        '''SELECT a.*, u.username AS developer_name
           FROM apps a
           LEFT JOIN users u ON u.id = a.developer_id
           WHERE ''' + where + '''
           ORDER BY
             CASE a.status WHEN 'pending' THEN 0
                           WHEN 'published' THEN 1
                           ELSE 2 END,
             a.updated_at DESC
           LIMIT 300''',
        params
    ).fetchall()
    conn.close()
    return jsonify({'apps': [dict(r) for r in rows]})


@admin_bp.route('/apps', methods=['DELETE'])
@require_admin
def admin_apps_bulk_delete():
    """删除所有已拒绝的应用"""
    status = request.args.get('status')
    if status != 'rejected':
        return jsonify({'error': '不支持批量删除此状态'}), 400

    conn = get_db()
    rows = conn.execute("SELECT id FROM apps WHERE status='rejected'").fetchall()
    ids = [r['id'] for r in rows]
    conn.execute("DELETE FROM apps WHERE status='rejected'")
    conn.execute("DELETE FROM installs WHERE app_id IN (" +
                 ",".join("?" * len(ids)) + ")", ids) if ids else None
    conn.commit()
    conn.close()

    for i in ids:
        _remove_app_backend(i)

    return jsonify({'success': True, 'deleted': len(ids)})


@admin_bp.route('/apps/<int:app_id>/approve', methods=['POST'])
@require_admin
def admin_app_approve(app_id):
    conn = get_db()
    a = conn.execute('SELECT * FROM apps WHERE id=?', (app_id,)).fetchone()
    if not a:
        conn.close()
        return jsonify({'error': '应用不存在'}), 404

    conn.execute(
        "UPDATE apps SET status='published', reject_reason=NULL, updated_at=? WHERE id=?",
        (now_iso(), app_id)
    )
    conn.commit()
    conn.close()

    if a['has_backend'] and a['backend_code']:
        _write_app_backend(app_id, a['backend_code'])

    return jsonify({'success': True})


@admin_bp.route('/apps/<int:app_id>/reject', methods=['POST'])
@require_admin
def admin_app_reject(app_id):
    data   = request.get_json(silent=True) or {}
    reason = (data.get('reason') or '不符合规范').strip()[:200]

    conn = get_db()
    a = conn.execute('SELECT * FROM apps WHERE id=?', (app_id,)).fetchone()
    if not a:
        conn.close()
        return jsonify({'error': '应用不存在'}), 404

    conn.execute(
        "UPDATE apps SET status='rejected', reject_reason=?, updated_at=? WHERE id=?",
        (reason, now_iso(), app_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@admin_bp.route('/apps/<int:app_id>', methods=['PUT'])
@require_admin
def admin_app_update(app_id):
    data = request.get_json(silent=True) or {}
    conn = get_db()
    a = conn.execute('SELECT * FROM apps WHERE id=?', (app_id,)).fetchone()
    if not a:
        conn.close()
        return jsonify({'error': '应用不存在'}), 404

    conn.execute(
        '''UPDATE apps SET
             name=?, icon=?, description=?, category=?, version=?,
             html=?, backend_code=?,
             status='pending', updated_at=?
           WHERE id=?''',
        (data.get('name', a['name']),
         data.get('icon', a['icon']),
         data.get('description', a['description']),
         data.get('category', a['category']),
         data.get('version', a['version']),
         data.get('html', a['html']),
         data.get('backend_code', a['backend_code']),
         now_iso(), app_id)
    )
    conn.commit()
    conn.close()

    if a['has_backend'] and data.get('backend_code') is not None:
        _write_app_backend(app_id, data['backend_code'])

    return jsonify({'success': True})


@admin_bp.route('/apps/<int:app_id>', methods=['DELETE'])
@require_admin
def admin_app_delete(app_id):
    conn = get_db()
    a = conn.execute('SELECT * FROM apps WHERE id=?', (app_id,)).fetchone()
    if not a:
        conn.close()
        return jsonify({'error': '应用不存在'}), 404

    conn.execute('DELETE FROM apps WHERE id=?', (app_id,))
    conn.execute('DELETE FROM installs WHERE app_id=?', (app_id,))
    conn.execute('DELETE FROM app_storage WHERE app_id=?', (app_id,))
    conn.commit()
    conn.close()

    _remove_app_backend(app_id)
    return jsonify({'success': True})


@admin_bp.route('/recharge-logs', methods=['GET'])
@require_admin
def admin_recharge_logs():
    page  = max(1, int(request.args.get('page', 1)))
    limit = min(100, max(1, int(request.args.get('limit', 25))))

    conn = get_db()
    total = conn.execute('SELECT COUNT(*) AS n FROM transactions').fetchone()['n']
    rows = conn.execute(
        '''SELECT t.*, u.username, u.nickname
           FROM transactions t
           LEFT JOIN users u ON u.id = t.user_id
           ORDER BY t.id DESC LIMIT ? OFFSET ?''',
        (limit, (page - 1) * limit)
    ).fetchall()
    conn.close()

    return jsonify({
        'total': total,
        'page':  page,
        'logs':  [dict(r) for r in rows]
    })


@admin_bp.route('/recharge-logs', methods=['DELETE'])
@require_admin
def admin_clear_recharge_logs():
    conn = get_db()
    conn.execute('DELETE FROM transactions')
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@admin_bp.route('/settings', methods=['GET'])
@require_admin
def admin_get_settings():
    conn = get_db()
    rows = conn.execute('SELECT * FROM settings').fetchall()
    conn.close()
    d = {r['key']: r['value'] for r in rows}

    return jsonify({
        'wallpaper':              d.get('wallpaper', 'default'),
        'welcome_mj':             float(d.get('welcome_mj', '0') or 0),
        'prompt_template':        d.get('prompt_template', DEFAULT_PROMPT_TEMPLATE),
        'default_prompt_template': DEFAULT_PROMPT_TEMPLATE,
    })


@admin_bp.route('/settings', methods=['POST'])
@require_admin
def admin_set_settings():
    data = request.get_json(silent=True) or {}
    for k in ('wallpaper', 'welcome_mj', 'prompt_template'):
        if k in data:
            set_setting(k, data[k])
    return jsonify({'success': True})


@admin_bp.route('/debug/database', methods=['GET'])
@require_admin
def admin_debug_database():
    conn = get_db()
    tables = ['users', 'apps', 'installs', 'messages',
              'transactions', 'app_storage', 'settings', 'admin']
    info = {}
    for t in tables:
        try:
            n = conn.execute('SELECT COUNT(*) AS n FROM ' + t).fetchone()['n']
            info[t] = n
        except Exception as e:
            info[t] = 'error: ' + str(e)
    size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    conn.close()
    return jsonify({
        'path':   DB_PATH,
        'size':   size,
        'tables': info,
    })


@admin_bp.route('/debug/environment', methods=['GET'])
@require_admin
def admin_debug_environment():
    return jsonify({
        'python':      sys.version,
        'platform':    sys.platform,
        'flask':       __import__('flask').__version__,
        'cors':        'enabled' if CORS else 'disabled',
        'base_dir':    BASE_DIR,
        'apps_dir':    APPS_DIR,
        'static_dir':  STATIC_DIR,
        'server_time': now_iso(),
    })


app.register_blueprint(admin_bp)


# ================================================================
#  静态文件服务
# ================================================================
@app.route('/', methods=['GET'])
def index_page():
    fp = os.path.join(STATIC_DIR, 'index.html')
    if not os.path.exists(fp):
        return Response(
            '未找到 static/index.html<br>'
            '请将前台 HTML 文件放入 static 目录',
            mimetype='text/html; charset=utf-8',
            status=404
        )
    return send_from_directory(STATIC_DIR, 'index.html')


@app.route('/admin', methods=['GET'])
def admin_page():
    fp = os.path.join(STATIC_DIR, 'admin.html')
    if not os.path.exists(fp):
        return Response(
            '未找到 static/admin.html<br>'
            '请将后台 HTML 文件放入 static 目录',
            mimetype='text/html; charset=utf-8',
            status=404
        )
    return send_from_directory(STATIC_DIR, 'admin.html')


@app.route('/static/<path:filename>', methods=['GET'])
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)


@app.route('/favicon.ico')
def favicon():
    fp = os.path.join(STATIC_DIR, 'favicon.ico')
    if os.path.exists(fp):
        return send_from_directory(STATIC_DIR, 'favicon.ico')
    return Response(status=204)


# ================================================================
#  错误处理
# ================================================================
@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': '接口不存在'}), 404
    return jsonify({'error': 'not found', 'path': request.path}), 404


@app.errorhandler(500)
def server_error(e):
    traceback.print_exc()
    return jsonify({'error': '服务器内部错误'}), 500


# ================================================================
#  启动
# ================================================================
if __name__ == '__main__':
    print('=' * 60)
    print(' mhjc 服务器 启动中…')
    print('=' * 60)
    print(' 数据目录  :', DATA_DIR)
    print(' 应用目录  :', APPS_DIR)
    print(' 静态目录  :', STATIC_DIR)
    print(' 数据库    :', DB_PATH)
    print()

    init_db()

    # 确保 static 目录中有必需的 HTML 文件
    if not os.path.exists(os.path.join(STATIC_DIR, 'index.html')):
        print('⚠️  未找到 static/index.html')
    if not os.path.exists(os.path.join(STATIC_DIR, 'admin.html')):
        print('⚠️  未找到 static/admin.html')
    print()

    host = os.environ.get('MHJC_HOST', '0.0.0.0')
    port = int(os.environ.get('MHJC_PORT', 5000))
    debug = os.environ.get('MHJC_DEBUG', '0') == '1'

    print(' 前台    : http://127.0.0.1:%d/' % port)
    print(' 后台    : http://127.0.0.1:%d/admin' % port)
    print(' 默认管理密码: 1')
    print('=' * 60)
    print()

    app.run(host=host, port=port, debug=debug, threaded=True)
