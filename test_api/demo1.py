from string import Template

from jsonpath import JSONPath
import pytest
import requests
from xToolkit import xfile

data = xfile.read(r"E:\yebao\test_yaml\test_api\data\接口用例数据.xls").excel_to_dict(sheet=1)


dic = {}
@pytest.mark.parametrize("case_info", data)
def test_execute(case_info):
    url = case_info["请求地址"]

    if '$' in url:
        url = Template(url).substitute(dic)

    response = requests.request(
        method=case_info["请求方式"],
        url = url,
        parapms = eval(case_info["请求参数"]),
        data = eval(case_info["断言信息"])
    )
    response.raise_for_status()
    print(response.json())

    assert response.json()["code"] == 0
    assert response.status_code == case_info["断言信息"]

    if case_info["提取参数"]:
        lsk = JSONPath(response.json(),"$.."+case_info["提取参数"])
        # 字典存值  语法 ： 字典名[kay] = value
        dic[case_info["提取参数"]] = lsk[0]