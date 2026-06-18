import json
from typing import *
from common.setting import ensure_path
from utils.other_tools.models import *
from utils.other_tools.models import TestMetrics
from utils.read_files_tools.get_all_files_path import get_all_files


class AllureFileClean:
    """数据清除"""

    @classmethod
    def get_testcases(cls) -> list:
        """获取所有的allure报告中的执行用例情况"""
        # 将数据全部收集到files中
        files = []
        for i in get_all_files(ensure_path("\\report\\html\\data\\test-cases")):
            with open(i, "r", encoding="utf-8") as file:
                data = json.load(file)
                files.append(data)
        return files

    def get_failed_case(self) -> list:
        """获取所有失败的用例和用例代码途径"""
        error_case = []
        for i in self.get_testcases():
            if i['status'] == 'failed' or i['status'] == 'broken':
                error_case.append((i['name'],i['fullName']))
        return error_case

    def get_failed_case_data(self) -> Text:
        """返回所有失败用例的相关内容"""
        data = self.get_failed_case()
        val = ""
        # 判断有失败用例则返回内容
        if len(data) >= 1:
            val = "用例失败:\n"
            val = "       ---------------------------------\n"
            for i in data:
                val += "        " + i[0] + ":" + i[1] + "\n"
        return val

    @classmethod
    def get_case_count(cls) -> TestMetrics | FileNotFoundError:
        """计算用例数量"""
        try:
            file_name = ensure_path("\\report\\html\\widgets\\summary.json")
            with open(file_name, "r", encoding="utf-8") as file:
                data = json.load(file)
            _case_count = data['statistic']
            _time = data['time']
            keep_keys = {"passed", "failed", "broken", "skipped", "total"}
            run_case_data = {k: v for k, v in data['statistic'].items() if k in keep_keys}
            if _case_count["total"] > 0:
                run_case_data["pass_rate"] = round(
                    _case_count["passed"] / _case_count["total"] * 100, 2)
            else:
                run_case_data["pass_rate"] = 0
            run_case_data["time"] = _time if run_case_data["total"] == 0 else round(_time['duration']/1000, 2)
            return TestMetrics(**run_case_data)
        except FileNotFoundError as exception:
            raise FileNotFoundError(
                "程序中检查到您未生成allure报告，"
                "通常可能导致的原因是allure环境未配置正确，"
                "详情可查看如下博客内容："
                "https://blog.csdn.net/weixin_43865008/article/details/124332793"
            ) from exception

if __name__ == '__main__':
    AllureFileClean().get_case_count()