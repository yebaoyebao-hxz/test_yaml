import json
import os
from typing import Dict
from urllib.parse import urlparse

import jsonpath as _jsonpath


def _jp(data, expr):
    """兼容 jsonpath 新旧版本 API。新版 search 返回列表（空匹配为 []），旧版返回 False/列表。"""
    result = _jsonpath.search(expr, data)
    if not result:
        return False
    return result
from ruamel.yaml import YAML

from common.setting import ensure_path


class SwaggerForYaml:
    def __init__(self):
        self._data = self.get_swagger_json()

    @classmethod
    def get_swagger_json(cls):
        """获取 swagger json 数据，文件不存在返回 None"""
        try:
            with open('./file/test_OpenAPI.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return None

    # ========== Excel 回退方案 ==========

    @classmethod
    def read_excel_cases(cls):
        """从 Excel 读取用例数据"""
        import xlrd
        excel_path = ensure_path("\\data\\接口用例数据.xls")
        book = xlrd.open_workbook(excel_path)
        cases = {}
        for sheet_name in book.sheet_names():
            sheet = book.sheet_by_name(sheet_name)
            col_headers = [str(h).strip() for h in sheet.row_values(0)]
            sheet_cases = []
            for r in range(1, sheet.nrows):
                row = sheet.row_values(r)
                case = {}
                for i, h in enumerate(col_headers):
                    case[h] = str(row[i]) if i < len(row) and row[i] != '' else ''
                sheet_cases.append(case)
            cases[sheet_name] = sheet_cases
        return cases

    @classmethod
    def _parse_json_safe(cls, text):
        """安全解析 JSON，失败返回空 dict"""
        if not text or text.strip() == '':
            return {}
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return {}

    @classmethod
    def _get_excel_request_type(cls, headers_dict):
        """从 Content-Type 判断 requestType"""
        ct = headers_dict.get('Content-Type', '')
        if 'application/json' in ct:
            return 'json'
        elif 'application/x-www-form-urlencoded' in ct:
            return 'data'
        elif 'multipart/form-data' in ct:
            return 'data'
        elif 'application/octet-stream' in ct:
            return 'file'
        return 'json'

    @classmethod
    def _parse_assert(cls, assert_text):
        """Excel 断言列 -> YAML assert 结构"""
        assert_dict = cls._parse_json_safe(assert_text)
        if not assert_dict:
            return {"status_code": 200}
        result = {}
        for key, value in assert_dict.items():
            result[key] = {
                "jsonpath": f"$.{key}",
                "type": "==",
                "value": value,
                "AssertType": None
            }
        return result

    @classmethod
    def _parse_extract(cls, extract_text):
        """Excel 读取字段列 -> YAML extract 结构"""
        if not extract_text or extract_text.strip() == '':
            return None
        fields = [f.strip() for f in extract_text.split(',') if f.strip()]
        result = {}
        for field in fields:
            result[field] = {"jsonpath": f"$.data.{field}"}
        return result

    @classmethod
    def _extract_url_info(cls, full_url):
        """从完整 URL 提取 path"""
        if not full_url:
            return "/"
        try:
            parsed = urlparse(full_url)
            return parsed.path or '/'
        except Exception:
            return "/"

    def _write_from_excel(self):
        """从 Excel 生成 YAML 用例文件"""
        excel_data = self.read_excel_cases()
        allure_epic = "\u63a5\u53e3\u81ea\u52a8\u5316\u6d4b\u8bd5"

        for sheet_name, cases in excel_data.items():
            allure_feature = f"{sheet_name}\u6a21\u5757"
            for idx, case in enumerate(cases, 1):
                case_name = case.get('\u7528\u4f8b\u540d\u79f0', f'case_{idx}')
                full_url = case.get('\u8bf7\u6c42\u5730\u5740', '')
                path = self._extract_url_info(full_url)
                method = case.get('\u8bf7\u6c42\u65b9\u5f0f', 'GET').strip().upper()

                headers_dict = self._parse_json_safe(case.get('\u8bf7\u6c42\u5934', '{}'))
                request_type = self._get_excel_request_type(headers_dict)
                data = self._parse_json_safe(case.get('\u8bf7\u6c42\u53c2\u6570', '{}'))
                assert_info = self._parse_assert(case.get('\u65ad\u8a00\u4fe1\u606f', ''))
                extract_info = self._parse_extract(case.get('\u8bfb\u53d6\u5b57\u6bb5', ''))

                case_id = f"{sheet_name}_{idx:02d}"

                yaml_data = {
                    "case_common": {
                        "allureEpic": allure_epic,
                        "allureFeature": allure_feature,
                        "allureStory": case_name
                    },
                    case_id: {
                        "host": "${{host()}}",
                        "url": path,
                        "method": method,
                        "detail": f"\u6d4b\u8bd5{case_name}",
                        "headers": headers_dict,
                        "requestType": request_type,
                        "is_run": None,
                        "data": data,
                        "dependence_case": False,
                        "dependence_case_data": None,
                        "assert": assert_info,
                        "sql": None,
                        "extract": extract_info
                    }
                }

                self.yaml_cases(yaml_data, file_path=f"/{sheet_name}")

    # ========== 通用 YAML 写入 ==========

    @classmethod
    def yaml_cases(cls, data: Dict, file_path: str) -> None:
        _file_path = ensure_path("\\data\\" + file_path[1:].replace("/", os.sep) + '.yaml')
        _file = _file_path.split(os.sep)[:-1]
        _dir_path = ''
        for i in _file:
            _dir_path += i + os.sep
        try:
            os.makedirs(_dir_path)
        except FileExistsError:
            ...
        yaml_writer = YAML()
        with open(_file_path, "a", encoding="utf-8") as file:
            yaml_writer.dump(data, file)
            file.write('\n')

    # ========== 总入口 ==========

    def write_yaml_handler(self):
        if self._data is not None:
            self._write_from_swagger()
        else:
            self._write_from_excel()

    # ========== Swagger 路径（原有逻辑） ==========

    def _write_from_swagger(self):
        _api_data = self._data['paths']
        for key, value in _api_data.items():
            for k, v in value.items():
                yaml_data = {
                    "case_common": {"allureEpic": self.get_allure_epic(), "allureFeature": self.get_allure_feature(v),
                                    "allureStory": self.get_allure_story(v)},
                    self.get_case_id(key): {
                        "host": "${{host()}}", "url": key, "method": k, "detail": self.get_detail(v),
                        "headers": self.get_headers(v), "requestType": self.get_request_type(v),
                        "is_run": None, "data": self.get_case_data(v), "dependence_case": False,
                        "assert": {"status_code": 200}, "sql": None}}
                self.yaml_cases(yaml_data, file_path=key)

    def get_allure_epic(self):
        return self._data['info']['title']

    @classmethod
    def get_allure_feature(cls, value):
        return str(value['tags'])

    @classmethod
    def get_allure_story(cls, value):
        return value['summary']

    @classmethod
    def get_case_id(cls, value):
        return "01" + value.replace("/", "_")

    @classmethod
    def get_detail(cls, value):
        return "test" + value['summary']

    @classmethod
    def get_request_type(cls, value):
        if _jp(data=value, expr="$.parameters") is not False:
            _parameters = value['parameters']
            if _parameters[0]['in'] == 'query':
                return "params"
            else:
                return "data"

    @classmethod
    def get_case_data(cls, value):
        _dict = {}
        if _jp(data=value, expr="$.parameters") is not False:
            _parameters = value['parameters']
            for i in _parameters:
                if i['in'] == 'header':
                    ...
                else:
                    _dict[i['name']] = None
        else:
            return None
        return _dict

    @classmethod
    def get_headers(cls, value):
        _headers = {}
        if _jp(data=value, expr="$.consumes") is not False:
            _headers = {"Content-Type": value['consumes'][0]}
        if _jp(data=value, expr="$.parameters") is not False:
            for i in value['parameters']:
                if i['in'] == 'header':
                    _headers[i['name']] = None
        else:
            _headers = None
        return _headers


if __name__ == '__main__':
    SwaggerForYaml().write_yaml_handler()
