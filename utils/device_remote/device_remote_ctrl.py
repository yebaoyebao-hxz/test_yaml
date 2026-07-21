from ppadb.client import Client as AdbClient
from ppadb.device import Device
import time
from PIL import Image
from io import BytesIO

# ADB 客户端初始化
ADB_HOST = "127.0.0.1"
ADB_PORT = 5037


class LocalAndroidCtrl:
    def __init__(self, device_serial: str = None):
        self.adb_client = AdbClient(host=ADB_HOST, port=ADB_PORT)
        self.device: Device = None
        self._connect(device_serial)

    def _connect(self, serial):
        """连接设备，不传serial默认取第一台设备"""
        devices = self.adb_client.devices()
        if not devices:
            raise Exception("未检测到安卓设备，请开启调试")
        if serial:
            self.device = next(d for d in devices if d.serial == serial)
        else:
            self.device = devices[0]
        print(f"设备连接成功：{self.device.serial}")

    # 基础触控操作
    def tap(self, x: int, y: int):
        """点击坐标"""
        self.device.shell(f"input tap {x} {y}")

    def swipe(self, x1: int, y1: int, x2: int, y2, duration=300):
        """滑动，单位ms"""
        self.device.shell(f"input swipe {x1} {y1} {x2} {y2} {duration}")

    def long_tap(self, x, y, hold=800):
        """长按"""
        self.swipe(x, y, x, y, hold)

    def input_text(self, text: str):
        """输入文字"""
        safe_text = text.replace(" ", "%s")
        self.device.shell(f"input text {safe_text}")

    # 截图
    def screen_capture(self) -> Image.Image:
        """实时截图返回PIL图像"""
        raw = self.device.screencap()
        return Image.open(BytesIO(raw))

    def save_screenshot(self, save_path="screen.png"):
        img = self.screen_capture()
        img.save(save_path)
        return save_path

    # 获取实时日志
    def get_logcat(self, lines=100):
        return self.device.shell(f"logcat -d -t {lines}")

    # 安装APK
    # def install_apk(self, apk_path):
    #     self.device.install(apk)

    # 释放连接
    def close(self):
        del self.device


# 本地调用示例
if __name__ == "__main__":
    ctrl = LocalAndroidCtrl()
    ctrl.tap(500, 1200)
    ctrl.swipe(500, 1800, 500, 800)
    ctrl.save_screenshot("./local_screen.png")
    print(ctrl.get_logcat(50))
    ctrl.close()