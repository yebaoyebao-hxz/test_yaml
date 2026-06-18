#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time   : 2026-06-12 18:59:48


import allure
import pytest
from utils.read_files_tools.get_yaml_data_analysis import GetTestCase
from utils.assertion.assert_control import Assert
from utils.requests_tool.request_control import RequestControl
from utils.read_files_tools.regular_control import regular
from utils.requests_tool.teardown_control import TearDownHandler


case_id = ['兔子_01', '兔子_02', '兔子_03', '兔子_04', '兔子_05', '兔子_06', '兔子_07', '兔子_08', '兔子_09', '兔子_10', '兔子_11', '兔子_12', '兔子_13', '兔子_14', '兔子_15', '兔子_16', '兔子_17', '兔子_18', '兔子_19', '兔子_20', '兔子_21', '兔子_22', '兔子_23', 'case_common_24', '兔子_24', '兔子_25', '兔子_26', '兔子_27', '兔子_28', '兔子_29', '兔子_30', '兔子_31']
TestData = GetTestCase.case_data(case_id)
re_data = regular(str(TestData))


@allure.epic("接口自动化测试")
@allure.feature("兔子模块")
class TestRabbitTest:

    @allure.story("兔子模块接口测试")
    @pytest.mark.parametrize('in_data', eval(re_data), ids=[i['detail'] for i in TestData])
    def test_rabbit_test(self, in_data):
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
    pytest.main(['test_rabbit_test.py', '-s', '-W', 'ignore:Module already imported:pytest.PytestWarning'])
