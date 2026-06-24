# -*- coding: utf-8 -*-
"""静态路由: /, /health, /report/<path>"""
from flask import Blueprint, render_template, jsonify, send_from_directory, current_app
import os
from web_server.config import REPORT_DIR


static_bp = Blueprint("static", __name__)


@static_bp.route("/")
def index():
    return render_template('index.html')


@static_bp.route("/health")
def health():
    return jsonify({"status": "ok", "service": "yaml-case-generator"})


@static_bp.route("/report/<path:filename>")
def serve_report(filename):
    return send_from_directory(str(REPORT_DIR), filename)

@static_bp.route('/<path:filename>')
def serve_static(filename):
    """通用静态文件访问：匹配 /css/*、/components/*、/views/* 等路径"""
    # 指向项目根目录下的 html 文件夹
    html_dir = os.path.join(current_app.root_path, "../../html")
    html_dir = os.path.abspath(html_dir)
    return send_from_directory(html_dir, filename)


