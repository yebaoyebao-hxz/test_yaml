import datetime
import os
from utils.read_files_tools.yaml_control import GetYamlData
from common.setting import ensure_path
from utils.other_tools.exceptions import ValueNotFoundError
from utils.requests_tool.set_current_request_cache import SetCurrentRequestCache


def write_case(case_path, page):
    """ 写入用例数据 """
    with open(case_path, 'w', encoding="utf-8") as file:
        file.write(page)


def write_testcase_file(*, allure_epic, allure_feature, class_title,
                        func_title, case_path, case_ids, file_name, allure_story, reason):
    """

        :param reason:
        :param allure_story:
        :param file_name: 文件名称
        :param allure_epic: 项目名称
        :param allure_feature: 模块名称
        :param class_title: 类名称
        :param func_title: 函数名称
        :param case_path: case 路径
        :param case_ids: 用例ID
        :return:
        """
    conf_data = GetYamlData(ensure_path("\\common\\config.yaml")).get_yaml_data()
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    real_time_update_test_cases = conf_data['real_time_update_test_cases']

    page = f'''#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time   : {now}


import json
import allure
import pytest
from utils.read_files_tools.get_yaml_data_analysis import GetTestCase
from utils.assertion.assert_control import Assert, AI_Assert
from utils.requests_tool.request_control import RequestControl
from utils.read_files_tools.regular_control import regular
from utils.requests_tool.teardown_control import TearDownHandler


case_id = {case_ids}
TestData = GetTestCase.case_data(case_id)
re_data = regular(str(TestData))
re_data = cache_regular(re_data)


@allure.epic("{allure_epic}")
@allure.feature("{allure_feature}")
class Test{class_title}:

    @allure.story("{allure_story}")
    @pytest.mark.parametrize('in_data', eval(re_data), ids=[i['detail'] for i in TestData])
    def test_{func_title}(self, in_data, case_skip):
        """
        :param :
        :return:
        """
        res = RequestControl(in_data).http_request()
        # ----- 新增：从响应中提取数据写入缓存 -----
        SetCurrentRequestCache(
            current_request_set_cache=in_data.get('current_request_set_cache'),
            request_data=res.body,
            response_data=res.response_data
        ).set_caches_main()
        # -----------------------------------------
        TearDownHandler(res).teardown_handle()
        Assert(assert_data=in_data['assert_data'],
               sql_data=res.sql_data,
               request_data=res.body,
               response_data=res.response_data,
               status_code=res.status_code).assert_type_handle()

        # AI 语义断言
        if in_data.get('ai_assert'):
            response_json = json.loads(res.response_data) if res.response_data else None
            assert_desc = in_data.get('ai_assert_detail') or in_data.get('detail', '')
            status, reason = AI_Assert(
                assert_data=in_data.get('assert_data', {{}}),
                sql_data=res.sql_data,
                request_data=res.body,
                response_data=res.response_data,
                status_code=res.status_code
            ).ai_handle(response_json, assert_desc)
            assert status == '通过', f"AI断言不通过: {reason}"


if __name__ == '__main__':
    pytest.main(['{file_name}', '-s', '-W', 'ignore:Module already imported:pytest.PytestWarning'])
'''
    if real_time_update_test_cases:
        write_case(case_path=case_path, page=page)
    elif real_time_update_test_cases is False:
        if not os.path.exists(case_path):
            write_case(case_path=case_path, page=page)
    else:
        raise ValueNotFoundError("real_time_update_test_cases 配置不正确，只能配置 True 或者 False")

