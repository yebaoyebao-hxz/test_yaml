import re
import warnings
import httpx
from dataclasses import dataclass, field
from typing import Optional, List, Union

from openai import OpenAI
from openai import AuthenticationError, APIError, RateLimitError

# 假设API配置文件 api_config.py 包含 AI_Config = {"API_KEY": "xxx", "BASE_URL": "xxx"}
from api_config import AI_Config

# 忽略 SSL 证书验证警告
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

# 冒烟测试专用系统提示词
SMOKE_SYSTEM_PROMPT = """你是高级游戏测试工程师，根据用户输入的API信息生成冒烟测试YAML用例。
冒烟测试聚焦核心业务流程，覆盖关键正向场景+核心异常场景，确保主流程可用。

---

## 输入处理
支持两种输入方式：
- **文本**：直接提取接口路径、method、核心参数、响应结构
- **curl命令**：解析 -H → headers，--data-raw → 参数，URL → 域名+路径，-X → method

---

## 冒烟测试YAML输出模板（严格按此结构）
case_common:
  allureEpic: [项目名——冒烟用例]
  allureFeature: [模块名]
  allureStory: [接口用途]
  smoke: true  # 冒烟测试标识

[用例名]_01:
  host: [地址]
  url: [路径]
  method: POST/GET/PUT/DELETE
  detail: [核心正向场景描述]
  priority: high  # 优先级：high/medium/low（冒烟用例仅high/medium）
  headers:
    Content-Type: 'application/json;charset=UTF-8'
    requestType: 'json'
  is_run: true
  data:
    [核心参数]: '[值]'
  dependence_case: False/True
  dependence_case_data:
    case_id: [依赖用例名]
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
    response_time:  # 冒烟必断言响应时间（核心接口<500ms）
      jsonpath: $._meta.response_time
      type: <
      value: 500
      AssertType:

---

## 冒烟测试生成规则（逐条强制）
### 命名规则
- 格式：[接口功能英文/拼音]_编号
- 编号含义：
  01=核心正向场景（主流程）
  02=核心必填参数缺失
  03=核心参数类型错误
  04=权限校验（无token/无效token）
  05=主流程依赖场景
- 禁止中文用例名

### 数量要求
- 每个接口至少生成5条冒烟用例，覆盖核心场景

### 断言规则
- 必须包含code断言：正常= '0'，异常=非0
- 必须包含响应时间断言：核心接口<500ms，非核心<1000ms
- 响应含msg字段时必须加msg断言

### 数据格式
- 数字不加引号，字符串用单引号
- 含YAML特殊字符的值必须用引号包裹
- 空字符串写 ''

### Bearer Token处理（最高优先级）
▸ 情况A：输入含Bearer token
  - 直接复制到headers，禁止生成login_01用例
  - headers: {Authorization: 'Bearer 实际值'}
▸ 情况B：输入不含Bearer token
  - 先生成login_01登录用例，下游用例用$cache{token}占位
  - login_01必须包含extract → current_request_set_cache: {token: $.data.token}
  - 下游用例headers: {Authorization: 'Bearer $cache{token}'}，dependence_case: True

---

## 输出格式（最高优先级）
第1行 → 一句话简述（如"用户登录接口冒烟测试用例_共5条"）
第2行起 → 完整YAML（缩进2空格）
禁止输出任何多余文字、代码围栏、Markdown格式、礼貌用语！
"""

@dataclass
class SmokeYamlCase:
    """冒烟测试用例生成结果"""
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

# DeepSeek客户端单例
_deepseek_client = None
def _get_deepseek():
    global _deepseek_client
    if _deepseek_client is None:
        _deepseek_client = OpenAI(
            api_key=AI_Config.API_KEY,
            base_url=AI_Config.BASE_URL,
            http_client=httpx.Client(verify=False),
        )
    return _deepseek_client

# curl解析（复用原有逻辑）
def _parse_curl(curl_text: str) -> dict:
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

    m = re.search(r"-X\s+(\w+)", curl_text, re.IGNORECASE)
    if m:
        result["method"] = m.group(1).upper()

    for m in re.finditer(r"""-H\s+['"]\s*([^:]+):\s*(.+?)['"]""", curl_text):
        result["headers"][m.group(1).strip()] = m.group(2).strip()

    m = re.search(r"--data-raw\s+['\"](.+?)['\"]", curl_text, re.DOTALL)
    if not m:
        m = re.search(r"""(?:-d|--data)\s+['\"](.+?)['\"]""", curl_text, re.DOTALL)
    if m:
        result["data"] = m.group(1)

    return result

# 调用DeepSeek生成冒烟用例
def _call_deepseek_smoke(user_message: str) -> SmokeYamlCase:
    client = _get_deepseek()
    try:
        resp = client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": SMOKE_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,  # 低随机性保证用例稳定性
        )
        raw = resp.choices[0].message.content
        return _parse_smoke_raw_output(raw, model="deepseek-v4-flash")
    except AuthenticationError:
        return SmokeYamlCase(success=False, error="认证失败：请检查 API_KEY 是否有效")
    except RateLimitError:
        return SmokeYamlCase(success=False, error="限流/欠费：请检查账户余额或稍后重试")
    except APIError as e:
        return SmokeYamlCase(success=False, error=f"API 错误: {e}")
    except Exception as e:
        return SmokeYamlCase(success=False, error=f"未知错误: {e}")

# 解析AI输出（剥离废话，提取简述+YAML）
def _parse_smoke_raw_output(raw: str, model: str = "") -> SmokeYamlCase:
    if not raw or not raw.strip():
        return SmokeYamlCase(success=False, error="AI 返回为空", model=model)

    text = raw.strip()
    lines = text.split("\n")
    yaml_start = None
    summary_idx = None

    # 定位YAML起始行（case_common: 或 用例名_01:）
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "case_common:":
            yaml_start = i
            # 提取上方的简述行
            for j in range(i - 1, -1, -1):
                prev = lines[j].strip()
                if not prev:
                    continue
                garbage_patterns = ["以下是", "根据您", "好的", "```"]
                if not any(p in prev for p in garbage_patterns):
                    summary_idx = j
                break
            break
        if re.match(r'^[a-z][a-z0-9_]*_\d{2}:\s*$', stripped):
            yaml_start = i
            for j in range(i - 1, -1, -1):
                prev = lines[j].strip()
                if not prev:
                    continue
                garbage_patterns = ["以下是", "根据您", "好的", "```"]
                if not any(p in prev for p in garbage_patterns):
                    summary_idx = j
                break
            break

    # 处理解析结果
    if yaml_start is None:
        summary = lines[0].strip()
        yaml_body = "\n".join(lines[1:]).strip()
    else:
        summary = lines[summary_idx].strip() if summary_idx is not None else "smoke_auto_case"
        yaml_body = "\n".join(lines[yaml_start:]).strip()

    # 清理YAML尾部多余内容
    yaml_body = _trim_smoke_yaml_garbage(yaml_body)
    return SmokeYamlCase(
        success=True,
        yaml=f"{summary}\n\n{yaml_body}",
        summary=summary,
        yaml_body=yaml_body,
        model=model,
    )

# 清理YAML尾部无效内容
def _trim_smoke_yaml_garbage(yaml_body: str) -> str:
    if not yaml_body:
        return yaml_body
    lines = yaml_body.split("\n")
    end = len(lines)
    # 反向遍历，保留合法YAML行
    for i in range(len(lines)-1, -1, -1):
        stripped = lines[i].strip()
        if not stripped:
            continue
        # 合法YAML行判断
        if (stripped.startswith('#') or
            re.match(r'^[a-z][a-z0-9_]*_\d{2}:\s*$', stripped) or
            stripped == 'case_common:' or
            re.match(r'^\w[\w.-]*:\s', stripped) or
            lines[i].startswith(' ') or
            re.match(r'^[\s]+- ', lines[i])):
            end = i + 1
            break
        end = i
    # 裁剪并清理空行
    result = lines[:end]
    while result and not result[-1].strip():
        result.pop()
    return "\n".join(result)

# 公共生成入口
def generate_smoke_case(input_type: str, content: str) -> dict:
    """
    生成冒烟测试用例
    Args:
        input_type: 输入类型 - "curl" / "text"
        content: 输入内容（curl命令/文本描述）
    Returns:
        dict: 生成结果（success/yaml/summary/error等）
    """
    if not content or (isinstance(content, str) and not content.strip()):
        return SmokeYamlCase(success=False, error="输入内容为空").to_dict()

    # 处理curl输入（先解析再传给AI）
    if input_type == "curl":
        parsed = _parse_curl(content)
        rich_input = (
            f"接口信息（从curl解析）：\n"
            f"  完整URL: {parsed['url']}\n"
            f"  Method:  {parsed['method']}\n"
            f"  Headers: {parsed['headers']}\n"
            f"  请求体:  {parsed['data']}\n\n"
            f"原始curl命令：\n{content}"
        )
        return _call_deepseek_smoke(rich_input).to_dict()

    # 处理文本输入
    elif input_type == "text":
        return _call_deepseek_smoke(content).to_dict()

    # 不支持的输入类型
    else:
        return SmokeYamlCase(
            success=False,
            error=f"不支持的 input_type: '{input_type}'，仅支持 curl/text",
        ).to_dict()

# 批量生成
def generate_smoke_batch(requests: List[dict]) -> List[dict]:
    results = []
    for i, req in enumerate(requests):
        r = generate_smoke_case(req.get("type", "text"), req.get("content", ""))
        r["index"] = i
        results.append(r)
    return results

# 测试示例
if __name__ == "__main__":
    # 测试文本输入
    test_text = """用户登录接口
    URL: http://zs-bjfyl-dy.danmu.hxzdm.com/game/douyin/anchor_register
    Method: POST
    参数：roomid（必填）
    响应：data.token=xxx
    请求头:X-Unity-Version = 2023.1.13f1
    发送弹幕接口
    URL: https://zs-bjfyl-dy.danmu.hxzdm.com/douyin/webcast/comment_notify
    Method: POST
    参数: msg_id(必填), sec_openid(必填), content(必填),nickname(必填)
    请求头: x-roomid: 12321, X-Unity-Version = 2023.1.13f1
    """
    result = generate_smoke_case("text", test_text)
    if result["success"]:
        print("冒烟测试用例生成成功：")
        print(result["yaml"])
    else:
        print(f"生成失败：{result['error']}")