#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time   : 2026-06-13 14:13:09


import allure
import pytest
from utils.read_files_tools.get_yaml_data_analysis import GetTestCase
from utils.assertion.assert_control import Assert
from utils.requests_tool.request_control import RequestControl
from utils.read_files_tools.regular_control import regular
from utils.requests_tool.teardown_control import TearDownHandler


case_id = ['send_sms_01', 'send_sms_02', 'send_sms_03', 'send_sms_04', 'send_sms_05']
TestData = GetTestCase.case_data(case_id)
re_data = regular(str(TestData))


@allure.epic("wwyd")
@allure.feature("login")
class TestLogin:

    @allure.story("发送短信验证码")
    @pytest.mark.parametrize('in_data', eval(re_data), ids=[i['detail'] for i in TestData])
    def test_login(self, in_data):
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
    pytest.main(['test_login.py', '-s', '-W', 'ignore:Module already imported:pytest.PytestWarning'])
