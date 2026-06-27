import re
import warnings
import httpx
from dataclasses import dataclass, field
from typing import Optional, List, Union

from openai import OpenAI
from openai import AuthenticationError, APIError, RateLimitError

from api_config import AI_Config

# 忽略 SSL 证书验证警告
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

# 压测测试专用系统提示词
STRESS_SYSTEM_PROMPT = """你是高级性能测试工程师，根据用户输入的API信息生成接口压测YAML用例。
压测用例聚焦性能维度，覆盖基准/峰值/疲劳/混合等施压场景，包含并发数、持续时间、性能断言。

---

## 输入处理
支持两种输入方式：
- **文本**：直接提取接口路径、method、核心参数、响应结构
- **curl命令**：解析 -H → headers，--data-raw → 参数，URL → 域名+路径，-X → method

---

## 压测测试YAML输出模板（严格按此结构）
case_common:
  allureEpic: [项目名——压测用例]
  allureFeature: [模块名]
  allureStory: [接口压测]
  stress: true  # 压测标识

[用例名]_01:
  host: [地址]
  url: [路径]
  method: POST/GET/PUT/DELETE
  detail: [压测场景描述]
  stress_type: base/peak/fatigue/mixed/abnormal  # 压测类型
  concurrency: 10  # 并发数
  duration: 60  # 持续时间（秒）
  ramp_up: 10  # 加压时间（秒，阶梯加压）
  headers:
    Content-Type: 'application/json;charset=UTF-8'
    requestType: 'json'
  is_run: true
  data:
    [核心参数]: '[值]'
  # 压测无需依赖用例（独立施压）
  dependence_case: False
  dependence_case_data: {}
  assert:
    # 基础断言
    code:
      jsonpath: $.code
      type: ==
      value: '0'
      AssertType:
    # 性能核心断言
    avg_response_time:  # 平均响应时间
      jsonpath: $._perf.avg_rt
      type: <
      value: 300
      AssertType:
    max_response_time:  # 最大响应时间
      jsonpath: $._perf.max_rt
      type: <
      value: 1000
      AssertType:
    tps:  # 每秒事务数
      jsonpath: $._perf.tps
      type: >
      value: 200
      AssertType:
    error_rate:  # 错误率
      jsonpath: $._perf.error_rate
      type: <
      value: 0.01
      AssertType:

---

## 压测测试生成规则（逐条强制）
### 命名规则
- 格式：[接口功能英文/拼音]_编号
- 编号含义：
  01=基准压测（低并发，验证基础性能）
  02=峰值压测（高并发，接近系统极限）
  03=疲劳压测（长时长，验证稳定性）
  04=混合压测（交替高低并发）
  05=异常流量压测（突发高并发）
  06=参数化压测（多组参数循环）
- 禁止中文用例名

### 数量要求
- 每个接口至少生成6条压测用例，覆盖不同施压场景

### 压测参数规则
- 基准压测：concurrency=10-50，duration=60，ramp_up=10
- 峰值压测：concurrency=100-500，duration=300，ramp_up=30
- 疲劳压测：concurrency=50-100，duration=3600，ramp_up=60
- 混合压测：concurrency=50→200→50，duration=600，ramp_up=20
- 异常流量：concurrency=1000，duration=60，ramp_up=5

### 性能断言规则
- 平均响应时间：核心接口<300ms，非核心<500ms
- 最大响应时间：<1000ms
- TPS：核心接口>200，非核心>50
- 错误率：<1%

### 数据格式
- 数字不加引号，字符串用单引号
- 含YAML特殊字符的值必须用引号包裹
- 压测参数（concurrency/duration/ramp_up）为数字，不加引号

### Bearer Token处理
- 输入含Bearer token：直接复制到headers
- 输入不含Bearer token：生成login_01用例，下游用$cache{token}占位

---

## 输出格式（最高优先级）
第1行 → 一句话简述（如"用户登录接口压测用例_共6条"）
第2行起 → 完整YAML（缩进2空格）
禁止输出任何多余文字、代码围栏、Markdown格式、礼貌用语！
"""

@dataclass
class StressYamlCase:
    """压测测试用例生成结果"""
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

# curl解析
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

# 调用DeepSeek生成压测用例
def _call_deepseek_stress(user_message: str) -> StressYamlCase:
    client = _get_deepseek()
    try:
        resp = client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": STRESS_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
        )
        raw = resp.choices[0].message.content
        return _parse_stress_raw_output(raw, model="deepseek-v4-flash")
    except AuthenticationError:
        return StressYamlCase(success=False, error="认证失败：请检查 API_KEY 是否有效")
    except RateLimitError:
        return StressYamlCase(success=False, error="限流/欠费：请检查账户余额或稍后重试")
    except APIError as e:
        return StressYamlCase(success=False, error=f"API 错误: {e}")
    except Exception as e:
        return StressYamlCase(success=False, error=f"未知错误: {e}")

# 解析AI输出
def _parse_stress_raw_output(raw: str, model: str = "") -> StressYamlCase:
    if not raw or not raw.strip():
        return StressYamlCase(success=False, error="AI 返回为空", model=model)

    text = raw.strip()
    lines = text.split("\n")
    yaml_start = None
    summary_idx = None

    # 定位YAML起始行
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "case_common:":
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

    if yaml_start is None:
        summary = lines[0].strip()
        yaml_body = "\n".join(lines[1:]).strip()
    else:
        summary = lines[summary_idx].strip() if summary_idx is not None else "stress_auto_case"
        yaml_body = "\n".join(lines[yaml_start:]).strip()

    # 清理YAML尾部
    yaml_body = _trim_stress_yaml_garbage(yaml_body)
    return StressYamlCase(
        success=True,
        yaml=f"{summary}\n\n{yaml_body}",
        summary=summary,
        yaml_body=yaml_body,
        model=model,
    )

# 清理YAML尾部无效内容
def _trim_stress_yaml_garbage(yaml_body: str) -> str:
    if not yaml_body:
        return yaml_body
    lines = yaml_body.split("\n")
    end = len(lines)
    for i in range(len(lines)-1, -1, -1):
        stripped = lines[i].strip()
        if not stripped:
            continue
        if (stripped.startswith('#') or
            re.match(r'^[a-z][a-z0-9_]*_\d{2}:\s*$', stripped) or
            stripped == 'case_common:' or
            re.match(r'^\w[\w.-]*:\s', stripped) or
            lines[i].startswith(' ') or
            re.match(r'^[\s]+- ', lines[i])):
            end = i + 1
            break
        end = i
    result = lines[:end]
    while result and not result[-1].strip():
        result.pop()
    return "\n".join(result)

# 公共生成入口
def generate_stress_case(input_type: str, content: str, normalize_assert: bool = False) -> dict:
    """
    生成压测测试用例
    Args:
        input_type: 输入类型 - "curl" / "text"
        content: 输入内容（curl命令/文本描述）
    Returns:
        dict: 生成结果
        :param input_type:
        :param content:
        :param normalize_assert:
    """
    if not content or (isinstance(content, str) and not content.strip()):
        return StressYamlCase(success=False, error="输入内容为空").to_dict()

    if input_type == "curl":
        parsed = _parse_curl(content)
        rich_input = f"接口信息：{parsed}\n原始curl：{content}"
        if normalize_assert:
            rich_input += "\n开启标准化性能断言，统一TPS/RT/错误率模板"
        return _call_deepseek_stress(rich_input).to_dict()
    elif input_type == "text":
        rich_input = content
        if normalize_assert:
            rich_input += "\n标准化压测断言，只保留核心性能指标，去除冗余校验"
        return _call_deepseek_stress(rich_input).to_dict()
    else:
        return StressYamlCase(success=False, error=f"不支持类型{input_type}").to_dict()

# 批量生成
def generate_stress_batch(requests: List[dict]) -> List[dict]:
    results = []
    for i, req in enumerate(requests):
        r = generate_stress_case(req.get("type", "text"), req.get("content", ""))
        r["index"] = i
        results.append(r)
    return results

# 测试示例
# if __name__ == "__main__":
#     # 测试curl输入
#     test_curl = """curl -X POST 'https://wwyd.vip.hnhxzkj.com/api/user/login' \
# -H 'Content-Type: application/json' \
# --data-raw '{"roomId":"12321"}'"""
#     result = generate_stress_case("curl", test_curl)
#     if result["success"]:
#         print("压测测试用例生成成功：")
#         print(result["yaml"])
#     else:
#         print(f"生成失败：{result['error']}")