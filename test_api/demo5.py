import requests
import time
import uuid
import random

#测试服
Test_URL = "http://192.168.1.47:94/douyin/webcast/gift_notify"
#正式服
Aip_URL = "https://zs-bjfyl-dy.danmu.hxzdm.com"
HEADERS = {
    "User-Agent": "UnityPlayer/2023.1.13f1 (UnityWebRequest/1.0, libcurl/8.1.1-DEV)",
    "Accept": "*/*",
    "Accept-Encoding": "deflate, gzip",
    "Content-Type": "application/json;charset=utf-8",
    "X-Unity-Version": "2023.1.13f1",
    "x-roomid": "12321",
}

def auto_join(count=10, interval=1.0):
    for i in range(1, count + 1):
        payload = [{
            "msg_id": f"hxz_test_{i}",
            "sec_openid": f"test_{i}",
            "sec_gift_id": "n1/Dg1905sj1FyoBlQBvmbaDZFBNaKuKZH6zxHkv8Lg5x2cRfrKUTb8gzMs=",
            "gift_num": 1,
            "gift_value": 0,
            "avatar_url": "",
            "nickname": f"test_{i}",  # 可自增或随机
            "timestamp": int(time.time() * 1000),  # 当前毫秒时间戳
            "audience_sec_open_id": "12321",
        }]
        resp = requests.post(Test_URL, json=payload, headers=HEADERS)
        print(f"[{i}] msg_id=hxz_test_{i} | status={resp.status_code}")
        time.sleep(interval)

if __name__ == "__main__":
    auto_join(count=100, interval=0.5)
