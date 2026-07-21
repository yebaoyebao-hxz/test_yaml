import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from fastapi import APIRouter
from utils.device_remote.adb_remote_ctrl import AdbRemoteCtrl

router = APIRouter(prefix="/api/v1/device", tags=["设备管理"])

# 获取全部已连接设备列表接口
@router.get("/list")
def get_all_device_list():
    """获取所有本地ADB连接设备完整信息"""
    try:
        device_data = AdbRemoteCtrl.get_all_devices()
        return {
            "code": 200,
            "msg": "成功",
            "data": device_data
        }
    except Exception as e:
        return {
            "code": 500,
            "msg": f"获取设备失败：{str(e)}",
            "data": []
        }

# 根据设备序列号获取单设备控制器（给WebSocket投屏使用）
@router.get("/ctrl/{serial}")
def get_device_ctrl(serial: str):
    return {"code": 200, "serial": serial}