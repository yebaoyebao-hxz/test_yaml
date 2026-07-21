from ppadb.client import Client as AdbClient
from ppadb.device import Device
from pathlib import Path
from PIL import Image
from io import BytesIO
from datetime import datetime
import re

# ADB基础配置
ADB_LOCAL_HOST = "127.0.0.1"
ADB_LOCAL_PORT = 5037
# 截图保存目录：项目根目录 /data/screen
SCREEN_SAVE_DIR = Path(__file__).parent.parent.parent / "data" / "screen"
# 自动创建文件夹（不存在则生成）
SCREEN_SAVE_DIR.mkdir(exist_ok=True, parents=True)

class AdbRemoteCtrl:
    def __init__(self, serial: str = None, remote_adb_host: str = None, remote_adb_port: int = None):
        """
        设备操控初始化
        :param serial: 设备序列号
        :param remote_adb_host: 远程FRP穿透服务器IP，本地设备传None
        :param remote_adb_port: 远程FRP映射端口，本地设备传None
        """
        host = remote_adb_host if remote_adb_host else ADB_LOCAL_HOST
        port = remote_adb_port if remote_adb_port else ADB_LOCAL_PORT
        self.adb_client = AdbClient(host=host, port=port)
        self.device: Device = None
        if serial:
            self._connect_device(serial)

    @staticmethod
    def get_all_devices(remote_adb_host=None, remote_adb_port=None) -> list[dict]:
        """静态方法：获取本地/远程所有ADB设备完整信息，返回结构化字典列表（供前端渲染）"""
        host = remote_adb_host if remote_adb_host else ADB_LOCAL_HOST
        port = remote_adb_port if remote_adb_port else ADB_LOCAL_PORT
        client = AdbClient(host=host, port=port)
        raw_devices = client.devices()
        device_list = []
        for dev in raw_devices:
            serial = dev.serial
            # 获取系统版本
            os_version = dev.shell("getprop ro.build.version.release").strip()
            # 获取设备型号
            model = dev.shell("getprop ro.product.model").strip()
            # 分辨率
            size_raw = dev.shell("wm size").strip()
            size_match = re.search(r"(\d+)x(\d+)", size_raw)
            resolution = f"{size_match.group(1)}x{size_match.group(2)}" if size_match else "未知"
            # 判断设备类型
            brand = dev.shell("getprop ro.product.brand").strip().lower()
            dev_type = "鸿蒙真机" if "harmony" in brand or "huawei" in brand else "安卓真机"
            if serial.startswith("emulator-"):
                dev_type = "模拟器"
            # 组装设备信息
            device_info = {
                "serial": serial,
                "model": model,
                "type": dev_type,
                "system": os_version,
                "resolution": resolution,
                "status": "online",
                "connect_type": "usb" if not serial.startswith("emulator-") else "emulator",
                "host": host,
                "port": port
            }
            device_list.append(device_info)
        return device_list


    def _connect_device(self, serial: str):
        device_list = self.adb_client.devices()
        if not device_list:
            raise ConnectionError("未检测到任何ADB设备，请检查调试连接")
        if serial:
            self.device = next((d for d in device_list if d.serial == serial), None)
            if not self.device:
                raise Exception(f"未找到序列号 {serial} 的设备")
        else:
            self.device = device_list[0]
        print(f"设备连接成功，序列号：{self.device.serial}")

    # 基础触控操作
    def tap(self, x: int, y: int):
        self.device.shell(f"input tap {x} {y}")

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300):
        self.device.shell(f"input swipe {x1} {y1} {x2} {y2} {duration}")

    def long_tap(self, x: int, y: int, hold_ms: int = 800):
        self.swipe(x, y, x, y, hold_ms)

    def input_text(self, text: str):
        safe_text = text.replace(" ", "%s")
        self.device.shell(f"input text {safe_text}")

    # 截图
    def get_screen_image(self) -> Image.Image:
        raw_data = self.device.screencap()
        img = Image.open(BytesIO(raw_data))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        save_file_name = f"{self.device.serial}_{timestamp}.png"
        save_full_path = SCREEN_SAVE_DIR / save_file_name
        # 保存截图到目标文件夹
        img.save(save_full_path, format="PNG")
        return img

    def get_screen_image_with_path(self) -> tuple[Image.Image, str]:
        """返回(图片对象, 完整保存路径)"""
        raw_data = self.device.screencap()
        img = Image.open(BytesIO(raw_data))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        save_file_name = f"{self.device.serial}_{timestamp}.png"
        save_full_path = str(SCREEN_SAVE_DIR / save_file_name)
        img.save(save_full_path, format="PNG")
        return img, save_full_path

    def save_screen(self, save_path: str = "./screen_temp.png"):
        img = self.get_screen_image()
        img.save(save_path)
        return save_path

    # 日志、安装、卸载
    def get_logcat(self, line_count: int = 100):
        return self.device.shell(f"logcat -d -t {line_count}")

    def install_apk(self, apk_path: str):
        self.device.install(apk_path)

    def uninstall_app(self, package_name: str):
        self.device.uninstall(package_name)

    def close(self):
        del self.device

# 本地调用示例
if __name__ == "__main__":
    # 本地USB设备
    ctrl = AdbRemoteCtrl()
    ctrl.tap(500, 1500)
    ctrl.save_screen()
    ctrl.close()

    # 远程FRP穿透设备示例
    # remote_ctrl = AdbRemoteCtrl(serial="RMX3617", remote_adb_host="123.xx.xx.xx", remote_adb_port=15037)