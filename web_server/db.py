# -*- coding: utf-8 -*-
"""MySQL 数据库连接"""
from utils.mysql_tool.mysql_connect import DBManager


def get_db_conn():
    """获取 MySQL 数据库连接"""
    return DBManager().connect()
