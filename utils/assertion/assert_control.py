"""
断言类型封装，支持json响应断言、数据库断言
"""
import ast
import json
from typing import Text, Dict, Any, Union
from utils.logging_tool.log_control import INFO
import httpx
import jsonpath as _jsonpath
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

from api_config import AI_Config


def _jp(data, expr):
    """兼容 jsonpath 新旧版本 API：旧版 jsonpath(data, expr) → 新版 jsonpath.search(expr, data)
    新版 search 返回列表（空匹配为 []），旧版返回 False/列表。此处做完全兼容。"""
    result = _jsonpath.search(expr, data)
    if not result:
        return False
    return result
from utils.other_tools.models import AssertMethod
from utils.logging_tool.log_control import ERROR, WARNING
from utils.read_files_tools.regular_control import cache_regular
from utils.other_tools.models import load_module_functions
from utils.assertion import assert_type
from utils.other_tools.exceptions import JsonpathExtractionFailed, SqlNotFound, AssertTypeError
from utils import config
# 创建不验证SSL证书的httpx客户端（⚠️仅用于开发环境，生产环境禁止使用）
_http_client = httpx.Client(verify=False)
# 接入AI接口 -- DeepSeek
client = OpenAI(
    api_key=AI_Config.API_KEY,
    base_url=AI_Config.BASE_URL,
    http_client=_http_client  # 禁用SSL验证
)

class AssertUtil:

    def __init__(self, assert_data, sql_data, request_data, response_data, status_code):

        self.response_data = response_data
        self.request_data = request_data
        self.sql_data = sql_data
        self.assert_data = assert_data
        self.sql_switch = config.mysql_db.switch
        self.status_code = status_code

    @staticmethod
    def literal_eval(attr):
        return ast.literal_eval(cache_regular(str(attr)))

    @property
    def get_assert_data(self):
        assert self.assert_data is not None, (
                "'%s' should either include a `assert_data` attribute, "
                % self.__class__.__name__
        )
        return ast.literal_eval(cache_regular(str(self.assert_data)))

    # 常用断言类型别名，兼容 AI 生成 YAML 中使用的符号形式
    _TYPE_ALIASES: Dict[str, str] = {
        "!=": "not_eq",
        "<": "lt",
        "<=": "le",
        ">": "gt",
        ">=": "ge",
    }

    @property
    def get_type(self):
        assert 'type' in self.get_assert_data.keys(), (
            " 断言数据: '%s' 中缺少 `type` 属性 " % self.get_assert_data
        )

        # 兼容 AI 生成的 YAML 使用符号形式（如 !=）
        _type = self.get_assert_data.get("type")
        _type = self._TYPE_ALIASES.get(_type, _type)
        name = AssertMethod(_type).name
        return name

    @staticmethod
    def _coerce_value(value: Any) -> Any:
        """将字符串尽可能转为数值，解决 YAML '0' vs API 返回值 0 的类型不匹配"""
        if isinstance(value, str):
            try:
                if '.' in value:
                    return float(value)
                return int(value)
            except ValueError:
                pass
        return value

    @property
    def get_value(self):
        assert 'value' in self.get_assert_data.keys(), (
            " 断言数据: '%s' 中缺少 `value` 属性 " % self.get_assert_data
        )
        return self._coerce_value(self.get_assert_data.get("value"))

    @property
    def get_jsonpath(self):
        assert 'jsonpath' in self.get_assert_data.keys(), (
            " 断言数据: '%s' 中缺少 `jsonpath` 属性 " % self.get_assert_data
        )
        return self.get_assert_data.get("jsonpath")

    @property
    def get_assert_type(self):
        assert 'AssertType' in self.get_assert_data.keys(), (
            " 断言数据: '%s' 中缺少 `AssertType` 属性 " % self.get_assert_data
        )
        return self.get_assert_data.get("AssertType")

    @property
    def get_message(self):
        """
        获取断言描述，如果未填写，则返回 `None`
        :return:
        """
        return self.get_assert_data.get("message", None)

    @property
    def get_sql_data(self):

        # 判断数据库开关为开启，并需要数据库断言的情况下，未编写sql，则抛异常
        if self.sql_switch_handle:
            assert self.sql_data != {'sql': None}, (
                "请在用例中添加您要查询的SQL语句。"
            )

        # 处理 mysql查询出来的数据类型如果是bytes类型，转换成str类型
        if isinstance(self.sql_data, bytes):
            return self.sql_data.decode('utf=8')

        sql_data = _jp(self.sql_data, self.get_value)
        assert sql_data is not False, (
            f"数据库断言数据提取失败，提取对象: {self.sql_data} , 当前语法: {self.get_value}"
        )
        if len(sql_data) > 1:
            return sql_data
        return sql_data[0]

    @staticmethod
    def functions_mapping():
        return load_module_functions(assert_type)

    @staticmethod
    def _safe_json(data: str) -> Any:
        """安全解析 JSON：空响应 / 非 JSON 返回 {}，避免 json.loads('') 崩溃"""
        if not data or not isinstance(data, str) or not data.strip():
            return {}
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            WARNING.logger.warning(f"响应非 JSON，原始内容(前200字符): {str(data)[:200]}")
            return {}

    @property
    def get_response_data(self):
        return self._safe_json(self.response_data)

    @property
    def sql_switch_handle(self):
        """
        判断数据库开关，如果未开启，则打印断言部分的数据
        :return:
        """
        if self.sql_switch is False:
            WARNING.logger.warning(
                "检测到数据库状态为关闭状态，程序已为您跳过此断言，断言值:%s" % self.get_assert_data
            )
        return self.sql_switch

    def _assert(self, check_value: Any, expect_value: Any, message: Text = ""):

        self.functions_mapping()[self.get_type](check_value, expect_value, str(message))

    @property
    def _assert_resp_data(self):
        resp_data = _jp(self.get_response_data, self.get_jsonpath)
        assert resp_data is not False, (
            f"jsonpath数据提取失败，提取对象: {self.get_response_data} , 当前语法: {self.get_jsonpath}"
        )
        if len(resp_data) > 1:
            return resp_data
        return resp_data[0]

    @property
    def _assert_request_data(self):
        req_data = _jp(self.request_data, self.get_jsonpath)
        assert req_data is not False, (
            f"jsonpath数据提取失败，提取对象: {self.request_data} , 当前语法: {self.get_jsonpath}"
        )
        if len(req_data) > 1:
            return req_data
        return req_data[0]

    def assert_type_handle(self):
        # 判断请求参数数据库断言
        if self.get_assert_type == "R_SQL":
            self._assert(self._assert_request_data, self.get_sql_data, self.get_message)

        # 判断请求参数为响应数据库断言
        elif self.get_assert_type == "SQL" or self.get_assert_type == "D_SQL":
            self._assert(self._assert_resp_data, self.get_sql_data, self.get_message)

        # 判断非数据库断言类型
        elif self.get_assert_type is None:
            self._assert(self._assert_resp_data, self.get_value, self.get_message)
        else:
            raise AssertTypeError("断言失败，目前只支持数据库断言和响应断言")


class Assert(AssertUtil):

    def assert_data_list(self):
        assert_list = []
        ad = self.get_assert_data
        if not isinstance(ad, dict):
            return assert_list
        for k, v in ad.items():
            if k == "status_code":
                assert self.status_code == v, "响应状态码断言失败"
            else:
                assert_list.append(v)
        return assert_list

    def assert_type_handle(self):
        for i in self.assert_data_list():
            self.assert_data = i
            super().assert_type_handle()

class AI_Assert(AssertUtil):

    def __init__(self):
        pass

    @staticmethod
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
            if '"原因"' in line:
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

    """AI 断言：将请求/响应/场景描述发送给 AI 进行语义级判断"""
    def ai_handle(self, response, assert_desc):
        # 1. 调用 DeepSeek/DashScope API，传入：
        #    - in_data['detail']     场景描述
        #    - in_data['ai_assert_detail']  AI断言说明
        #    - request body          请求体
        #    - response body         响应体
        #    - status_code           状态码
        #
        # 2. prompt 模板：
        #    "请判断以下API测试是否通过，返回JSON: {passed: bool, reason: str}"
        #
        # 3. 解析 AI 返回，passed=False 时 raise AssertionError(reason)
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
            INFO.logger.info(f"[AI断言] 开始 | 场景: {assert_desc[:60]}")
            completion = client.chat.completions.create(
                model="deepseek-v4-flash",
                messages=messages,
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            raw_result = completion.choices[0].message.content or ""
            # 打印 AI 原始返回（便于调试）
            print(f"    [AI断言原始返回]: {raw_result}")

            # 解析 JSON
            try:
                result_json = json.loads(raw_result)
            except json.JSONDecodeError:
                # JSON 解析失败，尝试修复

                print(f"    [警告] JSON解析失败，尝试自动修复...")
                repaired = self.repair_json_quotes(raw_result)
                print(f"    [修复后]: {repaired}")
                result_json = json.loads(repaired)

            if "断言结果" not in result_json:
                return "不通过", f"AI返回格式错误，缺少'断言结果'字段。原始返回: {raw_result}"

            status = result_json["断言结果"]
            reason = result_json.get("原因", "未提供原因")
            if status == "通过":
                INFO.logger.info(f"[AI断言] 通过 | 场景: {assert_desc[:50]}... | 原因: {reason}")
                return "通过", reason
            else:
                INFO.logger.warning(f"[AI断言] 不通过 | 场景: {assert_desc[:50]}... | 原因: {reason}")
                return "不通过", reason

        except json.JSONDecodeError as e:
            return "不通过", f"AI返回JSON解析失败: {str(e)}, 原始返回: {raw_result}"
        except Exception as e:
            return "不通过", f"断言过程中出现错误: {str(e)}"