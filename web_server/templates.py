# -*- coding: utf-8 -*-
"""pytest conftest / 测试文件模板"""
import os

# 从独立模板文件加载 conftest 代码（避免内嵌字符串转义问题）
_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "_conftest_template.py")
with open(_TEMPLATE_PATH, "r", encoding="utf-8") as _f:
    CONFTEST_CODE = _f.read()


def make_test_code(case_ids, common, yaml_stem, file_name):
    """生成 pytest 测试文件代码"""
    from datetime import datetime
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    class_title = "".join(w.capitalize() for w in yaml_stem.split("_")) if yaml_stem else "AutoCase"
    func_title = yaml_stem
    epic = common.get("allureEpic", "自动生成")
    feature = common.get("allureFeature", "自动生成")
    story = common.get("allureStory", "自动生成")
    return f'''#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time   : {now_str}


import allure
import pytest
from utils.read_files_tools.get_yaml_data_analysis import GetTestCase
from utils.assertion.assert_control import Assert
from utils.requests_tool.request_control import RequestControl
from utils.read_files_tools.regular_control import regular
from utils.requests_tool.teardown_control import TearDownHandler


case_id = {case_ids}
TestData = GetTestCase.case_data(case_id)
re_data = regular(str(TestData))


@allure.epic("{epic}")
@allure.feature("{feature}")
class Test{class_title}:

    @allure.story("{story}")
    @pytest.mark.parametrize('in_data', eval(re_data), ids=[i['detail'] for i in TestData])
    def test_{func_title}(self, in_data):
        """
        :param :
        :return:
        """
        res = RequestControl(in_data).http_request()
        TearDownHandler(res).teardown_handle()
        Assert(assert_data=in_data['assert_data'],
               sql_data=res.sql_data,
               request_data=res.body,
               response_data=res.response_data,
               status_code=res.status_code).assert_type_handle()


if __name__ == '__main__':
    pytest.main(['{file_name}', '-s', '-W', 'ignore:Module already imported:pytest.PytestWarning'])
'''
