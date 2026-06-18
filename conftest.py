# -*- coding: utf-8 -*-
"""项目根 conftest.py —— 加载 framework 插件 + Allure 集成

用法：
  pytest data/兔子.yaml -p framework.pytest_plugin        # 显式指定
  pytest --yaml-path data/兔子.yaml -p framework.pytest_plugin
  pytest test_case/test_login.py -p framework.pytest_plugin

如果不需要 framework 插件，删掉或改名此文件即可。
"""

pytest_plugins = ["framework.pytest_plugin"]
