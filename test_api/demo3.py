#!/usr/bin/env python
# -*- coding: utf-8 -*-
# ============================================================
# demo3.py — AI 测试用例生成服务（测试平台可调用版）
# ============================================================
# 用法：
#   from demo3 import generate
#   result = generate("curl", curl_text)
#   result = generate("text", description_text)
#   result = generate("image", image_path_or_base64)
#   result = generate_batch([...])  # 批量
#
# 返回值统一为 dict：
#   {"success": bool, "yaml": str|None, "summary": str|None, "error": str|None}
# ============================================================

import base64
import re
from dataclasses import dataclass, field
from typing import Optional, List, Union

from openai import OpenAI
from openai import AuthenticationError, APIError, RateLimitError

from api_config import AI_Config


# ============================================================
# 系统提示词（不变）
# ============================================================
SYSTEM_PROMPT = """你是高级游戏测试工程师，根据用户输入的API信息生成YAML测试用例。

---

## 输入处理

支持三种输入方式，按以下规则解析：

- **文本**：直接提取接口路径、method、参数列表、响应结构
- **curl命令**：解析 -H → headers，--data-raw → 参数，URL → 域名+路径，-X → method
- **截图**：识别图中所有文字，提取URL、参数名、参数类型、必填标识、响应示例

---

## YAML 输出模板（严格按此结构）

case_common:
  allureEpic: 盲盒APP
  allureFeature: [模块名]
  allureStory: [接口用途]

[用例名]_01:
  host:
  url: [路径]
  method: POST
  detail: [场景描述]
  headers:
    Content-Type: application/json;charset=UTF-8
    requestType: json
  is_run:
  data:
    [参数]: '[值]'
  dependence_case: False
  dependence_case_data:
  assert:
    code:
      jsonpath: $.code
      type: ==
      value: '00000'
      AssertType:
    msg:
      jsonpath: $.msg
      type: ==
      value: ok
      AssertType:
  sql:

---

## 生成规则（逐条强制）

### 命名
- 格式：[接口功能英文/拼音]_编号
- 编号含义：01=正常场景，02=参数异常（缺失/类型错误），03=边界值，04=特殊字符，05=并发/重复请求
- 禁止中文用例名

### 数量
- 每个接口至少生成5条用例
- 同一接口的所有用例在同一YAML代码块中输出

### 断言
- 必须包含 code 断言：正常= '00000'，异常=非0code
- 响应含 msg 字段时加 msg 断言：正常= ok，异常=实际错误提示
- 响应含 success 字段时加 success 断言：正常= true，异常= false

### 数据格式
- 数字不加引号：id: 1、count: 100
- 字符串用单引号（YAML中）：username: 'admin'
- 手机号脱敏：mobile: '138****0001'
- 空字符串写 ''，不要省略

### 依赖与提取
- 登录/获取token类接口，下游用例需要用到返回值时，添加 extract 字段：
  extract:
    token:
      jsonpath: $.data.token
- 需要前置用例返回数据的，设置 dependence_case: True，并在 dependence_case_data 中引用
- 无依赖的用例 dependence_case 设为 False

### headers
- 按接口文档补全所有header，至少保留 Content-Type
- 动态token类header填写占位：Authorization: 'Bearer {{token}}'

### 不确定性处理
- 参数名、类型不确定时填 [待确认] 而非留空
- 响应字段不确定时在 assertions 中用 [待确认] 占位_type: ==
  value: '[待确认]'

---

## 输出格式

1. 第一行：一句话简述接口（如"登录接口测试用例，共6条"）
2. 紧接着输出完整YAML代码块
3. 不输出任何其他解释、废话、额外markdown标记
4. YAML缩进统一用2空格

---

## 输出示例

登录接口测试用例，共6条

case_common:
  allureEpic: 盲盒APP
  allureFeature: 登录模块
  allureStory: 验证码登录接口测试

login_01:
  host:
  url: /api/user/login
  method: POST
  detail: 正常登录-正确手机号和验证码
  headers:
    Content-Type: application/json;charset=UTF-8
    requestType: json
  is_run:
  data:
    mobile: '138****0001'
    code: '1234'
    invite_code: ''
  dependence_case: False
  dependence_case_data:
  assert:
    code:
      jsonpath: $.code
      type: ==
      value: '00000'
      AssertType:
    msg:
      jsonpath: $.msg
      type: ==
      value: ok
      AssertType:
  extract:
    token:
      jsonpath: $.data.token
  sql:

"""


# ============================================================
# 数据结构
# ============================================================
@dataclass
class GenResult:
    """统一的生成结果"""
    success: bool
    yaml: Optional[str] = None       # YAML 原文（含简述行）
    summary: Optional[str] = None    # 简述（YAML 第一行）
    yaml_body: Optional[str] = None  # 纯 YAML（去简述行，可直接 safe_load）
    error: Optional[str] = None
    model: Optional[str] = None

    def to_dict(self):
        return {
            "success": self.success,
            "yaml": self.yaml,
            "summary": self.summary,
            "yaml_body": self.yaml_body,
            "error": self.error,
            "model": self.model,
        }


# ============================================================
# 客户端懒初始化（运行时校验）
# ============================================================
_deepseek_client = None
_dashscope_client = None


def _get_deepseek():
    global _deepseek_client
    if _deepseek_client is None:
        _deepseek_client = OpenAI(
            api_key=AI_Config.API_KEY,
            base_url=AI_Config.BASE_URL,
        )
    return _deepseek_client


def _get_dashscope():
    """阿里云 DashScope（OpenAI 兼容接口，支持视觉）"""
    global _dashscope_client
    if _dashscope_client is None:
        _dashscope_client = OpenAI(
            api_key=AI_Config.DASHSCOPE_API_KEY,
            base_url=AI_Config.DASHSCOPE_BASE_URL,
        )
    return _dashscope_client


# ============================================================
# curl 本地解析（前置处理，减少 AI 理解负担）
# ============================================================
def _parse_curl(curl_text: str) -> dict:
    """从 curl 命令字符串提取结构化信息"""
    result = {
        "url": "",
        "method": "GET",
        "headers": {},
        "data": "",
    }

    # 提取 URL（引号内）
    m = re.search(r"""curl\s+['"](\S+?['"])""", curl_text)
    if not m:
        m = re.search(r"curl\s+(\S+)", curl_text)
    if m:
        result["url"] = m.group(1).strip("'\"")

    # -X method
    m = re.search(r"-X\s+(\w+)", curl_text, re.IGNORECASE)
    if m:
        result["method"] = m.group(1).upper()

    # -H headers
    for m in re.finditer(r"""-H\s+['"]\s*([^:]+):\s*(.+?)['"]""", curl_text):
        result["headers"][m.group(1).strip()] = m.group(2).strip()

    # --data-raw / -d / --data
    m = re.search(r"--data-raw\s+['\"](.+?)['\"]", curl_text, re.DOTALL)
    if not m:
        m = re.search(r"""(?:-d|--data)\s+['\"](.+?)['\"]""", curl_text, re.DOTALL)
    if m:
        result["data"] = m.group(1)

    return result


# ============================================================
# 核心生成引擎
# ============================================================
def _call_deepseek(user_message: str) -> GenResult:
    """调用 DeepSeek 纯文本生成"""
    client = _get_deepseek()
    try:
        resp = client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
        )
        raw = resp.choices[0].message.content
        return _parse_raw_output(raw, model="deepseek-v4-flash")
    except AuthenticationError:
        return GenResult(success=False, error="认证失败：请检查 API_KEY 是否有效")
    except RateLimitError:
        return GenResult(success=False, error="限流/欠费：请检查账户余额或稍后重试")
    except APIError as e:
        return GenResult(success=False, error=f"API 错误: {e}")
    except Exception as e:
        return GenResult(success=False, error=f"未知错误: {e}")


def _call_dashscope_vision(image_url_or_base64: str, user_message: str = "") -> GenResult:
    """调用 DashScope 多模态视觉模型（截图→YAML）"""
    client = _get_dashscope()

    # 处理 base64 图片
    if image_url_or_base64.startswith("data:"):
        image_url = image_url_or_base64
    elif image_url_or_base64.startswith(("http://", "https://")):
        image_url = image_url_or_base64
    else:
        # 当作本地路径或纯 base64
        if len(image_url_or_base64) < 1024 and __import__("os").path.isfile(image_url_or_base64):
            # 本地文件路径
            with open(image_url_or_base64, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            image_url = f"data:image/png;base64,{b64}"
        else:
            # 纯 base64 字符串，自动补前缀
            image_url = f"data:image/png;base64,{image_url_or_base64}"

    if not user_message:
        user_message = "请识别这张截图中的API接口信息，生成YAML测试用例"

    try:
        resp = client.chat.completions.create(
            model="qwen-vl-plus",  # 通义千问多模态模型
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_url}},
                        {"type": "text", "text": user_message},
                    ],
                },
            ],
            temperature=0.3,
        )
        raw = resp.choices[0].message.content
        return _parse_raw_output(raw, model="qwen-vl-plus")
    except AuthenticationError:
        return GenResult(success=False, error="DashScope 认证失败：请检查 DASHSCOPE_API_KEY")
    except RateLimitError:
        return GenResult(success=False, error="DashScope 限流：请稍后重试")
    except APIError as e:
        return GenResult(success=False, error=f"DashScope API 错误: {e}")
    except Exception as e:
        return GenResult(success=False, error=f"视觉识别错误: {e}")


# ============================================================
# 输出解析
# ============================================================
def _parse_raw_output(raw: str, model: str = "") -> GenResult:
    """从 AI 原始返回解析出简述 + YAML"""
    if not raw or not raw.strip():
        return GenResult(success=False, error="AI 返回为空", model=model)

    lines = raw.strip().split("\n")
    # 第一行是"简述"
    summary = lines[0].strip()
    # 其余行是 YAML 正文
    yaml_body = "\n".join(lines[1:]).strip()

    return GenResult(
        success=True,
        yaml=raw.strip(),
        summary=summary,
        yaml_body=yaml_body,
        model=model,
    )


# ============================================================
# 公共 API
# ============================================================
def generate(input_type: str, content: str) -> dict:
    """统一入口：给定输入类型和内容，返回 YAML 测试用例

    Args:
        input_type: 输入类型 — "curl" / "text" / "image"
        content:
            - curl:  原始 curl 命令字符串
            - text:  接口自然语言描述
            - image: 图片 base64 / data: URL / 本地文件路径 / HTTP URL

    Returns:
        dict: {"success": bool, "yaml": str, "summary": str, "yaml_body": str, "error": str}
    """
    if not content or not content.strip():
        return GenResult(success=False, error="输入内容为空").to_dict()

    if input_type == "curl":
        # 先本地解析 curl，再传给 AI（附带原始命令以保留上下文）
        parsed = _parse_curl(content)
        rich_input = (
            f"接口信息（从curl解析）：\n"
            f"  完整URL: {parsed['url']}\n"
            f"  Method:  {parsed['method']}\n"
            f"  Headers: {parsed['headers']}\n"
            f"  请求体:  {parsed['data']}\n\n"
            f"原始curl命令：\n{content}"
        )
        return _call_deepseek(rich_input).to_dict()

    elif input_type == "text":
        return _call_deepseek(content).to_dict()

    elif input_type == "image":
        return _call_dashscope_vision(content).to_dict()

    else:
        return GenResult(
            success=False,
            error=f"不支持的 input_type: '{input_type}'，仅支持 curl/text/image",
        ).to_dict()


def generate_batch(requests: List[dict]) -> List[dict]:
    """批量生成（顺序执行）

    Args:
        requests: [{"type": "curl", "content": "..."}, {"type": "image", "content": "..."}]

    Returns:
        [{"success": ..., "index": 0, ...}, ...]
    """
    results = []
    for i, req in enumerate(requests):
        r = generate(req.get("type", "text"), req.get("content", ""))
        r["index"] = i
        results.append(r)
    return results


# ============================================================
# 直接运行（兼容旧用法）
# ============================================================
if __name__ == "__main__":
    api_info = """
curl 'https://wwyd.vip.hnhxzkj.com/api/user/login' \
  -H 'accept: application/json, text/plain, */*' \
  -H 'content-type: application/json;charset=UTF-8' \
  -H 'x-roomid: 12321' \
  --data-raw '{"mobile":"18800000001","code":"1234","invite_code":""}'

响应: {"code":0,"msg":"ok","data":{"token":"xxx"}}  成功响应: code=0  失败响应: code!=0
"""

    result = generate("curl", api_info)
    if result["success"]:
        print("=" * 50)
        print(result["yaml"])
        print("=" * 50)
    else:
        print(f"生成失败: {result['error']}")
