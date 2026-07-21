import asyncio
import uuid

import websockets
import json
import base64
import os, time
from io import BytesIO
from utils.device_remote.adb_remote_ctrl import AdbRemoteCtrl
from pathlib import Path

# WebSocket服务端口，前端页面连接 ws://127.0.0.1:8090
WS_LISTEN_PORT = 8090
# 全局缓存设备控制器实例，单设备单连接
# Bug 2 修复：限制最大缓存 10 个 ctrl 实例，防止内存泄漏
device_ctrl_map: dict = {}
MAX_CTRL_CACHE = 10

async def handle_device_websocket(websocket):
    """处理前端投屏操控WebSocket连接"""
    print(f"[WS] 新连接: {websocket.remote_address}")
    current_serial = None
    ctrl = None
    try:
        while True:
            recv_msg = await websocket.recv()
            msg_data = json.loads(recv_msg)
            action_type = msg_data.get("action")
            serial = msg_data.get("device_serial")
            print(f"[WS] 收到: action={action_type}, serial={serial}")

            # 初始化设备连接
            if action_type == "init_device":
                current_serial = serial
                if serial not in device_ctrl_map:
                    ctrl = AdbRemoteCtrl(serial=serial)
                    device_ctrl_map[serial] = ctrl
                else:
                    ctrl = device_ctrl_map[serial]
                # 初始化成功后立即推送第一帧
                screen_img = ctrl.get_screen_image().convert("RGB")
                buf = BytesIO()
                screen_img.save(buf, format="JPEG", quality=40)
                b64_screen = base64.b64encode(buf.getvalue()).decode("utf-8")
                print(f"[WS] 推送首帧: {len(b64_screen)} bytes")
                await websocket.send(json.dumps({
                    "msg": "设备初始化成功",
                    "screen_base64": b64_screen
                }))
                continue

            # 触控操作指令
            if not ctrl:
                await websocket.send(json.dumps({"error": "设备未初始化，请先初始化设备"}))
                continue
            if msg_data.get("stream_only"):
                pass
            elif action_type == "tap":
                x, y = msg_data["x"], msg_data["y"]
                ctrl.tap(x, y)
            elif action_type == "swipe":
                x1, y1, x2, y2 = msg_data["x1"], msg_data["y1"], msg_data["x2"], msg_data["y2"]
                ctrl.swipe(x1, y1, x2, y2, msg_data.get("duration", 300))
            elif action_type == "input_text":
                text = msg_data.get("text", "")
                if not text:
                    await websocket.send(json.dumps({"error": "文本不能为空"}))
                else:
                    safe = text.replace("'", "'\\''").replace(' ', '%s')
                    ctrl.device.shell(f"input text '{safe}'")
                    await websocket.send(json.dumps({"msg": "文本已注入", "length": len(text)}))
            elif action_type == "screenshot":
                save_dir = Path("data/screen")
                save_dir.mkdir(parents=True, exist_ok=True)
                ts = time.strftime("%Y%m%d_%H%M%S")
                fname = f"{current_serial}_{ts}.png"
                fpath = save_dir / fname
                img = ctrl.get_screen_image()
                img.save(str(fpath), "PNG")
                await websocket.send(json.dumps({"msg": "截图已保存", "url": f"/data/screen/{fname}"}))
            elif action_type == "session_info":
                info = {
                    "session_id": current_serial + "-" + uuid.uuid4().hex[:8],
                    "codec": "JPEG q40",
                    "width": 1080,  # 建议从 ctrl.device.shell("wm size") 解析
                    "height": 2340,
                    "serial": current_serial,
                }
                await websocket.send(json.dumps(info))
            elif action_type == "release":
                if current_serial and current_serial in device_ctrl_map:
                    old_ctrl = device_ctrl_map.pop(current_serial, None)
                    if old_ctrl:
                        try:old_ctrl.close()
                        except Exception: pass
                    print(f"[WS] 主动释放 ctrl: {current_serial}")
                await  websocket.send(json.dumps({"msg": "已释放", "serial": current_serial}))
                break
            elif action_type == "key":
                key = msg_data.get("key", "")
                # key 映射表: action key -> adb keyevent code
                # 0=KEYCODE_UNKNOWN home=3 back=4 menu=82 power=26
                # volume_up=24 volume_down=25 enter=66
                key_map = {
                    "home":        3,
                    "back":        4,
                    "menu":        82,
                    "power":       26,
                    "volume_up":   24,
                    "volume_down": 25,
                    "enter":       66,
                }
                keyevent_code = key_map.get(key.lower())
                if keyevent_code is None:
                    await websocket.send(json.dumps({"error": f"不支持的按键: {key}"}))
                else:
                    ctrl.device.shell(f"input keyevent {keyevent_code}")

            # 推送实时画面
            try:
                screen_img = ctrl.get_screen_image().convert("RGB")
                buf = BytesIO()
                screen_img.save(buf, format="JPEG", quality=40)
                b64_screen = base64.b64encode(buf.getvalue()).decode("utf-8")
                await websocket.send(json.dumps({"screen_base64": b64_screen}))
            except Exception as se:
                await websocket.send(json.dumps({"error": f"截图失败: {se}"}))
    except Exception as e:
        print(f"WebSocket连接断开：{e}")
    finally:
        # Bug 3 修复：断开连接时若缓存超过上限，淘汰最旧的 ctrl
        if len(device_ctrl_map) > MAX_CTRL_CACHE:
            oldest_serial = next(iter(device_ctrl_map))
            old_ctrl = device_ctrl_map.pop(oldest_serial, None)
            if old_ctrl:
                try: old_ctrl.close()
                except Exception: pass
                print(f"[WS] 清理超限 ctrl: {oldest_serial}")
        print(f"[WS] 连接关闭, current_serial={current_serial}")

async def start_ws_server():
    async with websockets.serve(handle_device_websocket, "0.0.0.0", WS_LISTEN_PORT,
                                  max_size=8 * 1024 * 1024):
        await asyncio.Future()

if __name__ == "__main__":
    print(f"设备投屏WebSocket服务启动，端口 {WS_LISTEN_PORT}")
    asyncio.run(start_ws_server())
