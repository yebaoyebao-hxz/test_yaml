import base64
import re
import warnings
import httpx
from dataclasses import dataclass, field
from typing import Optional, List, Union

from openai import OpenAI
from openai import AuthenticationError, APIError, RateLimitError

from api_config import AI_Config

# 忽略 SSL 证书验证警告（Windows 环境证书链不完整时需跳过）
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

# 系统提示词
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
  allureEpic: [项目名]
  allureFeature: [模块名]
  allureStory: [接口用途]

[用例名]_01:
  host:[地址]
  url: [路径]
  method: POST
  detail: [场景描述]
  headers:
    Content-Type: application/json;charset=UTF-8
    requestType: json
  is_run:
  data:
    [参数]: '[值]'
    # 是否有依赖业务，为空或者false则表示没有
  dependence_case: False
  dependence_case_data:
        # 依赖的数据
  assert:
    # 断言接口状态码
    code:
      jsonpath: $.code
      type: ==
      value: '0'
      AssertType:
    msg:
      jsonpath: $.msg
      type: ==
      value: 'ok'
      AssertType:

---

## 生成规则（逐条强制）

### 命名
- 格式：[接口功能英文/拼音]_编号
- 编号含义：01=正常场景，02=参数异常（缺失/类型错误），03=边界值，04=特殊字符，05=并发/重复请求，06=Token为空
- 禁止中文用例名

### 数量
- 每个接口至少生成8条用例
- 同一接口的所有用例在同一YAML代码块中输出

### 断言
- 必须包含 code 断言：正常= '0'，异常=非0code
- 响应含 msg 字段时加 msg 断言：正常= ok，异常=实际错误提示

### 数据格式
- 数字不加引号：id: 1、count: 100
- 字符串用单引号（YAML中）：username: 'admin'
- ⚠️ 任何值若含 YAML 特殊字符（* & ! # : { } [ ] , @）必须用引号包裹
- 空字符串写 ''，不要省略

### Bearer Token 检测（最高优先级，先生成前必须执行）

仔细检查用户输入（curl/文本/截图）中是否包含 Bearer 认证头，分两种情况处理：

**▸ 情况A：输入已含 Bearer 数据**
- 条件：curl 中有 `-H 'Authorization: Bearer xxx'` 或截图/文本中显示完整 Bearer token（如 eyJ... 开头的 JWT）
- 行为：直接复制该 Bearer 值到 headers，**禁止**使用 $cache{token}
  headers:
    Authorization: 'Bearer eyJhbGciOi...实际值'
- **禁止**生成 login_01 登录用例（token 已有，不需要走登录接口拿）
- **禁止**写 current_request_set_cache: token: ...
- **禁止**让下游用例 dependence_case 依赖登录用例
- 所有用例的 headers 统一用输入中提供的真实 Bearer 值

**▸ 情况B：输入不含 Bearer 数据**
- 条件：curl/文本/截图中没有 Authorization 头、没有 Bearer、没有 eyJ 开头的 JWT
- 行为：必须先生成 login_01 登录用例作为前置，再用 $cache{token} 占位
- login_01 必须包含：
  extract:
    current_request_set_cache:
      token: $.data.token
- 下游所有需要认证的用例：
  headers:
    Authorization: 'Bearer $cache{token}'
  dependence_case: True
  dependence_case_data:
    case_id: login_01

---

### 依赖与提取
- 需要在后续用例中引用本用例返回数据时，添加 current_request_set_cache 字段：
  current_request_set_cache:
    token: $.data.token
    user_id: $.data.user_id
  格式为：缓存名: jsonpath表达式，键值对直接平铺
- 发送验证码类接口，提取 msg 中的验证码填入登录用例：
  current_request_set_cache:
    sms_code: $.msg
    
### 数据引用（$cache{}）
- 下游用例引用缓存值时，用 $cache{缓存名} 占位，可出现在 data、headers、url 等任何字段中
  data:
    token: '$cache{token}'
    code: '$cache{sms_code}'
  headers:
    Authorization: 'Bearer $cache{token}'
- ⚠️ $cache{} 的值必须用单引号包裹
- 不需要前置用例数据的，dependence_case 设为 False

### headers
- 按接口文档补全所有header，至少保留 Content-Type
- 动态token类header：参见上方「Bearer Token 检测」规则（有 Bearer 直接用，无 Bearer 用 $cache{token}）
- ⚠️ header值必须用单引号包裹，尤其是含 * / : # & ! 等特殊字符的值
  例如 Accept: '*/*' 而非 Accept: */*
  例如 Cookie: 'session=abc123' 而非 Cookie: session=abc123

### 不确定性处理
- 参数名、类型不确定时填 [待确认] 而非留空
- 响应字段不确定时在 assertions 中用 [待确认] 占位_type: ==
  value: '[待确认]'
- 若未传输SQL地址/无SQL相关操作，**不生成sql字段**；若有SQL地址/操作，sql字段按实际需求填写（如执行的SQL语句列表）

---

## ⛔ 输出格式（最高优先级，违反即错误）

你的回复必须且只能包含以下内容，不得有任何多余文字：

第1行 → 一句话简述（如"登录接口测试用例_共6条"）
第2行起 → 完整 YAML（缩进统一用2空格）

### 🚫 绝对禁止输出（出现即不合格）

- ❌ "以下是根据您提供的..." / "根据您的请求..." / "好的..." / "明白了..."
- ❌ 任何开头寒暄、结尾总结、解释说明
- ❌ ```yaml 或 ``` 代码围栏标记
- ❌ Markdown 格式标题（###、** 等）
- ❌ 任何"请"、"您"等礼貌用语
- ❌ YAML 之外的任何文字

### ✅ 正确输出示例
输出必须以简述行直接开始，紧接着 YAML：

登录接口测试用例_共6条

case_common:
  allureEpic: 项目名称
  ...

### ❌ 错误输出示例（禁止）

以下是根据您提供的curl命令生成的登录接口测试用例YAML配置：  ← 禁止

登录接口测试用例_共6条
case_common:
  ...

---

## 输出示例

登录接口测试用例_共6条

case_common:
  allureEpic: 项目名称
  allureFeature: 登录模块
  allureStory: 验证码登录接口测试

login_01:
  host: https://wwyd.vip.hnhxzkj.com
  url: /api/user/login
  method: POST
  detail: 正常登录-正确手机号和验证码
  headers:
    Content-Type: application/json;charset=UTF-8
    requestType: json
  is_run:
  data:
    mobile: '13226509766'
    code: '$cache{sms_code}'
    invite_code: ''
    # 是否有依赖业务，为空或者false则表示没有
  dependence_case: False
  dependence_case_data:
        # 依赖的数据
  assert:
    # 断言接口状态码
    code:
      jsonpath: $.code
      type: ==
      value: '0'
      AssertType:
    msg:
      jsonpath: $.msg
      type: ==
      value: ok
      AssertType:
  extract:
    current_request_set_cache:
      token: $.data.token

login_02:
  host: https://wwyd.vip.hnhxzkj.com
  url: /api/login/send_sms
  method: POST
  detail: 手机号为空
  headers:
    Content-Type: application/json; charset=utf-8
    requestType: json
    Accept: '*/*'
    Connection: keep-alive
  is_run:
  data:
    phone: ''
  dependence_case: False
  dependence_case_data:
  assert:
    code:
      jsonpath: $.code
      type: ==
      value: '500'
      AssertType:
    msg:
      jsonpath: $.msg
      type: ==
      value: '请求未携带authorization信息'
      AssertType:
    
login_03:
  host: https://wwyd.vip.hnhxzkj.com
  url: /api/task/list
  method: POST
  detail: 正常获取任务列表-成功返回
  headers:
    Version: 'v1.0'
    User-Agent: 'Apifox/1.0.0 (https://apifox.com)'
    Content-Type: 'application/json;charset=UTF-8'
    Authorization: 'Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJ3ZWJtYW4udGlueXdhbi5jbiIsImF1ZCI6IndlYm1hbi50aW55d2FuLmNuIiwiaWF0IjoxNzc1MTg4NjY2LCJuYmYiOjE3NzUxODg2NjYsImV4cCI6MjYzOTE4ODY2NiwiZXh0ZW5kIjp7ImlkIjoxMjY3NDQsImFjY2Vzc19leHAiOjg2NDAwMDAwMCwicmVmcmVzaF9leHAiOjg2NDAwMDAwMCwibmFtZSI6ImdhbWUiLCJjbGllbnQiOiJNT0JJTEUifX0.ypJirRwybrWAUh-22HoNkJUcfU18_1_R0FS0a4N6Das'
    Accept: '*/*'
    Connection: 'keep-alive'
  is_run:
  data:
    page: 1
    limit: 10
  dependence_case: False
  dependence_case_data:
  assert:
    code:
      jsonpath: $.code
      type: ==
      value: '0'
      AssertType:
    msg:
      jsonpath: $.msg
      type: ==
      value: 'ok'
      AssertType:
"""
_deepseek_client = None
_dashscope_client = None


@dataclass
class YamlCase:
    """统一的生成结果"""
    success: bool
    yaml: Optional[str] = None
    summary: Optional[str] = None
    yaml_body: Optional[str] = None
    error: Optional[str] = None
    model: Optional[str] = None

    def to_dict(self):
        return {
            "success": self.success,
            "yaml": self.yaml,
            "summary": self.summary,
            "yaml_body": self.yaml_body,
            "error": self.error,
            "model": self.model
        }


def _get_deepseek():
    """deepseek OpenAI"""
    global _deepseek_client
    if _deepseek_client is None:
        _deepseek_client = OpenAI(
            api_key=AI_Config.API_KEY,
            base_url=AI_Config.BASE_URL,
            http_client=httpx.Client(verify=False),
        )
    return _deepseek_client


def _get_dashscope():
    """阿里云 DashScope（OpenAI 兼容接口，支持视觉）"""
    global _dashscope_client
    if _dashscope_client is None:
        _dashscope_client = OpenAI(
            api_key=AI_Config.DASHSCOPE_API_KEY,
            base_url=AI_Config.DASHSCOPE_BASE_URL,
            http_client=httpx.Client(verify=False),
        )
    return _dashscope_client


# ============================================================
# curl 本地解析（前置处理，减少 AI 理解负担）
# ============================================================
def _parse_curl(curl_text: str) -> dict:
    """从 curl 命令字符串提取结构化信息"""
    result = {
        "url": "",
        "method": "",
        "headers": {},
        "data": "",
    }
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
def _call_deepseek(user_message: str) -> YamlCase:
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
        return YamlCase(success=False, error="认证失败：请检查 API_KEY 是否有效")
    except RateLimitError:
        return YamlCase(success=False, error="限流/欠费：请检查账户余额或稍后重试")
    except APIError as e:
        return YamlCase(success=False, error=f"API 错误: {e}")
    except Exception as e:
        return YamlCase(success=False, error=f"未知错误: {e}")


def _call_dashscope_vision(image_url_or_base64: str, user_message: str = "") -> YamlCase:
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
        return YamlCase(success=False, error="DashScope 认证失败：请检查 DASHSCOPE_API_KEY")
    except RateLimitError:
        return YamlCase(success=False, error="DashScope 限流：请稍后重试")
    except APIError as e:
        return YamlCase(success=False, error=f"DashScope API 错误: {e}")
    except Exception as e:
        return YamlCase(success=False, error=f"视觉识别错误: {e}")


# ============================================================
# 混合模式：文本 + 截图合并生成
# ============================================================
def _call_mixed(text: str, input_type: str, images: list) -> YamlCase:
    """文本描述 + 截图 → qwen-vl 多模态生成 YAML"""
    client = _get_dashscope()

    # 构建多模态内容数组
    user_content = []

    # 添加所有图片
    for img in images:
        if img.startswith("data:"):
            image_url = img
        elif img.startswith(("http://", "https://")):
            image_url = img
        else:
            image_url = f"data:image/png;base64,{img}"
        user_content.append({"type": "image_url", "image_url": {"url": image_url}})

    # 添加文本提示
    if input_type == "curl":
        parsed = _parse_curl(text)
        rich_text = (
            f"接口信息（从curl解析）：\n"
            f"  完整URL: {parsed['url']}\n"
            f"  Method:  {parsed['method']}\n"
            f"  Headers: {parsed['headers']}\n"
            f"  请求体:  {parsed['data']}\n\n"
            f"原始curl命令：\n{text}\n\n"
            f"请结合以上截图中的接口信息，生成完整的YAML测试用例。"
        )
    else:
        rich_text = (
            f"接口描述：\n{text}\n\n"
            f"请结合以上 {len(images)} 张截图中的接口信息，生成完整的YAML测试用例。"
        )
    user_content.append({"type": "text", "text": rich_text})

    try:
        resp = client.chat.completions.create(
            model="qwen-vl-plus",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
        )
        raw = resp.choices[0].message.content
        return _parse_raw_output(raw, model="qwen-vl-plus (文本+截图)")
    except AuthenticationError:
        return YamlCase(success=False, error="DashScope 认证失败：请检查 DASHSCOPE_API_KEY")
    except RateLimitError:
        return YamlCase(success=False, error="DashScope 限流：请稍后重试")
    except APIError as e:
        return YamlCase(success=False, error=f"DashScope API 错误: {e}")
    except Exception as e:
        return YamlCase(success=False, error=f"混合模式错误: {e}")


# ============================================================
# 输出解析
# ============================================================
def _is_yaml_line(line: str) -> bool:
    """判断一行是否为合法 YAML（而非自然语言废话）"""
    stripped = line.strip()
    if not stripped:
        return True
    # 注释
    if stripped.startswith('#'):
        return True
    # 顶格 case key：case_common: / login_01:
    if re.match(r'^[a-z][a-z0-9_]*_\d{2}:\s*$', stripped):
        return True
    if stripped == 'case_common:':
        return True
    # 顶格简单 key: value
    if re.match(r'^\w[\w.-]*:\s', stripped):
        return True
    # 缩进 + 键值对
    if re.match(r'^[\s]+[\w.-]+\s*:', line):
        return True
    # 缩进 + 列表项
    if re.match(r'^[\s]+- ', line):
        return True
    # 顶格 + 中文 → 大概率是 AI 的废话标题/总结（非 YAML）
    if re.search(r'[\u4e00-\u9fff]', stripped) and not line.startswith(' '):
        return False
    # 其他缩进行（多行文本值、续行等）→ 属于 YAML
    return line.startswith(' ')


def _trim_tail_garbage(yaml_body: str) -> str:
    """从 YAML 正文底部剥离 AI 多余废话。

    1. 基于行结构（缩进/键值对/中文）判断并切尾
    2. 用 YAML 解析器反向验证：解析失败则逐行截尾直到成功
    """
    if not yaml_body:
        return yaml_body
    lines = yaml_body.split("\n")
    # ── 步骤1：基于结构化特征切尾 ──
    end = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if not lines[i].strip():
            continue
        if _is_yaml_line(lines[i]):
            end = i + 1
            break
        end = i
    result = lines[:end]
    while result and not result[-1].strip():
        result.pop()
    cleaned = "\n".join(result)
    # ── 步骤2：YAML 解析器验证，失败则逐行裁减尾部 ──
    import yaml as _y
    attempts = 0
    while attempts < 20:
        try:
            _y.safe_load(cleaned)
            break
        except Exception:
            attempts += 1
            parts = cleaned.split("\n")
            n = len(parts)
            while n > 0 and not parts[n-1].strip():
                n -= 1
            if n == 0:
                break
            parts = parts[:n-1]
            while parts and not parts[-1].strip():
                parts.pop()
            cleaned = "\n".join(parts)
    return cleaned
def _parse_raw_output(raw: str, model: str = "") -> YamlCase:
    """从 AI 原始返回解析出简述 + YAML，自动剥离 AI 废话前缀"""
    if not raw or not raw.strip():
        return YamlCase(success=False, error="AI 返回为空", model=model)

    text = raw.strip()

    # ── 自动剥离 AI 废话前缀 ──
    # 找第一个 YAML 结构行：case_common: 或 case_key_01:
    lines = text.split("\n")
    yaml_start = None
    summary_idx = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        # case_common: → YAML 从这里开始
        if stripped == "case_common:":
            yaml_start = i
            # summary 是上方最近的非空非废话行
            for j in range(i - 1, -1, -1):
                prev = lines[j].strip()
                if not prev:
                    continue
                garbage_patterns = [
                    "以下是根据", "根据您", "好的", "明白了",
                    "```", "以下是", "为您生成", "测试用例YAML",
                ]
                if not any(p in prev for p in garbage_patterns):
                    summary_idx = j
                break
            break
        # 直接以 case_key_01: 开头（没有 case_common）
        if re.match(r'^[a-z][a-z0-9_]*_\d{2}:\s*$', stripped):
            yaml_start = i
            for j in range(i - 1, -1, -1):
                prev = lines[j].strip()
                if not prev:
                    continue
                garbage_patterns = [
                    "以下是根据", "根据您", "好的", "明白了",
                    "```", "以下是", "为您生成",
                ]
                if not any(p in prev for p in garbage_patterns):
                    summary_idx = j
                break
            break

    if yaml_start is None:
        # 没找到标准 YAML 起始行，降级为旧逻辑
        summary = lines[0].strip()
        yaml_body = "\n".join(lines[1:]).strip()
    else:
        summary = lines[summary_idx].strip() if summary_idx is not None else "auto_case"
        yaml_body = "\n".join(lines[yaml_start:]).strip()

    # 清理尾部：YAML 后可能有 AI 尾巴文字
    yaml_body = _trim_tail_garbage(yaml_body)
    yaml_body = yaml_body.strip()

    return YamlCase(
        success=True,
        yaml=f"{summary}\n\n{yaml_body}",
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
        input_type: 输入类型 — "curl" / "text" / "image" / "mixed"
        content:
            - curl:  原始 curl 命令字符串
            - text:  接口自然语言描述
            - image: 图片 base64 / data: URL / 本地文件路径 / HTTP URL
            - mixed: {"text": "...", "input_type": "...", "images": [...]}

    Returns:
        dict: {"success": bool, "yaml": str, "summary": str, "yaml_body": str, "error": str}
    """
    # mixed 模式：文本 + 截图合并生成
    if input_type == "mixed":
        if isinstance(content, dict):
            return _call_mixed(
                content.get("text", ""),
                content.get("input_type", "text"),
                content.get("images", []),
            ).to_dict()
        return YamlCase(success=False, error="mixed 模式需要 JSON 对象格式").to_dict()

    if not content or (isinstance(content, str) and not content.strip()):
        return YamlCase(success=False, error="输入内容为空").to_dict()

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
        return YamlCase(
            success=False,
            error=f"不支持的 input_type: '{input_type}'，仅支持 curl/text/image/mixed",
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