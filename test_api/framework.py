import json
import pytest
import requests
import xlrd
from xToolkit import xfile
from jsonpath import JSONPath

_token = None
_session = requests.Session()
_extracted = {}  # 用于存放提取的参数
_game_id = None

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
    # 3) 断言校验
    check_result(res_json, assert_info, case_name)

    return res_json


# ============================================================
#  pytest 用例生成
# ============================================================
_excel_path = r"/data\接口用例数据.xls"
ALL_CASES = load_excel_cases(_excel_path, sheet_name="兔子")

@pytest.mark.parametrize("case_info", ALL_CASES)
def test_execute(case_info):
    """pytest 会为每一条 Excel 用例生成一个测试函数。"""
    execute_case(case_info)


# ============================================================
#  独立调试入口
# ============================================================
if __name__ == "__main__":
    cases = load_excel_cases(_excel_path, sheet_name="兔子")
    print(f"共加载 {len(cases)} 条用例：")
    for i, c in enumerate(cases, 1):
        print(f"  {i}. {c.get('用例名称', '?')}")

    print("\n开始执行第一条用例...\n")
    execute_case(cases[0])
