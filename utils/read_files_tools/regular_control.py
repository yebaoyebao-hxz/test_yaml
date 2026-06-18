import random
import re

import jsonpath as _jsonpath
from faker import Faker

from utils.cache_process.cache_control import CacheHandler
from utils.logging_tool.log_control import ERROR


def _jp(data, expr):
    """兼容 jsonpath 新旧版本 API。新版 search 返回列表（空匹配为 []），旧版返回 False/列表。"""
    result = _jsonpath.search(expr, data)
    if not result:
        return False
    return result

class Context:
    def __init__(self):
        self.faker = Faker(locale='zh_CN')

    @classmethod
    def random_int(cls) -> int:
        _data =  random.randint(100000, 999999)
        return _data

def regular(target):
    """
    新版本
    使用正则替换请求数据
    :return:
    """
    try:
        regular_pattern = r'\${{(.*?)}}'
        while re.findall(regular_pattern, target):
            key = re.search(regular_pattern, target).group(1)
            value_types = ['int:', 'bool:', 'list:', 'dict:', 'tuple:', 'float:']
            if any(i in key for i in value_types) is True:
                func_name = key.split(":")[1].split("(")[0]
                value_name = key.split(":")[1].split("(")[1][:-1]
                if value_name == "":
                    value_data = getattr(Context(), func_name)()
                else:
                    value_data = getattr(Context(), func_name)(*value_name.split(","))
                regular_int_pattern = r'\'\${{(.*?)}}\''
                target = re.sub(regular_int_pattern, str(value_data), target, 1)
            else:
                func_name = key.split("(")[0]
                value_name = key.split("(")[1][:-1]
                if value_name == "":
                    value_data = getattr(Context(), func_name)()
                else:
                    value_data = getattr(Context(), func_name)(*value_name.split(","))
                target = re.sub(regular_pattern, str(value_data), target, 1)
        return target

    except AttributeError:
        ERROR.logger.error("未找到对应的替换的数据, 请检查数据是否正确 %s", target)
        raise
    except IndexError:
        ERROR.logger.error("yaml中的 ${{}} 函数方法不正确，正确语法实例：${{get_time()}}")
        raise




def sql_json(js_path, res):
    """ 提取 sql中的 json 数据 """
    _json_data = _jp(res, js_path)[0]
    if _json_data is False:
        raise ValueError(f"sql中的jsonpath获取失败 {res}, {js_path}")
    return _jp(res, js_path)[0]


def sql_regular(value, res=None):
    """
    这里处理sql中的依赖数据，通过获取接口响应的jsonpath的值进行替换
    :param res: jsonpath使用的返回结果
    :param value:
    :return:
    """
    sql_json_list = re.findall(r"\$json\((.*?)\)\$", value)

    for i in sql_json_list:
        pattern = re.compile(r'\$json\(' + i.replace('$', "\$").replace('[', '\[') + r'\)\$')
        key = str(sql_json(i, res))
        value = re.sub(pattern, key, value, count=1)

    return value

def cache_regular(value):


    """
    通过正则的方式，读取缓存中的内容
    例：$cache{login_init}
    :param value:
    :return:
    """
    # 正则获取 $cache{login_init}中的值 --> login_init
    regular_dates = re.findall(r"\$cache\{(.*?)\}", value)

    # 拿到的是一个list，循环数据
    for regular_data in regular_dates:
        value_types = ['int:', 'bool:', 'list:', 'dict:', 'tuple:', 'float:']
        if any(i in regular_data for i in value_types) is True:
            value_types = regular_data.split(":")[0]
            regular_data = regular_data.split(":")[1]
            # pattern = re.compile(r'\'\$cache{' + value_types.split(":")[0] + r'(.*?)}\'')
            pattern = re.compile(r'\'\$cache\{' + value_types.split(":")[0] + ":" + regular_data + r'\}\'')
        else:
            pattern = re.compile(
                r'\$cache\{' + regular_data.replace('$', "\$").replace('[', '\[') + r'\}'
            )
        try:
            # cache_data = Cache(regular_data).get_cache()
            cache_data = CacheHandler.get_cache(regular_data)
            # 使用sub方法，替换已经拿到的内容
            value = re.sub(pattern, str(cache_data), value)
        except Exception:
            pass
    return value