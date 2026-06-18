import os
from typing import Text

def root_path():
    """ 获取 根路径  """
    path =  os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    return path

def ensure_path(path:Text) -> Text:
    """兼容不同系统操作"""
    if "/" in path:
        path = os.sep.join(path.split("/"))

    if "\\" in path:
        path = os.sep.join(path.split("\\"))

    return root_path() + path

def ensure_path_sep(path:Text) -> Text:
    """ensure_path 别名，生成独立文件存放路径"""
    if "/" in path:
        path = os.sep.join(path.split("/"))

    if "\\" in path:
        path = os.sep.join(path.split("\\"))

    return root_path() + path