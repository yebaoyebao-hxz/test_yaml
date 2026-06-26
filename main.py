import pytest, os, sys, subprocess, socket, time
from utils.notify.wechat_send import WeChatSend
from utils.other_tools.allure_data.allure_report_data import AllureFileClean
# 运行前请安装 pytest test_demo1.py --alluredir=allure-result
# runfile() 是 PyCharm Console 的特殊命令，它直接把参数传给 pytest 但方式可能不对。建议直接在 Terminal 里跑
# 生成测试报告
if __name__ == "__main__":
    pytest.main(["-vs",  # 固定命令
                 "--capture=sys",  # 捕获输出
                 "test_api/test_demo2.py",
                 "--clean-alluredir",  # 清除上次数据
                 "--alluredir=allure-result"])
    # 生成报告到 report/html（框架通知代码以此路径为准）
    os.system("allure generate allure-result -o ./report/html --clean")
    # 发送企业微信通知（根据 notification_type 自动判断发哪种）
    try:
        WeChatSend(AllureFileClean().get_case_count()).send_wechat_notification()
        print("[通知] 企业微信消息发送成功")
    except Exception as e:
        print(f"[通知] 发送失败: {e}")
    # 启动本地 HTTP 服务并打开报告（Jenkins 环境下跳过）
    if not os.environ.get("JENKINS_HOME"):
        print("[报告] 正在启动本地服务...")
        subprocess.Popen([sys.executable, "-m", "http.server", "8888"],
                         cwd=os.path.join(os.path.dirname(__file__), "report", "html"),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
        os.system("start http://127.0.0.1:8888")
        print("[报告] 浏览器已打开 http://127.0.0.1:8888")