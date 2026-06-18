"""pytest conftest —— 加载 兔子测试框架 插件。

将此文件复制到项目的 test_api/ 目录，或在 pytest 命令行中指定:
    pytest -p framework.pytest_plugin --yaml-path data/兔子.yaml

也可作为本地插件：
    pytest --yaml-path data/兔子.yaml -p framework.pytest_plugin
"""

pytest_plugins = ["framework.pytest_plugin"]
