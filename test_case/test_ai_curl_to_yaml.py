#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试脚本：输入 curl 命令 → AI 生成 YAML 测试用例
用法：
    python test_ai_curl_to_yaml.py
    python test_ai_curl_to_yaml.py --curl "curl -X POST ..."
"""

import sys
import os
import json

# 确保项目根在 sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from utils.read_files_tools.get_yaml_case import generate
from common.setting import ensure_path


# ============================================================
# 以下为测试用的 curl 命令（可自行替换）
# ============================================================
TEST_CURLS = [
    # 排行榜接口
    """curl -X POST 'https://ydmc.vip.hnhxzkj.com/api/user/rank' \\
  -H 'Content-Type: application/json;charset=UTF-8' \\
  -H 'Authorization: Bearer eyJ0...' \\
  --data-raw '{"type":0}'""",

    # 发送短信
    """curl -X POST 'https://wwyd.vip.hnhxzkj.com/api/login/send_sms' \\
  -H 'Content-Type: application/json; charset=utf-8' \\
  -H 'Accept: */*' \\
  --data-raw '{"phone":"13226509766"}'""",
]


def curl_to_yaml(curl_text: str) -> dict:
    """调用 AI 将 curl 命令转换为 YAML 测试用例"""
    print(f"\n{'='*60}")
    print(f"[输入 curl]")
    print(f"{curl_text[:200]}...")
    print(f"{'='*60}")

    result = generate(input_type="curl", content=curl_text)

    if result["success"]:
        print(f"\n[AI 模型] {result.get('model', 'unknown')}")
        print(f"[简述]   {result['summary']}")
        print(f"[生成 YAML 预览]")
        print(result["yaml_body"][:500])
    else:
        print(f"\n[失败] {result['error']}")

    return result


def save_yaml(result: dict, filename: str = None) -> str:
    """将生成的 YAML 保存到 data/ 目录"""
    if not result["success"]:
        print("[跳过保存] 生成失败")
        return ""

    data_dir = ensure_path("\\data\\")
    if filename is None:
        # 从简述生成文件名
        summary = result["summary"].replace(" ", "_").replace("/", "_")
        filename = f"ai_{summary}.yaml"
    filepath = os.path.join(data_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(result["yaml"])

    print(f"\n[已保存] {filepath}")
    return filepath


def main():
    # 1. 如果有命令行参数传入 curl，优先使用
    if len(sys.argv) > 1 and sys.argv[1] == "--curl" and len(sys.argv) > 2:
        curl_text = sys.argv[2]
        results = [curl_to_yaml(curl_text)]
    else:
        # 2. 否则使用内置测试 curl
        print("使用内置测试 curl 命令（可通过 --curl 参数自定义）")
        results = [curl_to_yaml(c) for c in TEST_CURLS]

    # 3. 保存结果
    saved = []
    for r in results:
        path = save_yaml(r)
        if path:
            saved.append(path)

    # 4. 汇总
    print(f"\n{'='*60}")
    print(f"完成！成功 {len(saved)}/{len(results)} 个")
    for p in saved:
        print(f"  → {p}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
    """
    python test_ai_curl_to_yaml.py --curl "curl --location --request POST 'https://ydmc.vip.hnhxzkj.com/api/user/rank' \
    --header 'Version: v1.0' \
    --header 'User-Agent: Apifox/1.0.0 (https://apifox.com)' \
    --header 'Content-Type: application/json' \
    --header 'Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJ3ZWJtYW4udGlueXdhbi5jbiIsImF1ZCI6IndlYm1hbi50aW55d2FuLmNuIiwiaWF0IjoxNzc1MTg4NjY2LCJuYmYiOjE3NzUxODg2NjYsImV4cCI6MjYzOTE4ODY2NiwiZXh0ZW5kIjp7ImlkIjoxMjY3NDQsImFjY2Vzc19leHAiOjg2NDAwMDAwMCwicmVmcmVzaF9leHAiOjg2NDAwMDAwMCwibmFtZSI6ImdhbWUiLCJjbGllbnQiOiJNT0JJTEUifX0.ypJirRwybrWAUh-22HoNkJUcfU18_1_R0FS0a4N6Das' \
    --header 'Accept: */*' \
    --header 'Host: ydmc.vip.hnhxzkj.com' \
    --header 'Connection: keep-alive' \
    --data-raw '{
        "type": 0
    }'"}'"
    
    """
