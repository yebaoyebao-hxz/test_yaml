#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time   : 2026-06-17 19:17:33


import allure
import pytest
from utils.read_files_tools.get_yaml_data_analysis import GetTestCase
from utils.assertion.assert_control import Assert
from utils.requests_tool.request_control import RequestControl
from utils.read_files_tools.regular_control import regular
from utils.requests_tool.teardown_control import TearDownHandler


case_id = ['game_start_01', 'game_start_02', 'game_start_03', 'game_start_04', 'game_start_05', 'game_start_06', 'game_start_07', 'game_start_08']
TestData = GetTestCase.case_data(case_id)
re_data = regular(str(TestData))


@allure.epic("游戏模块")
@allure.feature("游戏启动")
class TestCase0617191733:

    @allure.story("验证游戏启动接口功能")
    @pytest.mark.parametrize('in_data', eval(re_data), ids=[i['detail'] for i in TestData])
    def test_case_0617_191733(self, in_data):
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
    pytest.main(['test_case_0617_191733.py', '-s', '-W', 'ignore:Module already imported:pytest.PytestWarning'])
