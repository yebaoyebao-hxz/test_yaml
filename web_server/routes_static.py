# -*- coding: utf-8 -*-
"""静态路由: /, /health, /report/<path>"""
from flask import Blueprint, render_template, jsonify, send_from_directory, make_response

from web_server.config import REPORT_DIR

static_bp = Blueprint("static", __name__)


@static_bp.route("/")
def index():
    resp = make_response(render_template('index.html'))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp


@static_bp.route("/health")
def health():
    return jsonify({"status": "ok", "service": "yaml-case-generator"})


@static_bp.route("/report/<path:filename>")
def serve_report(filename):
    return send_from_directory(str(REPORT_DIR), filename)
