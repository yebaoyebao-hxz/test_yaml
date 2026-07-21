# -*- coding: utf-8 -*-
"""手工功能测试用例生成器。

根据产品文字描述 / 页面截图生成标准化功能测试 YAML 用例。
- 纯文字：DeepSeek 文本模型
- 单张截图：通义千问 VL 视觉模型
- 多张截图+文字混合：通义千问 VL

参考兄弟模块：smoke_test_case_generator.py / stress_test_case_generator.py
"""

import base64
import re
import os
import argparse
import warnings
from dataclasses import dataclass
from typing import Optional, List

import httpx
import yaml
from openai import OpenAI
from openai import AuthenticationError, RateLimitError

# 统一使用 api_config.py（与 smoke / stress 模块保持一致）
from api_config import AI_Config

# 忽略 SSL 证书警告
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

# ============================================================
# 系统提示词
# ============================================================

SYSTEM_PROMPT = """你是专业手工功能测试工程师，根据用户提供的产品文字描述/页面截图生成标准化功能测试YAML用例。
## 一、输入类型
1. 纯文字：产品模块、页面、按钮、交互、业务流程描述
2. 截图：网页/APP界面截图，识别按钮、输入框、弹窗、分页、弹窗、权限控件、提示文案
## 二、统一YAML固定模板
case_base:
  module: [所属模块，如用户中心/商城首页/游戏背包]
  function_point: [当前功能名称]
  test_env: 测试环境
  priority: P0/P1/P2  # P0核心流程，P1次要功能，P2边缘交互
func_case_01:
  case_name: 正常流程-XX操作
  test_type: 正常场景
  precondition: 测试前置条件（账号、页面、数据准备）
  test_data: 测试使用的数据（账号、文本、数字、文件等）
  operate_steps:
    1. 步骤1
    2. 步骤2
    3. 步骤3
  expect_result: 每一步对应的正确页面/弹窗/文案/数据结果
  remark: 无特殊备注
func_case_02:
  case_name: 异常场景-空输入
  test_type: 异常校验
  precondition: 
  test_data:
  operate_steps:
    1.
  expect_result:
  remark:
## 三、强制生成规则
1. 用例命名规则：func_case_两位数字，01正常流程，02异常输入，03边界值，04重复操作，05权限校验，06兼容场景，07弹窗校验，08网络异常
2. 每个功能至少生成8条独立用例，覆盖全场景
3. test_type固定分类：正常场景/异常校验/边界值/重复操作/权限验证/兼容测试/弱网测试
4. priority规则：主业务流程P0，辅助功能P1，边角交互P2
5. operate_steps：步骤分点清晰，一步一操作，不能合并
6. expect_result：精确描述页面展示、弹窗提示、文字提示、数据变化、按钮状态
7. test_data：填写测试用到账号、文字、数字、图片、空值、超长字符等
8. precondition：明确账号权限、页面位置、预置数据
## 四、输出强制规范
1. 第一行仅一句话：XX功能测试用例_共X条
2. 从第二行开始仅输出纯YAML文本
3. 禁止markdown代码块、禁止解释文字、禁止开场白结束语
4. 缩进统一使用2空格，字符串无需多余转义，空值填''
5. 禁止出现host、url、method、headers、接口、请求等自动化接口相关词汇
"""

# ============================================================
# 数据实体
# ============================================================

@dataclass
class FuncCase:
    success: bool
    yaml: Optional[str] = None
    summary: Optional[str] = None
    yaml_body: Optional[str] = None
    error: Optional[str] = None

# ============================================================
# AI 客户端缓存（与 smoke / stress 模块同模式）
# ============================================================

_deepseek_client = None
_dashscope_client = None

def _get_deepseek() -> OpenAI:
    global _deepseek_client
    if not _deepseek_client:
        _deepseek_client = OpenAI(
            api_key=AI_Config.API_KEY,
            base_url=AI_Config.BASE_URL,
            http_client=httpx.Client(verify=False),
        )
    return _deepseek_client

def _get_dashscope() -> OpenAI:
    global _dashscope_client
    if not _dashscope_client:
        _dashscope_client = OpenAI(
            api_key=AI_Config.DASHSCOPE_API_KEY,
            base_url=AI_Config.DASHSCOPE_BASE_URL,
            http_client=httpx.Client(verify=False),
        )
    return _dashscope_client

# ============================================================
# 图片数据 URI 构造
# ============================================================

def _img_to_data_uri(path_or_url: str) -> str:
    """统一处理：本地文件路径 → data:image/png;base64,...，URL 则原样返回。"""
    if path_or_url.startswith(("http://", "https://", "data:")):
        return path_or_url
    if os.path.isfile(path_or_url):
        with open(path_or_url, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return f"data:image/png;base64,{b64}"
    # 兜底：当作 base64 字面量
    return f"data:image/png;base64,{path_or_url}"

# ============================================================
# YAML 清洗与解析
# ============================================================

# 扩展的中文/全角字符区间（基础汉字 + 扩展区 + 全角标点/片假名）
_RE_CJK = re.compile(r'[\u2E80-\u2EFF\u3000-\u303F\u31C0-\u31EF'
                      r'\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF'
                      r'\U00020000-\U0002A6DF\U0002F800-\U0002FA1F]')

def _is_yaml_line(line: str) -> bool:
    """判断一行是否属于合法 YAML 内容（排除 AI 废话）。"""
    stripped = line.strip()
    if not stripped or stripped.startswith('#'):
        return True
    # 顶层 key：case_base / func_case_NN
    if stripped == "case_base:" or re.match(r'^func_case_\d{2}:\s*$', stripped):
        return True
    # 缩进 key：缩进 + 名称:
    if re.match(r'^\s+\w[\w.-]*\s*:', line):
        return True
    # 列表项：缩进 + 数字.
    if re.match(r'^\s+\d+\.', line):
        return True
    # 顶层不带缩进的非 key 行 → 可能是 AI 废话（如中文说明）
    if not line.startswith(' ') and _RE_CJK.search(stripped):
        return False
    return line.startswith(' ')

def _trim_tail_garbage(raw_yaml: str) -> str:
    """从末尾逐行剔除 AI 多余输出，直到能通过 yaml.safe_load。"""
    if not raw_yaml:
        return ""
    lines = raw_yaml.split("\n")
    # 找到最后一个合法 YAML 行
    end = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() and _is_yaml_line(lines[i]):
            end = i + 1
            break
    # 保留非空行（去掉中间的 AI 废话行）
    kept = [l for l in lines[:end] if l.strip()]
    # 反向验证：逐行削底直到 YAML 解析成功
    trial = "\n".join(kept)
    for _ in range(20):
        if not trial.strip():
            break
        try:
            yaml.safe_load(trial)
            break
        except Exception:
            parts = trial.rsplit("\n", 1)
            trial = parts[0] if len(parts) > 1 else ""
    return trial

def _parse_raw_output(raw: str) -> FuncCase:
    """从 AI 返回的原始文本中提取 YAML 正文 + 标题摘要。"""
    if not raw or not raw.strip():
        return FuncCase(success=False, error="AI返回内容为空")
    lines = raw.strip().split("\n")
    yaml_start = None
    summary = "功能测试用例"
    for idx, line in enumerate(lines):
        s = line.strip()
        if s == "case_base:" or re.match(r'^func_case_\d{2}:\s*$', s):
            yaml_start = idx
            for j in range(idx - 1, -1, -1):
                prev = lines[j].strip()
                skip_words = ("以下是", "根据", "好的", "生成", "```")
                if prev and not prev.startswith(skip_words):
                    summary = prev
                break
            break
    if yaml_start is None:
        summary = lines[0].strip()
        yaml_body = "\n".join(lines[1:])
    else:
        yaml_body = "\n".join(lines[yaml_start:])
    yaml_body = _trim_tail_garbage(yaml_body).strip()
    full_yaml = f"{summary}\n{yaml_body}"
    return FuncCase(
        success=True,
        yaml=full_yaml,
        summary=summary,
        yaml_body=yaml_body
    )

# ============================================================
# 生成入口
# ============================================================

def generate_text_func(text: str) -> FuncCase:
    """纯文字/功能描述 → DeepSeek → 功能 YAML 用例。"""
    client = _get_deepseek()
    try:
        resp = client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ],
            temperature=0.3
        )
        return _parse_raw_output(resp.choices[0].message.content)
    except AuthenticationError:
        return FuncCase(success=False, error="DeepSeek密钥认证失败")
    except RateLimitError:
        return FuncCase(success=False, error="模型限流或余额不足")
    except Exception as e:
        return FuncCase(success=False, error=f"生成异常：{str(e)}")

def generate_image_func(img_path: str, desc: str = "") -> FuncCase:
    """单张截图 → 通义千问 VL → 功能 YAML 用例。"""
    client = _get_dashscope()
    img_url = _img_to_data_uri(img_path)
    user_text = "识别页面截图，生成完整手工功能测试用例"
    if desc:
        user_text += f"\n附加功能描述：{desc}"
    try:
        resp = client.chat.completions.create(
            model="qwen-vl-plus",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": img_url}},
                        {"type": "text", "text": user_text}
                    ]
                }
            ],
            temperature=0.3
        )
        return _parse_raw_output(resp.choices[0].message.content)
    except AuthenticationError:
        return FuncCase(success=False, error="DashScope密钥错误")
    except Exception as e:
        return FuncCase(success=False, error=f"图片解析失败：{str(e)}")

def generate_mixed_func(text: str, img_list: List[str]) -> FuncCase:
    """多张截图 + 文字 → 通义千问 VL → 功能 YAML 用例。"""
    client = _get_dashscope()
    content_arr = [_img_to_data_uri(path) for path in img_list]
    content_arr = [{"type": "image_url", "image_url": {"url": u}} for u in content_arr]
    content_arr.append({
        "type": "text",
        "text": f"产品功能描述：{text}，结合多张页面截图生成手工功能测试用例"
    })
    try:
        resp = client.chat.completions.create(
            model="qwen-vl-plus",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content_arr}
            ],
            temperature=0.3
        )
        return _parse_raw_output(resp.choices[0].message.content)
    except Exception as e:
        return FuncCase(success=False, error=f"混合生成失败：{str(e)}")

# ============================================================
# 文件保存
# ============================================================

def save_case(result: FuncCase, output_file: str):
    """将生成成功的用例写入 YAML 文件。"""
    if not result.success:
        print("生成失败，无法保存文件")
        return
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(result.yaml)
    print(f"✅ 用例文件已输出至：{output_file}")
    print(f"📋 用例标题：{result.summary}")

# ============================================================
# 命令行入口
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="手工功能测试用例生成工具（支持页面截图/文字描述，无接口内容）"
    )
    parser.add_argument("--text", "-t", type=str, help="产品功能、页面、业务流程文字描述")
    parser.add_argument("--image", "-i", action="append", help="页面截图路径，可多次传入多张图片")
    parser.add_argument("--output", "-o", default="./func_case.yaml", help="输出YAML文件路径")
    args = parser.parse_args()

    if not args.text and not args.image:
        print("错误：必须传入 --text 功能描述 或 --image 截图文件")
        exit(1)

    if args.text and not args.image:
        res = generate_text_func(args.text)
    elif args.image and not args.text:
        res = generate_image_func(args.image[0])
    else:
        res = generate_mixed_func(args.text, args.image)

    if not res.success:
        print(f"❌ 生成失败：{res.error}")
        exit(1)
    save_case(res, args.output)
    print("\n======= 生成用例预览 =======")
    print(res.yaml)
