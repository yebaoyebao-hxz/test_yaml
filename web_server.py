#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试用例生成后台 Web 服务
启动方式: python web_server.py
访问地址: http://127.0.0.1:5000

依赖: pip install flask
(已在 .venv 中安装)
"""

import sys, os, re, traceback, sqlite3, subprocess, shutil, json

import httpx
import yaml as _yaml
from pathlib import Path


from utils.mysql_tool.mysql_connect import DBManager

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "utils" / "read_files_tools"))
sys.path.insert(0,str(PROJECT_ROOT / "utils"/"mysql_tool"))

from flask import Flask, request, jsonify, send_from_directory, render_template

# ── 导入生成核心 ──
from utils.read_files_tools.get_yaml_case import generate, generate_batch

app = Flask(__name__, template_folder='html')

# ============================================================
# 数据库（SQLite，路径可配置）
# ============================================================
DB_PATH = str(PROJECT_ROOT / "history.db")

def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    with _get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS test_cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                input_type TEXT DEFAULT '',
                input_content TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                yaml_body TEXT DEFAULT '',
                model TEXT DEFAULT '',
                executed INTEGER DEFAULT 0,
                report_path TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

init_db()

# ============================================================
# 报告目录（Allure HTML）
# ============================================================
REPORT_DIR = PROJECT_ROOT / "report" / "html"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# HTML 页面（内嵌，零依赖，免配置）
# ============================================================

# ── YAML 头部清理：剥离 AI 输出的非 YAML 前言 ──
def _trim_yaml_head(yaml_text):
    """跳过 YAML 正文前的裸文本行（AI 常在第一行输出标题/摘要）"""
    lines = yaml_text.split("\n")
    start = 0
    for i, line in enumerate(lines):
        s = line.strip()
        # 空行、注释 → 保留（跳过持续扫描）
        if not s or s.startswith("#"):
            continue
        # 顶格 key:（如 case_common: / login_01:）→ 从这里开始
        if re.match(r'^[a-zA-Z_][\w]*:\s*$', s):
            start = i
            break
        # 缩进 + 键值对 → 从这里开始
        if re.match(r'^\s+[\w.-]+\s*:', line):
            start = i
            break
        # 顶格注释、列表等也放过
        if s.startswith(("-", "---", "...")):
            start = i
            break
        # 裸文本行（无冒号、非特殊字符开头）→ 跳过
    return "\n".join(lines[start:])

# ── YAML 安全处理：自动给含特殊字符的裸值加引号 ──
def _sanitize_yaml_scalars(yaml_text):
    yaml_text = _trim_yaml_head(yaml_text)  # 先清理 AI 前言
    lines = yaml_text.split("\n")
    out = []
    for line in lines:
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            out.append(line)
            continue
        line = re.sub(r"(\s+value:\s+)'(\d+)'", r"\1\2", line)
        # 修复 :'' (冒号接空单引号，YAML 解析失败)
        if re.search(r":''\s*$", line):
            line = re.sub(r":''\s*$", ":", line)
        m = re.match(r"^(\s*)([^:]+):\s+(\S.*)$", line)
        if not m:
            out.append(line)
            continue
        indent, key, val = m.group(1), m.group(2), m.group(3)
        v = val.strip()
        if not v or v.startswith(("'", '"', "{", "[")):
            out.append(line)
            continue
        # YAML 块标量：| 或 > 后紧跟换行/缩进指示符才放过，其余（>= != 等比较符）需引号
        if v.startswith(("|", ">")):
            rest = v[1:]
            if rest in ('', '-', '+', '>-', '>+', '|-', '|+'):
                out.append(line)
                continue
        # ! 开头的是 YAML tag，但 != 是运算符，需引号
        if v.startswith("!"):
            if v != '!=' and not v.startswith('!!'):
                out.append(line)
                continue
        # > | ! 开头且非块标量/合法tag → 比较运算符等，必须引号
        if v and v[0] in ('>', '|', '!'):
            q = '"' if "'" in v else "'"
            new_line = f"{indent}{key}: {q}{v}{q}"
            out.append(new_line)
            continue
        dangerous = any(ch in v for ch in ("*", "&", "!", "{", "}", "[", "]", "#", "%", "@", "`", ","))
        has_colon_or_hash = (":" in v or "#" in v) and not v.startswith("http")
        if dangerous or (has_colon_or_hash and not (v.startswith("$") or v.startswith("http"))):
            q = '"' if "'" in v else "'"
            new_line = f"{indent}{key}: {q}{v}{q}"
            out.append(new_line)
        else:
            out.append(line)
    return "\n".join(out)

def _normalize_yaml_assertions(yaml_text):
    """标准化断言：加 status_code: 200 + 只保留 code 断言字段"""
    lines = yaml_text.split('\n')
    result = []
    in_assert = False
    has_status_code = False
    has_code = False
    assert_indent = 0

    for raw in lines:
        stripped = raw.rstrip()
        indent = len(raw) - len(raw.lstrip())
        is_blank = not stripped or stripped.startswith('#')

        if is_blank:
            result.append(raw)
            continue

        # 顶级 key（非 case_common）：关闭上一个 assert 块
        if indent <= 2 and stripped.endswith(':'):
            key = stripped.split(':')[0].strip()
            if key and not key.startswith('#') and key != 'case_common' and ' ' not in key:
                if in_assert and not has_status_code:
                    result.append(' ' * (assert_indent + 2) + 'status_code: 200')
                in_assert = False
                has_status_code = False
                has_code = False

        # assert: 行（检测 stripped 去掉首部空白）
        if stripped.lstrip() == 'assert:':
            if in_assert and not has_status_code:
                result.append(' ' * (assert_indent + 2) + 'status_code: 200')
            in_assert = True
            assert_indent = indent
            has_status_code = False
            has_code = False
            result.append(raw)
            continue

        if not in_assert:
            result.append(raw)
            continue

        child_indent = assert_indent + 2

        # assert 的直接子 key（用正则提取冒号前的字段名）
        if indent == child_indent:
            m = re.match(r'^(\s*)([^:]+):', raw)
            if m:
                child_key = m.group(2).strip()
                if child_key == 'status_code':
                    has_status_code = True
                    has_code = False
                    result.append(raw)
                    continue
                if child_key == 'code':
                    has_code = True
                    result.append(raw)
                    continue
                # 其他字段 → 跳过
                has_code = False
                continue

        # 子树：仅保留当前 code 子树
        if indent > child_indent:
            if has_code:
                result.append(raw)
            continue

        continue

    # 文件末尾仍有未关闭的 assert
    if in_assert and not has_status_code:
        result.append(' ' * (assert_indent + 2) + 'status_code: 200')

    return '\n'.join(result)

# PAGE_HTML 已抽取至 html/index.html（通过 Flask render_template 加载）

# ============================================================
# 路由
# ============================================================
@app.route("/")
def index():
    return render_template('index.html')

@app.route("/api/generate", methods=["POST"])
def api_generate():
    """统一生成接口"""
    try:
        body = request.get_json(force=True)
        if not body:
            return jsonify({"success": False, "error": "请求体为空"})

        input_type = body.get("type", "text")
        content = body.get("content", "")
        images = body.get("images", [])

        if not content and not images:
            return jsonify({"success": False, "error": "输入内容为空"})

        # 如果有截图附件，和文本描述合并发送给AI
        if images and content and input_type in ("curl", "text"):
            result = generate("mixed", {"text": content, "input_type": input_type, "images": images})
        elif images and not content:
            # 纯图片模式
            result = generate("image", images[0])
        else:
            result = generate(input_type, content)

        normalize = body.get("normalize_asserts", False)

        # 标准化断言：加 status_code: 200 + 只保留 code 字段
        if normalize and result.get("success"):
            raw_yaml = result.get("yaml", "") or result.get("yaml_body", "")
            if raw_yaml:
                normalized = _normalize_yaml_assertions(raw_yaml)
                if result.get("yaml_body"):
                    result["yaml_body"] = normalized
                if result.get("yaml"):
                    result["yaml"] = normalized

        # 生成成功后存入 MySQL test_yaml_cases
        yaml_body = result.get("yaml_body", "")
        if result.get("success") and yaml_body:
            safe_name = result.get("summary", "generated")
            safe_name = re.sub(r'[\\/:*?"<>|]', '', safe_name)[:30] or "auto_yaml"
            try:
                mysql_conn = get_db_conn()
                try:
                    with mysql_conn.cursor() as cur:
                        cur.execute(
                            """INSERT INTO test_yaml_cases
                                (filename, yaml_body, input_type, input_content, summary, model, exec_status)
                                VALUES (%s, %s, %s, %s, %s, %s, 'generated')""",
                            (safe_name, yaml_body, input_type,
                             (content or "")[:10000],
                             result.get("summary", ""),
                             result.get("model", ""))
                        )
                        mysql_conn.commit()
                finally:
                    mysql_conn.close()
            except Exception as e:
                print(f"[WARN] MySQL 写入 YAML 失败: {e}")

        return jsonify(result)

    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": f"服务异常: {str(e)}",
        }), 500

@app.route("/api/batch", methods=["POST"])
def api_batch():
    """批量生成接口"""
    try:
        body = request.get_json(force=True)
        if not body or "requests" not in body:
            return jsonify({"success": False, "error": "缺少 requests 字段"})

        results = generate_batch(body["requests"])
        return jsonify({"success": True, "results": results})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "yaml-case-generator"})


# ============================================================
# 报告静态文件
# ============================================================
@app.route("/report/<path:filename>")
def serve_report(filename):
    return send_from_directory(str(REPORT_DIR), filename)


# ============================================================
# 数据库 API
# ============================================================
@app.route("/api/db/config", methods=["GET", "POST"])
def api_db_config():
    """查询/设置数据库路径"""
    global DB_PATH
    if request.method == "GET":
        return jsonify({
            "db_path": DB_PATH,
            "exists": os.path.exists(DB_PATH),
        })
    else:
        body = request.get_json(force=True) or {}
        new_path = body.get("db_path", "")
        if new_path and os.path.isdir(os.path.dirname(new_path) or "."):
            DB_PATH = new_path
            init_db()
            return jsonify({"success": True, "db_path": DB_PATH})
        return jsonify({"success": False, "error": "无效路径"}), 400

@app.route("/api/db/records", methods=["GET"])
def api_db_records():
    """查询历史记录（MySQL 两表 JOIN，失败回退 SQLite）"""
    limit = request.args.get("limit", 50, type=int)
    try:
        mysql_conn = get_db_conn()
        try:
            with mysql_conn.cursor() as cur:
                cur.execute(
                    """SELECT
                        tc.id, tc.filename, tc.summary, tc.model,
                        tc.exec_status, tc.input_type,
                        COALESCE(tc.input_content, '') as input_content,
                        COALESCE(tc.yaml_body, '') as yaml_body,
                        DATE_FORMAT(tc.created_at, '%%Y-%%m-%%d %%H:%%i:%%S') as created_at,
                        tr.id as report_id, tr.total, tr.passed, tr.failed,
                        tr.skipped, tr.broken, tr.pass_rate, tr.duration,
                        tr.report_path
                    FROM test_yaml_cases tc
                    LEFT JOIN test_allure_reports tr ON tc.id = tr.yaml_case_id
                    ORDER BY tc.id DESC
                    LIMIT %s""",
                    (limit,)
                )
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
            records = [dict(zip(cols, row)) for row in rows]
        finally:
            mysql_conn.close()
        return jsonify({
            "success": True,
            "count": len(records),
            "source": "mysql",
            "records": records,
        })
    except Exception as e:
        # MySQL 不可用时回退 SQLite
        try:
            with _get_db() as conn:
                rows = conn.execute(
                    "SELECT * FROM test_cases ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            return jsonify({
                "success": True,
                "count": len(rows),
                "source": "sqlite",
                "records": [dict(r) for r in rows],
            })
        except Exception as e2:
            return jsonify({"success": False, "error": str(e2)}), 500


# ============================================================
# 执行用例 API
# ============================================================
@app.route("/api/execute", methods=["POST"])
def api_execute():
    """保存 YAML → 生成测试文件 → 执行 pytest → 生成 Allure 报告"""
    try:
        body = request.get_json(force=True) or {}
        yaml_body = body.get("yaml_body", "")
        filename = body.get("filename", "auto_yaml_case")
        input_type = body.get("input_type", "")
        input_content = body.get("input_content", "")
        summary = body.get("summary", "")
        model = body.get("model", "")

        if not yaml_body:
            return jsonify({"success": False, "error": "YAML 内容为空"}), 400

        # 1. 保存 YAML 到 data/ 目录
        safe_name = filename.replace(" ", "_").replace("/", "_").replace("\\", "_")
        data_dir = PROJECT_ROOT / "data"
        data_dir.mkdir(exist_ok=True)
        yaml_path = data_dir / f"{safe_name}.yaml"
        # 存入磁盘前清洗：切除 AI 生成的标题行、清理脏字符（避免后续 conftest/pytest 解析失败）
        clean_yaml = _trim_yaml_head(yaml_body)
        clean_yaml = _sanitize_yaml_scalars(clean_yaml)
        yaml_path.write_text(clean_yaml, encoding="utf-8")

        # 2. 存入数据库
        with _get_db() as conn:
            conn.execute(
                """INSERT INTO test_cases (filename, input_type, input_content, summary, yaml_body, model)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (safe_name, input_type, input_content[:10000], summary, yaml_body, model)
            )
            record_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        # 2.5 点击执行后存储数据库
        mysql_case_id = None
        try:
            mysql_conn = get_db_conn()
            try:
                with mysql_conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO test_yaml_cases
                            (filename, yaml_body, input_type, input_content, summary, model, exec_status)
                            VALUES (%s, %s, %s, %s, %s, %s, 'generated')""",
                        (safe_name, yaml_body, input_type, input_content[:10000], summary, model)
                    )
                    mysql_conn.commit()
                    mysql_case_id = cur.lastrowid
            finally:
                mysql_conn.close()
                print(f"[DEBUG] mysql_case_id = {mysql_case_id}")
        except Exception as e:
                print(f"[WARN] MySQL 写入 YAML 失败: {e}")


        # 3. 生成测试文件（自包含，不依赖缓存）
        # 注册自定义标签构造器，处理 !=、== 等被误解析为 YAML tag 的值
        class _SafeStringLoader(_yaml.SafeLoader):
            pass

        def _tag_handler(loader, tag_suffix, node):
            if isinstance(node, _yaml.nodes.ScalarNode):
                return tag_suffix
            return None

        _SafeStringLoader.add_multi_constructor('', _tag_handler)
        safe_yaml_body = _sanitize_yaml_scalars(yaml_body)
        try:
            case_data = _yaml.load(safe_yaml_body, Loader=_SafeStringLoader)
        except Exception as _ye:
            # 诊断：打印前后 200 字符帮助定位
            preview = safe_yaml_body[:500]
            return jsonify({
                "success": False,
                "error": f"YAML 解析失败：{_ye}",
                "yaml_preview": preview,
                "hint": "请检查 YAML 缩进、特殊字符或重复键"
            }), 400
        common = case_data.get("case_common", {})
        case_ids = [k for k in case_data.keys() if k != "case_common"]

        # 从 YAML 提取安全的文件名/类名（仅 ASCII + 下划线）
        def _safe_ident(raw: str, fallback: str = "auto_case") -> str:
            """清洗为合法 Python 标识符（仅保留 ASCII 字母数字下划线）"""
            s = raw.replace(" ", "_").replace("-", "_")
            s = "".join(c for c in s if c.isascii() and (c.isalnum() or c == "_"))
            s = s.strip("_")
            if not s or s[0].isdigit():
                s = "_" + s if s else ""
            return s if s else fallback

        # 优先用 allureEpic / allureFeature 做文件名
        feature = common.get("allureFeature", "") or common.get("allureEpic", "")
        yaml_stem = _safe_ident(feature) if feature and _safe_ident(feature) != "auto_case" else _safe_ident(safe_name)
        # 如果标识符全是数字/下划线（如 _5），或无意义，用时间戳兜底
        from datetime import datetime as _dt
        bare = yaml_stem.lstrip("_")
        if yaml_stem == "auto_case" or len(yaml_stem) < 2 or bare == "" or bare.isdigit():
            yaml_stem = "case_" + _dt.now().strftime("%m%d_%H%M%S")

        # 测试文件路径
        test_case_dir = PROJECT_ROOT / "test_case"
        test_case_dir.mkdir(exist_ok=True)
        case_path = str(test_case_dir / f"test_{yaml_stem}.py")
        file_name = f"test_{yaml_stem}.py"
        case_path_obj = test_case_dir / file_name
        case_path = str(case_path_obj)

        # 类名：foo_bar → FooBar
        class_title = "".join(w.capitalize() for w in yaml_stem.split("_")) if yaml_stem else "AutoCase"
        func_title = yaml_stem

        # 使用项目原有测试模板（GetTestCase.case_data + regular），
        # 在 test_case/conftest.py 中预填充缓存解决子进程缓存丢失问题。
        # conftest.py: 从环境变量 CASE_YAML 读取 YAML 路径 → 解析 → 填入 CacheHandler
        conftest_code = '''# -*- coding: utf-8 -*-
"""
conftest.py — 预填充 GetTestCase.case_data 所需缓存。
支持: CASE_YAML 环境变量 或 data/ 目录自动发现
"""
import os, glob, yaml

def pytest_sessionstart(session):
    yaml_path = os.environ.get("CASE_YAML")
    if not yaml_path or not os.path.exists(yaml_path):
        yaml_path = _auto_discover_yaml()
    if not yaml_path or not os.path.exists(yaml_path):
        print("[conftest] CASE_YAML 未设置且 data/ 无 YAML，缓存未填充", flush=True)
        return

    print(f"[conftest] 从 YAML 填充缓存: {yaml_path}", flush=True)

    class _L(yaml.SafeLoader):
        pass
    def _tag_ctor(loader, tag, node):
        if isinstance(node, yaml.nodes.ScalarNode):
            return tag
        return None
    _L.add_multi_constructor("", _tag_ctor)

    with open(yaml_path, encoding="utf-8") as f:
        raw_text = f.read()
        # 防御 AI 生成的 YAML 有裸标题行
        import re
    lines, start = raw_text.splitlines(True), 0
    for i, L in enumerate(lines):
        s = L.lstrip()
        if not s or s.startswith('#') or s.startswith('---'):
            continue
        if len(L) - len(s) == 0 and re.match(r'^[a-zA-Z_\u4e00-\u9fff][\w\u4e00-\u9fff-]*\s*:', s):
            start = i
            break
    raw_text = ''.join(lines[start:])
    raw = yaml.load(raw_text, Loader=_L)
    common = raw.get("case_common", {})
    from utils.cache_process.cache_control import CacheHandler

    for key, case in raw.items():
        if key == "case_common":
            continue
        host_val = common.get("host", "") or case.get("host", "")
        url = (host_val or "") + (case.get("url", "") or "")
        entry = {
            "case_id": key, "url": url,
            "method": (case.get("method", "POST") or "POST").upper(),
            "is_run": case.get("is_run"),
            "detail": case.get("detail", key),
            "headers": case.get("headers") or {},
            "requestType": (case.get("requestType", "JSON") or "JSON").upper(),
            "data": case.get("data") or {},
            "dependence_case": case.get("dependence_case") or False,
            "dependence_case_data": case.get("dependence_case_data"),
            "current_request_set_cache": case.get("current_request_set_cache"),
            "sql": case.get("sql"),
            "assert_data": case.get("assert") or [],
            "setup_sql": case.get("setup_sql"),
            "teardown": case.get("teardown"),
            "teardown_sql": case.get("teardown_sql"),
            "sleep": case.get("sleep"),
        }
        CacheHandler.update_cache(cache_name=key, value=entry)

    print(f"[conftest] 缓存已填充 {len([k for k in raw if k != \"case_common\"])} 条用例", flush=True)


def _auto_discover_yaml():
    """扫描 data/ 目录，按文件修改时间选最新的 YAML"""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(project_root, "data")
    if not os.path.isdir(data_dir):
        return None
    yaml_files = glob.glob(os.path.join(data_dir, "*.yaml")) + \
                 glob.glob(os.path.join(data_dir, "*.yml"))
    if not yaml_files:
        return None
    yaml_files.sort(key=os.path.getmtime, reverse=True)
    return yaml_files[0]
'''
        (test_case_dir / "conftest.py").write_text(conftest_code, encoding="utf-8")

        # 生成测试文件（保持项目原有模板格式：GetTestCase + regular + eval）
        now_str = _dt.now().strftime('%Y-%m-%d %H:%M:%S')
        test_code = f'''#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time   : {now_str}


import allure
import pytest
from utils.read_files_tools.get_yaml_data_analysis import GetTestCase
from utils.assertion.assert_control import Assert
from utils.requests_tool.request_control import RequestControl
from utils.read_files_tools.regular_control import regular
from utils.requests_tool.teardown_control import TearDownHandler


case_id = {case_ids}
TestData = GetTestCase.case_data(case_id)
re_data = regular(str(TestData))


@allure.epic("{common.get("allureEpic", "自动生成")}")
@allure.feature("{common.get("allureFeature", "自动生成")}")
class Test{class_title}:

    @allure.story("{common.get("allureStory", "自动生成")}")
    @pytest.mark.parametrize('in_data', eval(re_data), ids=[i['detail'] for i in TestData])
    def test_{func_title}(self, in_data):
        """
        :param :
        :return:
        """
        res = RequestControl(in_data).http_request()
        TearDownHandler(res).teardown_handle()
        Assert(assert_data=in_data['assert_data'],
               sql_data=res.sql_data,
               request_data=res.body,
               response_data=res.response_data,
               status_code=res.status_code).assert_type_handle()


if __name__ == '__main__':
    pytest.main(['{file_name}', '-s', '-W', 'ignore:Module already imported:pytest.PytestWarning'])
'''
        case_path_obj.write_text(test_code, encoding="utf-8")
        # 通过环境变量把 YAML 路径传给子进程 conftest
        _exec_env = {**os.environ, "CASE_YAML": str(yaml_path)}

        # 清理旧的 allure-results（避免累积历史数据）
        allure_results_dir = PROJECT_ROOT / "report" / "allure-results"
        if allure_results_dir.exists():
            shutil.rmtree(str(allure_results_dir))
        allure_results_dir.mkdir(parents=True, exist_ok=True)

        # 4. 执行 pytest 并生成 Allure 报告
        pytest_cmd = [
            sys.executable, "-m", "pytest", case_path,
            "--alluredir", str(allure_results_dir),
            "-v"
        ]
        proc = subprocess.run(
            pytest_cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(PROJECT_ROOT),
            env=_exec_env,
        )

        # 生成 Allure HTML 报告（尝试多个路径）
        allure_bin = r"E:\allure-2.41.0\bin\allure.bat"
        if not os.path.exists(allure_bin):
            allure_bin = "allure"  # 回退到 PATH 中的 allure
        allure_cmd = [
            allure_bin, "generate",
            str(allure_results_dir),
            "-o", str(REPORT_DIR),
            "--clean"
        ]
        allure_ok = False
        try:
            allure_proc = subprocess.run(allure_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            allure_ok = ("successfully generated" in allure_proc.stdout or
                         "successfully generated" in allure_proc.stderr or
                         os.path.exists(REPORT_DIR / "index.html"))
        except (FileNotFoundError, OSError) as e:
            print(f"[WARN] allure 命令 ({allure_bin}) 不可用: {e}")

        # 5. 更新数据库执行状态
        with _get_db() as conn:
            conn.execute(
                "UPDATE test_cases SET executed=1, report_path=? WHERE id=?",
                (str(REPORT_DIR), record_id)
            )
        # 5.5 写入 MySQL Allure 报告（不管 allure_ok 状态，只要有 summary.json 就入库）
        if mysql_case_id:
            summary_file = REPORT_DIR / "widgets" / "summary.json"
            print(f"[DEBUG] summary_file exists: {summary_file.exists()}, path: {summary_file}")
            if summary_file.exists():
                import json
                try:
                    with open(summary_file, "r", encoding="utf-8") as f:
                        stats = json.load(f).get("statistic", {})
                except Exception:
                    stats = {}
                try:
                    mysql_conn = get_db_conn()
                    try:
                        with mysql_conn.cursor() as cur:
                            total = stats.get("total", 0) or 1
                            cur.execute(
                                """INSERT INTO test_allure_reports
                                    (yaml_case_id, report_path, total, passed, failed,
                                     skipped, broken, pass_rate, duration, exec_status)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                                (
                                    mysql_case_id,
                                    str(REPORT_DIR),
                                    stats.get("total", 0),
                                    stats.get("passed", 0),
                                    stats.get("failed", 0),
                                    stats.get("skipped", 0),
                                    stats.get("broken", 0),
                                    round(stats.get("passed", 0) / total * 100, 2),
                                    stats.get("duration", 0),
                                    "passed" if proc.returncode == 0 else "failed",
                                )
                            )
                            mysql_conn.commit()
                        with mysql_conn.cursor() as cur:
                            cur.execute(
                                "UPDATE test_yaml_cases SET exec_status=%s WHERE id=%s",
                                ("passed" if proc.returncode == 0 else "failed", mysql_case_id),
                            )
                            mysql_conn.commit()
                    finally:
                        mysql_conn.close()
                except Exception as e:
                    print(f"[WARN] MySQL 写入报告失败: {e}")
            else:
                # summary.json 不存在，至少更新 exec_status
                try:
                    mysql_conn = get_db_conn()
                    try:
                        with mysql_conn.cursor() as cur:
                            cur.execute(
                                "UPDATE test_yaml_cases SET exec_status=%s WHERE id=%s",
                                ("passed" if proc.returncode == 0 else "failed", mysql_case_id),
                            )
                            mysql_conn.commit()
                    finally:
                        mysql_conn.close()
                except Exception as e:
                    print(f"[WARN] MySQL 更新状态失败: {e}")


        # 6. 构造返回结果
        report_url = f"/report/index.html" if os.path.exists(REPORT_DIR / "index.html") else ""
        return jsonify({
            "success": True,
            "pytest_rc": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "yaml_file": str(yaml_path),
            "test_file": case_path,
            "report_url": report_url
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": f"执行失败: {str(e)}",
            "traceback": traceback.format_exc()
        }), 500


# ============================================================
# AI 断言接口
# ============================================================
@app.route("/api/ai_assert", methods=["POST"])
def api_ai_assert():
    """解析 YAML → 发送 HTTP 请求 → 调用 AI 语义断言"""
    try:
        body = request.get_json(force=True) or {}
        yaml_body = body.get("yaml_body", "")
        normalize_asserts = body.get("normalize_asserts", False)
        if not yaml_body:
            return jsonify({"success": False, "error": "YAML 内容为空"}), 400

        from utils.assertion.assert_control import AI_Assert

        safe_yaml_body = _sanitize_yaml_scalars(yaml_body)
        class _L(_yaml.SafeLoader):
            pass
        def _h(loader, tag, node):
            if isinstance(node, _yaml.nodes.ScalarNode):
                return tag
            return None
        _L.add_multi_constructor('', _h)
        case_data = _yaml.load(safe_yaml_body, Loader=_L)

        case_ids = [k for k in case_data.keys() if k != "case_common"]
        if not case_ids:
            return jsonify({"success": False, "error": "YAML 中没有用例"}), 400

        results = []
        with httpx.Client(verify=False, timeout=30.0) as client:
            common_host = case_data.get("case_common",{}).get("host","")if isinstance(case_data.get("case_common"), dict) else ""
            for cid in case_ids:
                case = case_data[cid]
                host = case.get("host","") or common_host
                url = case.get("url", "")
                method = case.get("method", "POST").upper()
                headers = case.get("headers", {})
                data = case.get("data", {})
                detail = case.get("detail", "")

                if not host or not url:
                    results.append({"case_id": cid, "status": "错误", "reason": "缺少 host 或 url"})
                    continue

                full_url = host.rstrip("/") + "/" + url.lstrip("/")

                try:
                    content_type = headers.get("Content-Type", "")
                    if method == "GET":
                        resp = client.get(full_url, params=data, headers=headers)
                    elif "json" in content_type:
                        resp = client.request(method, full_url, json=data, headers=headers)
                    else:
                        resp = client.request(method, full_url, data=data, headers=headers)

                    # 解析响应体
                    try:
                        resp_body = resp.json()
                    except Exception:
                        resp_body = resp.text

                    response_data = {
                        "status_code": resp.status_code,
                        "body": resp_body
                    }

                    # 从 YAML assert 块提取断言描述
                    assert_block = case.get("assert", {})
                    if normalize_asserts:
                        # 标准化模式：仅断言 code 字段
                        code_rules = assert_block.get("code", {})
                        if isinstance(code_rules, dict):
                            val = code_rules.get("value", "")
                            jp = code_rules.get("jsonpath", "$.code")
                            typ = code_rules.get("type", "==")
                            assert_desc = f"{jp} {typ} {val}"
                        else:
                            assert_desc = detail or ""
                    else:
                        # 原有逻辑：提取所有断言字段
                        assert_desc_parts = []
                        for field_name, field_rules in assert_block.items():
                            if isinstance(field_rules, dict):
                                val = field_rules.get("value", "")
                                typ = field_rules.get("type", "")
                                jp = field_rules.get("jsonpath", f"$.{field_name}")
                            else:
                                val = field_rules
                                typ = ""
                                jp = f"$.{field_name}"
                            if field_name == "status_code":
                                continue  # status_code 不在 AI 断言中显示
                            assert_desc_parts.append(f"{jp} {typ} {val}")
                        assert_desc = "; ".join(assert_desc_parts) if assert_desc_parts else detail

                    ai = AI_Assert()
                    status, reason = ai.ai_handle(response_data, assert_desc or detail)

                    results.append({
                        "case_id": cid,
                        "status": status,
                        "reason": reason,
                        "assert_desc": assert_desc or detail,
                        "response_code": resp.status_code
                    })
                except Exception as req_err:
                    results.append({
                        "case_id": cid,
                        "status": "错误",
                        "reason": f"请求异常: {str(req_err)}"
                    })

        all_passed = all(r["status"] == "通过" for r in results)
        return jsonify({
            "success": all_passed,
            "status": "通过" if all_passed else "不通过",
            "results": results,
            "summary": f"{sum(1 for r in results if r['status'] == '通过')}/{len(results)} 通过"
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": f"AI断言异常: {str(e)}"}), 500

# ============================================================
# 链接数据库，存放数据
# ============================================================
def get_db_conn():
    """获取 MySQL 数据库连接"""
    return DBManager().connect()


# ============================================================
# 启动
# ============================================================
if __name__ == "__main__":
    import io, sys as _sys
    _sys.stdout = io.TextIOWrapper(_sys.stdout.buffer, encoding="utf-8")
    _sys.stderr = io.TextIOWrapper(_sys.stderr.buffer, encoding="utf-8")
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
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
