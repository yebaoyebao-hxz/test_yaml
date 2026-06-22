# -*- coding: utf-8 -*-
"""
YAML 测试用例生成器 Web 后台 —— 主入口
启动方式: python web_server/main.py
  或:    python -m web_server.main
访问地址: http://127.0.0.1:5000

模块结构:
  web_server/
  ├── main.py              ← 本文件（入口）
  ├── config.py            ← 路径/常量/SQLite
  ├── db.py                ← MySQL 连接
  ├── yaml_utils.py        ← YAML 清洗/断言标准化
  ├── templates.py         ← conftest + 测试代码模板
  ├── _conftest_template.py← conftest 模板源文件
  ├── routes_generate.py   ← /api/generate, /api/batch
  ├── routes_execute.py    ← /api/execute
  ├── routes_ai_assert.py  ← /api/ai_assert
  ├── routes_db.py         ← /api/db/config, /api/db/records
  ├── routes_danmaku.py    ← /api/danmaku/*
  └── routes_static.py     ← /, /health, /report/<path>
"""
import io, os, sys

# 确保项目根目录在路径中（支持 python web_server/main.py 方式启动）
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from flask import Flask

# ── 注册 Blueprint ──
from web_server.routes_generate import gen_bp
from web_server.routes_execute import exec_bp
from web_server.routes_ai_assert import ai_assert_bp
from web_server.routes_db import db_bp
from web_server.routes_danmaku import danmaku_bp
from web_server.routes_static import static_bp


def create_app():
    """工厂函数：创建并配置 Flask 应用"""
    app = Flask(__name__, template_folder=os.path.join(_project_root, "html"))
    app.register_blueprint(gen_bp)
    app.register_blueprint(exec_bp)
    app.register_blueprint(ai_assert_bp)
    app.register_blueprint(db_bp)
    app.register_blueprint(danmaku_bp)
    app.register_blueprint(static_bp)
    return app


if __name__ == "__main__":
    # 修复 Windows 控制台 UTF-8 输出
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

    print("""
╔══════════════════════════════════════════════╗
║   🐇 YAML 测试用例生成器 Web 后台           ║
║                                              ║
║   本地访问: http://127.0.0.1:5000            ║
║   报告目录: http://127.0.0.1:5000/report/    ║
║   数据库:   history.db (SQLite)              ║
║                                              ║
║   快捷键: Ctrl+Enter 快速生成                ║
║   接口:   POST /api/generate                 ║
║           POST /api/batch                    ║
║           POST /api/execute                  ║
║           POST /api/ai_assert                ║
║           GET  /api/db/records               ║
║           GET  /health                       ║
╚══════════════════════════════════════════════╝
""")

    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
