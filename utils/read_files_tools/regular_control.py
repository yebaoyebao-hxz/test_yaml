import random
import re
import string

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
    def random_int(cls, min_val=None, max_val=None) -> int:
        """随机整数，默认 6 位。支持自定义范围: ${{random_int(10000000,99999999)}}"""
        try:
            a = int(min_val) if min_val is not None else 100000
            b = int(max_val) if max_val is not None else 999999
        except (ValueError, TypeError):
            a, b = 100000, 999999
        return random.randint(a, b)

    @classmethod
    def random_digits(cls, n=None) -> int:
        """指定位数随机数: ${{random_digits(8)}} → 8位随机整数"""
        try:
            digits = int(n) if n is not None else 6
        except (ValueError, TypeError):
            digits = 6
        lo = 10 ** (digits - 1)
        hi = 10 ** digits - 1
        return random.randint(lo, hi)

    @classmethod
    def random_str(cls, n=None) -> str:
        """指定长度随机字母数字: ${{random_str(16)}}"""
        import string
        try:
            length = int(n) if n is not None else 8
        except (ValueError, TypeError):
            length = 8
        return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

    @classmethod
    def uuid4(cls) -> str:
        """随机 UUID: ${{uuid4()}}"""
        import uuid
        return str(uuid.uuid4())

    @classmethod
    def timestamp(cls) -> int:
        """当前秒级时间戳: ${{timestamp()}}"""
        import time
        return int(time.time())

    @classmethod
    def timestamp_ms(cls) -> int:
        """当前毫秒时间戳: ${{timestamp_ms()}}"""
        import time
        return int(time.time() * 1000)

    def seat_all(self):
        # AI从图片提取的全部姓氏（百家姓）
        SURNAMES = [
            # 单姓 (16列×26行 + 末行8个)
            "赵", "钱", "孙", "李", "周", "吴", "郑", "王", "冯", "陈", "褚", "卫", "蒋", "沈", "韩", "杨",
            "朱", "秦", "尤", "许", "何", "吕", "施", "张", "孔", "曹", "严", "华", "金", "魏", "陶", "姜",
            "戚", "谢", "邹", "喻", "柏", "水", "窦", "章", "云", "苏", "潘", "葛", "奚", "范", "彭", "郎",
            "鲁", "韦", "昌", "马", "苗", "凤", "花", "方", "俞", "任", "袁", "柳", "酆", "鲍", "史", "唐",
            "费", "廉", "岑", "薛", "雷", "贺", "倪", "汤", "滕", "殷", "罗", "毕", "郝", "邬", "安", "常",
            "乐", "于", "时", "傅", "皮", "卞", "齐", "康", "伍", "余", "元", "卜", "顾", "孟", "平", "黄",
            "和", "穆", "萧", "尹", "姚", "邵", "湛", "汪", "祁", "毛", "禹", "狄", "米", "贝", "明", "臧",
            "计", "伏", "成", "戴", "谈", "宋", "茅", "庞", "熊", "纪", "舒", "屈", "项", "祝", "董", "梁",
            "杜", "阮", "蓝", "闵", "席", "季", "麻", "强", "贾", "路", "娄", "危", "江", "童", "颜", "郭",
            "梅", "盛", "林", "刁", "钟", "徐", "邱", "骆", "高", "夏", "蔡", "田", "樊", "胡", "凌", "霍",
            "虞", "万", "支", "柯", "昝", "管", "卢", "莫", "经", "房", "裘", "缪", "干", "解", "应", "宗",
            "丁", "宣", "贲", "邓", "郁", "单", "杭", "洪", "包", "诸", "左", "石", "崔", "吉", "钮", "龚",
            "程", "嵇", "邢", "滑", "裴", "陆", "荣", "翁", "荀", "羊", "於", "惠", "甄", "麴", "家", "封",
            "芮", "羿", "储", "靳", "汲", "邴", "糜", "松", "井", "段", "富", "巫", "乌", "焦", "巴", "弓",
            "牧", "隗", "山", "谷", "车", "侯", "宓", "蓬", "全", "郗", "班", "仰", "秋", "仲", "伊", "宫",
            "宁", "仇", "栾", "暴", "甘", "钭", "厉", "戎", "祖", "武", "符", "刘", "景", "詹", "束", "龙",
            "叶", "幸", "司", "韶", "郜", "黎", "蓟", "薄", "印", "宿", "白", "怀", "蒲", "邰", "从", "鄂",
            "索", "咸", "籍", "赖", "卓", "蔺", "屠", "蒙", "池", "乔", "阴", "鬱", "胥", "能", "苍", "双",
            "闻", "莘", "党", "翟", "谭", "贡", "劳", "逄", "姬", "申", "扶", "堵", "冉", "宰", "郦", "雍",
            "卻", "璩", "桑", "桂", "濮", "牛", "寿", "通", "边", "扈", "燕", "冀", "郏", "浦", "尚", "农",
            "温", "别", "庄", "晏", "柴", "瞿", "阎", "充", "慕", "连", "茹", "习", "宦", "艾", "鱼", "容",
            "向", "古", "易", "慎", "戈", "廖", "庾", "终", "暨", "居", "衡", "步", "都", "耿", "满", "弘",
            "匡", "国", "文", "寇", "广", "禄", "阙", "东", "欧", "殳", "沃", "利", "蔚", "越", "夔", "隆",
            "师", "巩", "厍", "聂", "晁", "勾", "敖", "融", "冷", "訾", "辛", "阚", "那", "简", "饶", "空",
            "曾", "毋", "沙", "乜", "养", "鞠", "须", "丰", "巢", "关", "蒯", "相", "查", "后", "荆", "红",
            "游", "竺", "权", "逯", "盖", "益", "桓", "公"
        ]
        # 存储最终结果列表
        result = []
        # 遍历
        for idx,surname in enumerate(SURNAMES, 1):
            content = f"加入{surname}"
            result.append(content)
        return result

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

# ════════════════════════════════════════════════════════════════
# 随机参数
# ════════════════════════════════════════════════════════════════

def random_room_id(cid):
    """cid控制随机数长度"""
    if not isinstance(cid, int) or cid <= 0:
        raise ValueError("cid必须是大于0的整数，用于指定房间ID的长度")
    room_id = ''.join(random.choice(string.digits) for _ in range(cid))
    return room_id

_inc_counter = 0
def increment_id(start=None):
    global _inc_counter
    if start is not None:
        _inc_counter = int(start)
    val = _inc_counter
    _inc_counter += 1
    return val

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