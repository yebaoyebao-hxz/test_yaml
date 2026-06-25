"""utils.config 桥接层 —— 包装 framework/config.py 的 Config 单例，兼容旧版 API"""

from framework.config import Config as _Config

_config = _Config()
_ORIG_DATA = _config._data  # 保存原始数据引用，避免变量被覆盖后失效


class _MysqlDb:
    """mysql_db 子对象，兼容旧版 config.mysql_db.* 访问"""
    def __init__(self, data):
        self._data = data

    @property
    def switch(self) -> bool:
        return self._data.get("mysql_switch", False)

    @property
    def host(self) -> str:
        return self._data.get("mysql_host", "127.0.0.1")

    @property
    def user(self) -> str:
        return self._data.get("mysql_user", "root")

    @property
    def password(self) -> str:
        return self._data.get("mysql_password", "")

    @property
    def port(self) -> int:
        return self._data.get("mysql_port", 3306)


class _Wechat:
    """wechat 子对象，兼容旧版 config.wechat.* 访问"""

    @property
    def webhook(self) -> str:
        return ""


# 包装 Config 实例，把内部字段映射为旧版 API
class _ConfigProxy:
    def __init__(self, data):
        self._data = data
        self.mysql_db = _MysqlDb(data)
        self.wechat = _Wechat()

    @property
    def project_name(self):
        return self._data.get("project_name", "")

    @property
    def tester_name(self):
        return self._data.get("tester_name", "")


# 替换为代理对象，外部仍可 import
_config = _ConfigProxy(_ORIG_DATA)

# 模块级属性转发，使 config.mysql_db / config.project_name 等可直接访问
_mysql_db = _config.mysql_db
_wechat = _config.wechat


def __getattr__(name: str):
    """将未找到的属性转发到 _ConfigProxy 实例"""
    if name == '__path__':
        raise AttributeError(name)
    return getattr(_config, name)
