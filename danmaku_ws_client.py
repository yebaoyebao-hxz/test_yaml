# -*- coding: utf-8 -*-
"""
弹幕游戏 — 创建房间客户端 (WebSocket 版)
==========================================
链路: HTTP登录 → WebSocket连接(带token) → 认证 → 创建房间

用法:
    python danmaku_ws_client.py

WebSocket 地址: ws://HOST:PORT/game/ws/dsqy?token=TOKEN
"""

import json
import random
import struct
import string

import requests
import urllib3
from websocket import create_connection, WebSocketConnectionClosedException
from utils.read_files_tools.regular_control import *

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── proto ──
from utils.msg.msg_pb2 import (
    ReqUserInfo, ResUserInfo,
    ReqCreateRoom, ResCreateRoom)

# ════════════════════════════════════════════════════════════════
# 配置
# ════════════════════════════════════════════════════════════════

HTTP_HOST = "zs-bjfyl-dy.danmu.hxzdm.com"
BASE_URL = f"https://{HTTP_HOST}"

# 游戏服务器 WebSocket 地址 (从 Unity 客户端日志获取)
WS_HOST = "192.168.1.47"
WS_PORT = increment_id(94)
WS_PATH = "/game/ws/dsqy"

CUSTOM_ROOM_ID = int(random_room_id(3))
DIFFICULTY_LEVEL = 1
DUEL_MODE = True

UNITY_HEADERS = {
    "Host": HTTP_HOST,
    "Content-Type": "application/json; charset=utf-8",
    "User-Agent": "UnityPlayer/2021.3.42f1 (UnityWebRequest/1.0, libcurl/8.6.0-DEV)",
    "Accept": "*/*",
    "Accept-Encoding": "identity",
    "X-Unity-Version": "2021.3.42f1",
    "Connection": "Keep-Alive",
}



# ════════════════════════════════════════════════════════════════
# 二进制协议 (小端序, 和 TCP 版相同)
# ════════════════════════════════════════════════════════════════

def pack_frame(user_id: int, module: int, cmd: int, body: bytes = b"") -> bytes:
    return struct.pack('<QHH', user_id, module, cmd) + body

def unpack_header(raw: bytes):
    user_id, module, cmd = struct.unpack_from('<QHH', raw, 0)
    body = raw[12:]
    return user_id, module, cmd, body

# ════════════════════════════════════════════════════════════════
# HTTP 登录
# ════════════════════════════════════════════════════════════════

def http_login(room_id: int):
    room_id = int(room_id)  # 防御：确保 roomId 为整数（Go 后端要求 int64）
    url = f"{BASE_URL}/game/douyin/anchor_register"
    print(f"[1/3] HTTP 登录 → {url}")
    print(f"      请求体: roomId={room_id}")

    resp = requests.post(url, json={"roomId": room_id}, headers=UNITY_HEADERS, timeout=15, verify=False)
    print(f"      HTTP {resp.status_code}")
    resp.raise_for_status()

    data = resp.json()
    if isinstance(data, str):
        raise ValueError(f"返回纯字符串: {data[:100]}")

    if "data" in data and isinstance(data["data"], dict):
        inner = data["data"]
        token = inner.get("token", "")
        user_id = int(inner.get("id", 0))
    else:
        token = data.get("token", "")
        user_id = int(data.get("id", 0))

    print(f"      token: {token if token else '(空)'}")
    print(f"      userId: {user_id}")
    return token, user_id

# ════════════════════════════════════════════════════════════════
# WebSocket 连接
# ════════════════════════════════════════════════════════════════

def ws_connect(token: str):
    """连接 WebSocket，URL 带 token 参数"""
    ws_url = f"ws://{WS_HOST}:{WS_PORT}{WS_PATH}?token={token}"
    print(f"\n[2/4] WebSocket 连接 → {ws_url[:80]}...")

    ws = create_connection(ws_url, timeout=10, enable_multithread=True)
    print(f"      已连接")
    return ws

# ════════════════════════════════════════════════════════════════

def ws_recv_frame(ws):
    """收一帧二进制消息并解包"""
    raw = ws.recv()
    if isinstance(raw, str):
        print(f"      收到文本消息: {raw[:200]}")
        return None, None, None, None
    rid, mod, cmd, body = unpack_header(raw)
    return rid, mod, cmd, body

def ws_auth(ws, token: str, user_id: int, room_id: int):
    """WebSocket 认证"""
    print(f"\n[3/4] WS 认证 → M_User(10) / UserInfo(1)")

    msg = ReqUserInfo()
    msg.token = token
    msg.roomCode = str(room_id)

    frame = pack_frame(user_id, module=10, cmd=1, body=msg.SerializeToString())
    ws.send_binary(frame)
    print(f"      已发送 ReqUserInfo ({len(frame)} bytes)")

    # 收响应（可能先收到网关消息）
    for _ in range(3):
        rid, mod, cmd, body = ws_recv_frame(ws)
        if rid is None:
            continue
        print(f"      收到 → userId={rid} module={mod} cmd={cmd} body_len={len(body) if body else 0}")

        # 网关消息 → 跳过
        if mod == 0 and cmd == 10001:
            print(f"         [跳过网关包]")
            continue

        # UserInfo 响应
        if mod == 10 and cmd == 1:
            res = ResUserInfo()
            res.ParseFromString(body)
            err = res.errCode
            print(f"         errCode={err} inviteCode={res.inviteCode} levelStar={res.levelStar}")
            if err == 0:
                print(f"      认证通过 | inviteCode={res.inviteCode}")
                return True
            else:
                print(f"      认证失败 errCode={err}")
                return False

    print("      未收到有效认证响应")
    return False

def create_room(ws, user_id: int):
    """创建房间"""
    print(f"\n[3/3] 创建房间 -> M_Matching(100) / CreateRoom(50)")

    msg = ReqCreateRoom()
    msg.DifficultyLevel = DIFFICULTY_LEVEL
    msg.duel = DUEL_MODE
    msg.pwd = ""

    body = msg.SerializeToString()
    print(f"      Req body hex: {body.hex()}")
    frame = pack_frame(user_id, module=100, cmd=50, body=body)
    ws.send_binary(frame)
    print(f"      已发送 ReqCreateRoom ({len(frame)} bytes)")

    rid, mod, cmd, body = ws_recv_frame(ws)
    if rid is None:
        print("      未收到响应")
        return None
    print(f"      收到 -> userId={rid} module={mod} cmd={cmd} body_len={len(body) if body else 0} body_hex={body.hex() if body else '(empty)'}")

    res = ResCreateRoom()
    if body:
        res.ParseFromString(body)
    else:
        print("      WARNING: body is empty, errCode defaults to 0")

    err = res.errCode
    if err == 0:
        room = res.room
        print(f"\n  房间创建成功!")
        print(f"      游戏房间号 : {room.roomId}")
        print(f"      房主       : userId={room.masterId}")
        print(f"      房间状态   : {room.roomStatus}")
        print(f"      对决模式   : {room.duel}")
        print(f"      难度       : {room.DifficultyLevel}")
        print(f"      可观战     : {room.canWatch}")
        print(f"      有机器人   : {room.hasRobot}")
        if room.users:
            print(f"      在线人数   : {len(room.users)}")
        return room
    else:
        err_name = ResCreateRoom.Error.DESCRIPTOR.values_by_number.get(err, None)
        err_label = err_name.name if err_name else "未知"
        print(f"      创建失败 errCode={err} ({err_label})")
        return None
def main():
    print("=" * 60)
    print("  弹幕游戏 — 创建房间客户端 (WebSocket)")
    print(f"  HTTP : {BASE_URL}")
    print(f"  WS   : ws://{WS_HOST}:{WS_PORT}{WS_PATH}")
    print("=" * 60)

    # Step 1: HTTP 登录
    try:
        token, user_id = http_login(CUSTOM_ROOM_ID)
        if not token or not user_id:
            print("登录失败：未获取到 token 或 user_id")
            return
    except Exception as e:
        print(f"登录异常: {e}")
        return

    # Step 2: WebSocket 连接 (token 已通过 URL 传递，无需额外认证)
    try:
        ws = ws_connect(token)
    except Exception as e:
        print(f"WebSocket 连接失败: {e}")
        return

    try:
        # 先收一帧看看服务器是否发欢迎消息
        old_timeout = ws.timeout
        ws.timeout = 2
        try:
            raw = ws.recv()
            if raw:
                rid, mod, cmd, body = unpack_header(raw)
                print(f"   [服务器] userId={rid} module={mod} cmd={cmd} body_len={len(body) if body else 0}")
        except Exception:
            print("   [服务器] 无欢迎消息")
        ws.timeout = old_timeout

        # Step 3: 直接创建房间 (token已在URL传过, 无需额外认证)
        room = create_room(ws, user_id)
        if room:
            print(f"\n  房间号: {room.roomId} | 房主: {room.masterId}")

    finally:
        try:
            ws.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
