#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time   : 2026-06-27 16:01:09


import allure
import pytest
from utils.read_files_tools.get_yaml_data_analysis import GetTestCase
from utils.assertion.assert_control import Assert
from utils.requests_tool.request_control import RequestControl
from utils.read_files_tools.regular_control import regular
from utils.requests_tool.teardown_control import TearDownHandler


case_id = ['login_01', 'login_02', 'login_03', 'login_04', 'login_05', 'login_06', 'user_01', 'user_02', 'user_03', 'user_04', 'user_05', 'user_06']
TestData = GetTestCase.case_data(case_id)
re_data = regular(str(TestData))


@allure.epic("压测项目——压测用例")
@allure.feature("用户模块")
class TestCase0627160109:

    @allure.story("接口压测")
    @pytest.mark.parametrize('in_data', eval(re_data), ids=[i['detail'] for i in TestData])
    def test_case_0627_160109(self, in_data):
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
    pytest.main(['test_case_0627_160109.py', '-s', '-W', 'ignore:Module already imported:pytest.PytestWarning'])
