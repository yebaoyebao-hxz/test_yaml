# -*- coding: utf-8 -*-
"""静态路由: /, /health, /report/<path>"""
from flask import Blueprint, render_template, jsonify, send_from_directory

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
