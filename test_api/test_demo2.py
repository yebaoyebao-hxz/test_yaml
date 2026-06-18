import json
import os

import httpx
import pytest
import requests
import xlrd
from openai import OpenAI
from jsonpath import JSONPath
from openai.types.chat import ChatCompletionMessageParam
from api_config import AI_Config

# 创建不验证SSL证书的httpx客户端（⚠️仅用于开发环境，生产环境禁止使用）
_http_client = httpx.Client(verify=False)
_token = None
_session = requests.Session()
_extracted = {}  # 用于存放提取的参数
_game_id = None
# 接入AI接口 -- DeepSeek
client = OpenAI(
    api_key=AI_Config.API_KEY,
    base_url=AI_Config.BASE_URL,
    http_client=_http_client  # 禁用SSL验证
)


# ============================================================
#  服务器预热（解决冷启动超时）
# ============================================================
@pytest.fixture(scope="session", autouse=True)
def warmup_server():
    """pytest session 启动时自动发一个预热请求，暖服务器避免前几个用例超时。"""
    print("\n[预热] 正在唤醒服务器...")
    try:
        r = _session.get(
            "https://wwyd.vip.hnhxzkj.com/api/login/send_sms",
            json={"phone": "13224523466"},
            timeout=30,
            verify=False
        )
        print(f"[预热] 服务器已就绪 (status={r.status_code})")
    except Exception as e:
        print(f"[预热] 预热请求失败: {e}")


# ============================================================
#  Excel 数据读取
# ============================================================
def get_data(filename, sheet_name):
    """读取 Excel (.xls) 指定 sheet，返回去掉表头的行数据列表。"""
    book = xlrd.open_workbook(filename)
    sheet = book.sheet_by_name(sheet_name)
    return [sheet.row_values(i) for i in range(1, sheet.nrows)]


def load_excel_cases(excel_path, sheet_name="兔子"):
    """读取 Excel 指定 sheet，返回字典列表（每行一条用例）。"""
    book = xlrd.open_workbook(excel_path)
    sheet = book.sheet_by_name(sheet_name)
    headers = sheet.row_values(0)
    cases = []
    for r in range(1, sheet.nrows):
        row = sheet.row_values(r)
        cases.append(dict(zip(headers, row)))
    return cases


# ============================================================
#  Token 管理
# ============================================================
def extract_token(res_json, case_name):
    """从响应中提取 token 并写入全局 session。"""
    global _token
    # 优先 $.data.token
    token_list = JSONPath("$.data.token").parse(res_json)
    if not token_list:
        # 兜底 $.data[0].token
        token_list = JSONPath("$.data[0].token").parse(res_json)
    if token_list and token_list[0]:
        token = token_list[0]
        set_auth_token(token)
        print(f"[OK] {case_name}: 成功提取 token")


def set_auth_token(token):
    """把 token 拼成 Bearer xxx 写入 session 请求头。"""
    global _token
    _token = token
    _session.headers["Authorization"] = f"Bearer {_token}"
    print(f"[Token] 已生效: Bearer {_token[:20]}...")


def extract_game_id(res_json, case_name):
    """从响应中提取 game_id，兼容 data.game_id 和直接 game_id"""
    global _game_id
    game_id_list = JSONPath("$.data.game_id").parse(res_json)
    if not game_id_list:
        game_id_list = JSONPath("$.game_id").parse(res_json)
    if game_id_list and game_id_list[0]:
        game_id = game_id_list[0]
        _game_id = game_id
        print(f"[OK] {case_name}: 成功提取 game_id -> {game_id}")
    else:
        print(f"[WARN] {case_name}: 响应中未找到 game_id")


def inject_game_id(params_dict):
    """将全局 _game_id 注入到请求参数中"""
    global _game_id
    if not _game_id:
        return params_dict
    params_dict = dict(params_dict)  # 避免修改原对象
    params_dict["game_id"] = str(_game_id)
    return params_dict


def get_auth_token():
    """返回当前全局 token 值。"""
    return _token


# ============================================================
#  辅助：安全解析 JSON 字符串
# ============================================================
def safe_json_loads(s):
    """把 JSON 字符串转成 dict，空/None 时返回 {}。"""
    if not s or (isinstance(s, str) and s.strip() == ""):
        return {}
    return json.loads(s)


# ============================================================
#  断言校验
# ============================================================
def check_result(res_json, assert_info_str, case_name):
    """
    用 '断言信息' 做校验。
    assert_info 格式为期望的 JSON（字符串），
    取出其中 key 对应的值与响应对比。
    支持嵌套 key，如 "code", "msg", "data" 等。
    """
    if not assert_info_str or (isinstance(assert_info_str, str) and assert_info_str.strip() == ""):
        print(f"[跳过] {case_name}: 断言信息为空")
        return

    expected = safe_json_loads(assert_info_str)
    errors = []

    for key, exp_val in expected.items():
        # 支持 $.key 或直接 key，这里用 JSONPath 解析响应
        result = JSONPath(f"$.{key}").parse(res_json)
        if not result:
            errors.append(f"  响应中找不到 key='{key}'，期望值={exp_val}")
            continue
        actual = result[0]
        if actual != exp_val:
            errors.append(f"  key='{key}': 期望={exp_val}, 实际={actual}")

    if errors:
        err_msg = f"[断言失败] {case_name}\n" + "\n".join(errors)
        print(err_msg)
        pytest.fail(err_msg)
    else:
        print(f"[OK] {case_name}: 断言通过")


# ============================================================
#  参数提取
# ============================================================
def do_extract(res_json, extract_key):
    """
    从响应中按 extract_key（逗号分隔的多个 key，或 jsonpath 表达式）提取值，
    存入全局 _extracted 字典。
    """
    if not extract_key or (isinstance(extract_key, str) and extract_key.strip() == ""):
        return
    # 支持 "token,game_id" 逗号分隔多个 key
    keys = [k.strip() for k in str(extract_key).split(",")]
    for key in keys:
        if not key:
            continue
        # 尝试 jsonpath 风格（$..key）或直接 key
        result = JSONPath(f"$..{key}").parse(res_json)
        if result and result[0] is not None:
            _extracted[key] = result[0]
            print(f"[提取] {key} = {str(result[0])[:30]}")
        else:
            print(f"[提取失败] {key}: 未找到有效值")


# ============================================================
#  用例执行（发送请求 + 提取 + 断言）
# ============================================================
def execute_case(case_info):
    """
    执行一条用例：
      1. 用 session 发送请求（自动带上 Authorization）
      2. 提取参数（如果 Excel 有 '提取参数' 列）
      3. 断言校验（'断言信息' 列）
    """
    case_name = case_info.get("用例名称", "?")
    method = case_info.get("请求方式", "POST").upper()
    url = case_info.get("请求地址", "")
    headers = safe_json_loads(case_info.get("请求头", ""))
    params = safe_json_loads(case_info.get("请求参数", ""))
    assert_info = case_info.get("断言信息", "")
    extract_key = case_info.get("提取参数", "")  # ← 需要 Excel 加此列

    print(f"\n>>> [{method}] {url}")
    print(f"    参数: {params}")

    # 游戏结算用例：自动注入 game_id（Excel params 里可能没有此字段）
    if "结算" in case_name and _game_id:
        params = inject_game_id(params)
        print(f"    [注入] game_id 已补充: {params}")

    # 发送请求（用 _session，自动携带 token）
    # POST/PUT → json=params（请求体）；GET/DELETE → params=params（URL查询参数）
    if method in ("GET", "DELETE"):
        resp = _session.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            timeout=10,
            verify=False
        )
    else:
        resp = _session.request(
            method=method,
            url=url,
            headers=headers,
            json=params,
            timeout=10,
            verify=False
        )
    resp.raise_for_status()
    res_json = resp.json()

    print(f"    响应: {str(res_json)[:100]}")

    # 1) 提取参数
    do_extract(res_json, extract_key)
    extract_token(res_json, case_name)
    extract_game_id(res_json, case_name)
    # 先调用AI断言（如果excel中有“断言信息”列且不为空）
    ai_assert_desc = case_info.get("断言信息", "")
    if ai_assert_desc and str(ai_assert_desc).strip():
        status, reason = ai_assert(res_json, ai_assert_desc)
        if status == "不通过":
            err_msg = f"[断言信息]{case_name}\n  原因:{reason}"
            print(err_msg)
            pytest.fail(err_msg)
        else:
            #  没有就用传统断言
            check_result(res_json, ai_assert_desc, case_name)
    return res_json


# ============================================================
#  pytest 用例生成
# ============================================================
_excel_path = r"E:\yebao\test_yaml\data\接口用例数据.xls"
ALL_CASES = load_excel_cases(_excel_path, sheet_name="兔子")


@pytest.mark.parametrize("case_info", ALL_CASES)
def test_execute(case_info):
    """pytest 会为每一条 Excel 用例生成一个测试函数。"""
    execute_case(case_info)


def repair_json_quotes(json_str: str) -> str:
    """
    修复 JSON 字符串中未转义的引号。
    仅处理 "原因" 字段值内部的未转义引号。
    """
    import re

    # 查找 "原因": "..." 的模式，修复值内部的引号
    # 这个正则匹配 "原因": "开头，然后到下一个未转义的 "}" 或行尾
    # 我们需要更智能的处理

    # 方法：找到 "原因" 字段，然后对其值进行处理
    # 使用更安全的方法：提取 "原因" 的值，转义内部引号

    # 查找 "断言结果" 字段值（通常是简单值，不需要处理）
    # 查找 "原因" 字段值（可能包含未转义引号）

    lines = json_str.split('\n')
    repaired_lines = []

    for line in lines:
        # 检测是否是 "原因" 字段行
        if '"原因"' in line or '"原因"' in line:
            # 尝试修复：找到第一个冒号后的内容
            colon_idx = line.find(':')
            if colon_idx != -1:
                prefix = line[:colon_idx + 1]
                value_part = line[colon_idx + 1:].strip()

                # 如果值是以 " 开头的字符串
                if value_part.startswith('"'):
                    # 找到值的结束位置（最后一个 " 或 ,或 }）
                    # 转义值内部的所有引号（除了开头和结尾的）
                    if value_part.endswith(',') or value_part.endswith('}'):
                        end_char = value_part[-1]
                        value_content = value_part[1:-2]  # 去掉开头的 " 和结尾的 ",
                    else:
                        end_char = ''
                        value_content = value_part[1:-1] if value_part.endswith('"') else value_part[1:]

                    # 转义内部的双引号
                    value_content = value_content.replace('"', '\\"')

                    # 重建行
                    if value_part.endswith(',') or value_part.endswith('}'):
                        line = f'{prefix} "{value_content}{end_char}'
                    else:
                        line = f'{prefix} "{value_content}"'

        repaired_lines.append(line)

    return '\n'.join(repaired_lines)


def ai_assert(response, assert_desc):
    """
    使用 AI 进行智能断言。
    返回: (status: str, reason: str) 元组
    """
    if not response:
        return "不通过", "响应为空，无法断言"

    prompt = f"""
            你作为一名接口测试断言专家，完成以下验证:
            1.接口实际返回数据:
            {json.dumps(response, ensure_ascii=False, indent=2)}

            2.预期响应结果描述: {assert_desc}

            请严格按照以下JSON格式返回（注意：JSON中的字符串值如果包含双引号，必须用反斜杠转义，如 \\"）:
            {{
                "断言结果": "通过",
                "原因": "说明理由"
            }}
            或
            {{
                "断言结果": "不通过",
                "原因": "说明理由"
            }}

            重要提示：原因字段中不要直接使用双引号，请改用单引号或直接描述，避免JSON格式错误。
            """

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": "你是专业的接口测试断言专家。请严格返回有效JSON格式，字符串中的双引号必须转义。"},
        {"role": "user", "content": prompt}
    ]

    raw_result = ""  # 用于保存原始返回，供错误处理使用

    try:
        completion = client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=messages,
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        raw_result = completion.choices[0].message.content or ""

        # 打印 AI 原始返回（便于调试）
        print(f"    [AI断言原始返回]: {raw_result}")

        # 尝试直接解析 JSON
        try:
            result_json = json.loads(raw_result)
        except json.JSONDecodeError:
            # JSON 解析失败，尝试修复
            print(f"    [警告] JSON解析失败，尝试自动修复...")
            repaired = repair_json_quotes(raw_result)
            print(f"    [修复后]: {repaired}")
            result_json = json.loads(repaired)

        # 校验返回格式
        if "断言结果" not in result_json:
            return "不通过", f"AI返回格式错误，缺少'断言结果'字段。原始返回: {raw_result}"

        status = result_json["断言结果"]
        reason = result_json.get("原因", "未提供原因")

        if status == "通过":
            return "通过", reason
        else:
            return "不通过", reason

    except json.JSONDecodeError as e:
        return "不通过", f"AI返回JSON解析失败: {str(e)}, 原始返回: {raw_result}"
    except Exception as e:
        return "不通过", f"断言过程中出现错误: {str(e)}"

# 运行前请安装 pytest test_demo2.py --alluredir=allure-result
# runfile() 是 PyCharm Console 的特殊命令，它直接把参数传给 pytest 但方式可能不对。建议直接在 Terminal 里跑
# 生成测试报告
if __name__ == "__main__":
    pytest.main(["-vs",  # 固定命令
                 "--capture=sys",  # 捕获输出
                 "test_demo2.py",
                 "--clean-alluredir",  # 清除上次数据
                 "--alluredir=allure-result"])
    os.system("allure generate allure-result -o ./report_allure --clean")