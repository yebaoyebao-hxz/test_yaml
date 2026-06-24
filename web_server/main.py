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
  ├── routes_wsperf.py     ← /api/perf/ws (长链接压测)
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
from web_server.routes_wsperf import wsperf_bp
from web_server.routes_protobuf import proto_bp


def create_app():
    """工厂函数：创建并配置 Flask 应用"""
    # 项目根目录下的 html 文件夹路径（存放前端静态资源）
    html_dir = os.path.join(_project_root, "html")
    app = Flask(
        __name__,
        template_folder=html_dir,       # 模板目录（原有配置）
        static_folder=html_dir,        # 静态文件目录指向 html 文件夹
        static_url_path=""             # 静态文件URL路径为空，使 /css/main.css 直接映射到 html/css/main.css
    )
    app.register_blueprint(gen_bp)
    app.register_blueprint(exec_bp)
    app.register_blueprint(ai_assert_bp)
    app.register_blueprint(db_bp)
    app.register_blueprint(danmaku_bp)
    app.register_blueprint(static_bp)
    app.register_blueprint(wsperf_bp)
    app.register_blueprint(proto_bp)
    return app


def _kill_port(port):
    """杀死占用指定端口的进程，避免旧进程残留导致新版本 HTML 不生效"""
    import subprocess
    try:
        out = subprocess.check_output(
            f'netstat -ano | findstr :{port} | findstr LISTENING',
            shell=True, text=True, timeout=5
        )
        for line in out.strip().split('\n'):
            parts = line.split()
            if parts:
                pid = int(parts[-1])
                subprocess.run(f'taskkill /F /PID {pid}', shell=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"  ⚠  已清理旧进程 PID={pid}（端口 {port} 被占用）")
    except Exception:
        pass  # 端口未被占用或无法清理，正常继续

if __name__ == "__main__":
    _kill_port(5000)

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
║           POST /api/perf/ws  (长链接压测)    ║
║           GET  /api/db/records               ║
║           GET  /health                       ║
╚══════════════════════════════════════════════╝
""")

    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
