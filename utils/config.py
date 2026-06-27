#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""配置模块 —— 从 common/config.yaml 读取，提供属性访问。

使用方式：
    from utils import config
    print(config.mysql_db.switch)   # mysql_db 段
    print(config.project_name)      # YAML 顶层字段
"""

import yaml
from pathlib import Path
from typing import Any


# ============================================================
# 1. 读取 common/config.yaml
# ============================================================
_yaml_path = Path(__file__).resolve().parent.parent / "common" / "config.yaml"
with open(_yaml_path, "r", encoding="utf-8") as _f:
    _data: dict[str, Any] = yaml.safe_load(_f) or {}


# ============================================================
# 2. 嵌套配置类（把 YAML 字典段落转成属性访问对象）
# ============================================================

class _MysqlDb:
    """mysql_db 配置段 → config.mysql_db.switch 等"""

    def __init__(self, raw: dict):
        self.switch: bool = raw.get("switch", False)
        self.host: str = raw.get("host", "")
        self.user: str = raw.get("user", "")
        self.password: str = raw.get("password", "")
        self.port: int = raw.get("port", 3306)

    def __repr__(self):
        return (
            f"MysqlDb(switch={self.switch}, host={self.host!r}, "
            f"user={self.user!r}, port={self.port})"
        )


class _Wechat:
    """wechat 配置段 → config.wechat.webhook"""

    def __init__(self, raw: dict):
        self.webhook: str = raw.get("webhook", "")

    def __repr__(self):
        return f"Wechat(webhook={self.webhook!r})"


class _DingTalk:
    """ding_talk 配置段 → config.ding_talk.webhook / secret"""

    def __init__(self, raw: dict):
        self.webhook: str = raw.get("webhook", "")
        self.secret: str = raw.get("secret", "")

    def __repr__(self):
        return f"DingTalk(webhook={self.webhook!r})"


class _Email:
    """email 配置段 → config.email.send_user 等"""

    def __init__(self, raw: dict):
        self.send_user: str = raw.get("send_user", "")
        self.email_host: str = raw.get("email_host", "")
        self.stamp_key: str = raw.get("stamp_key", "")
        self.send_list: str = raw.get("send_list", "")


class _Lark:
    """lark 配置段 → config.lark.webhook"""

    def __init__(self, raw: dict):
        self.webhook: str = raw.get("webhook", "")


# ============================================================
# 3. 模块级实例（支持 config.mysql_db.switch 这样的访问）
# ============================================================
mysql_db = _MysqlDb(_data.get("mysql_db", {}))
wechat = _Wechat(_data.get("wechat", {}))
ding_talk = _DingTalk(_data.get("ding_talk", {}))
email = _Email(_data.get("email", {}))
lark = _Lark(_data.get("lark", {}))


# ============================================================
# 4. 兜底：顶层字段直接用 __getattr__ 暴露
#    config.project_name → _data["project_name"]
#    config.host         → _data["host"]
#    等等
# ============================================================
def __getattr__(name: str) -> Any:
    if name.startswith("_"):
        raise AttributeError(f"没有 '{name}' 这个配置项")
    if name in _data:
        return _data[name]
    raise AttributeError(f"config 中没有 '{name}' 字段，可用字段: {list(_data.keys())}")
