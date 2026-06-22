# -*- coding: utf-8 -*-
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
