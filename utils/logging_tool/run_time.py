from utils.logging_tool.log_control import ERROR


def execution_duration(number:int):
    """
    时间装饰器
    :param number: 预计运行时间
    :return:
    """
    def decorator(func):
        def swapper(*args, **kwargs):
            res = func(*args, **kwargs)
            run_time = res.res_time
            if run_time > number:
                ERROR.logger.error(
                    "\n====================================================\n"
                    "测试用例执行时间较长，请关注.\n"
                    "函数运行时间: %s ms\n"
                    "测试用例相关数据: %s\n"
                    "========================================================"
                    , run_time, res
                )
            return res
        return swapper
    return decorator