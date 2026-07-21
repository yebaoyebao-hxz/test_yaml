# -*- coding: utf-8 -*-
"""静态路由: /, /health, /report/<path>, /views/<path>, /common/<path>"""
import os
from flask import Blueprint, jsonify, send_from_directory, make_response

from web_server.config import REPORT_DIR

static_bp = Blueprint("static", __name__)

# Project root: same logic as main.py
# Use cwd as fallback if __file__ is not absolute
try:
    _PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.exists(os.path.join(_PROJECT_ROOT, "html")):
        _PROJECT_ROOT = os.getcwd()
except Exception:
    _PROJECT_ROOT = os.getcwd()
_HTML_DIR = os.path.join(_PROJECT_ROOT, "html")


@static_bp.route("/")
def index():
    return _serve_raw('index.html')


@static_bp.route("/legacy")
def legacy():
    """旧版页面回退入口"""
    resp = make_response(_serve_raw('index_legacy.html'))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp


def _serve_raw(path):
    """直接读取 HTML 文件（绕过 Jinja2，避免 Vue {{ }} 冲突）"""
    full = os.path.join(_HTML_DIR, path)
    if not os.path.exists(full):
        return jsonify({"error": "Not found"}), 404
    with open(full, "r", encoding="utf-8") as f:
        content = f.read()
    resp = make_response(content)
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    resp.headers['Content-Type'] = 'text/html; charset=utf-8'
    return resp


@static_bp.route("/health")
def health():
    return jsonify({"status": "ok", "service": "yaml-case-generator"})


@static_bp.route("/report/<path:filename>")
def serve_report(filename):
    return send_from_directory(str(REPORT_DIR), filename)


@static_bp.route("/data/screen/<path:filename>")
def serve_screen(filename):
    """Serve device screenshots as device thumbnails."""
    screen_dir = os.path.join(_PROJECT_ROOT, "data", "screen")
    if not os.path.exists(screen_dir):
        return jsonify({"error": "screen dir not found"}), 404
    return send_from_directory(screen_dir, filename)


@static_bp.route("/common/<path:filename>")
def serve_common(filename):
    """Serve common HTML/CSS fragments."""
    full_path = os.path.join(_HTML_DIR, "common", filename)
    if not os.path.exists(full_path):
        return jsonify({"error": f"Not found: {filename}"}), 404
    with open(full_path, "r", encoding="utf-8") as f:
        content = f.read()
    resp = make_response(content)
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Content-Type'] = _guess_content_type(filename)
    return resp


@static_bp.route("/vue-app/<path:filename>")
def serve_vue_app(filename):
    """Serve Vue SPA static assets (CSS / JS)."""
    full_path = os.path.join(_HTML_DIR, "vue-app", filename)
    if not os.path.exists(full_path):
        return jsonify({"error": f"Not found: {filename}"}), 404
    with open(full_path, "r", encoding="utf-8") as f:
        content = f.read()
    resp = make_response(content)
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Content-Type'] = _guess_content_type(filename)
    return resp


@static_bp.route("/views/<path:filename>")
def serve_views(filename):
    """Serve view HTML/CSS fragments (e.g. views/generate/generate.html)."""
    full_path = os.path.join(_HTML_DIR, "views", filename)
    if not os.path.exists(full_path):
        return jsonify({"error": f"Not found: {filename}"}), 404
    with open(full_path, "r", encoding="utf-8") as f:
        content = f.read()
    resp = make_response(content)
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Content-Type'] = _guess_content_type(filename)
    return resp


def _guess_content_type(filename):
    if filename.endswith(".css"):
        return "text/css; charset=utf-8"
    elif filename.endswith(".js"):
        return "application/javascript; charset=utf-8"
    elif filename.endswith(".html"):
        return "text/html; charset=utf-8"
    return "text/plain; charset=utf-8"
