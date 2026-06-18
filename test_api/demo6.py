from openai import OpenAI
import httpx
import requests
import base64
import time
import os
import traceback
import urllib3
from api_config import AI_Config

# 禁用 SSL 证书验证警告（代理环境下常见）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 初始化OpenAI客户端（绕过SSL证书验证，适配代理环境）
client = OpenAI(
    api_key=AI_Config.DASHSCOPE_API_KEY,
    base_url=AI_Config.DASHSCOPE_BASE_URL,
    http_client=httpx.Client(verify=False)
)
Test_API_URL = "http://192.168.1.47:94/douyin/webcast/comment_notify"  #测试环境
API_URL = "https://zs-bjfyl-dy.danmu.hxzdm.com/douyin/webcast/comment_notify"  #正式环境

def img_to_base64(img_path: str) -> str:
    """
    图片转base64编码（支持PNG/JPG/JPEG）
    根据文件扩展名自动生成对应MIME类型，确保GPT-4o正确识别
    """
    # 获取文件扩展名，转为小写
    file_ext = os.path.splitext(img_path)[1].lower()

    # 支持的图片格式及对应MIME类型
    supported_formats = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg"
    }

    # 格式校验
    if file_ext not in supported_formats:
        raise ValueError(f"不支持的图片格式：{file_ext}，仅支持PNG/JPG/JPEG")

    # 读取图片并编码为base64
    with open(img_path, "rb") as f:
        img_bytes = f.read()
    base64_str = base64.b64encode(img_bytes).decode("utf-8")

    # 返回带正确MIME类型的base64字符串
    return f"data:{supported_formats[file_ext]};base64,{base64_str}"


def get_all_surname_by_ai(img_path: str) -> list:
    """AI识图：识别图片全部中文姓氏（单姓+复姓），返回姓氏列表"""
    try:
        img_b64 = img_to_base64(img_path)
        resp = client.chat.completions.create(
            model="qwen3.7-plus",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text",
                         "text": "识别图片中全部中文姓氏（包含单姓、复姓：上官/司马/欧阳等），只输出姓氏，多个姓氏用英文逗号分隔，不能加任何多余文字、符号、说明。无姓氏则直接返回空"},
                        {"type": "image_url", "image_url": {"url": img_b64}}
                    ]
                }
            ],
            max_tokens=3000
        )
        res_text = resp.choices[0].message.content.strip()
        if res_text == "" or res_text.lower() == "空":
            return []
        # 分割成姓氏列表
        surname_list = [s.strip() for s in res_text.split(",") if s.strip()]
        return surname_list
    except ValueError as e:
        print(f"图片格式错误：{str(e)}")
        return []
    except Exception as e:
        print(f"AI识图失败：{str(e)}")
        traceback.print_exc()
        return []


def send_seat_notify(surname: str):
    """单个姓氏发送落座接口，严格按照需求请求头+请求体格式"""
    # 固定请求头（和需求完全一致）
    headers = {
        "x-roomid": "12321",
        "X-Unity-Version": "2023.1.13f1",
        "User-Agent": "UnityPlayer/2023.1.13f1 (UnityWebRequest/1.0, libcurl/8.1.1-DEV)",
        "Content-Type": "application/json"
    }
    # 构造请求体：严格匹配示例格式，content=加入XX
    timestamp_ms = int(time.time() * 1000)  # 毫秒时间戳
    req_body = [
        {
            "msg_id": f"test_{surname}",
            "sec_openid": f"test_{surname}",
            "content": f"加入{surname}",
            "avatar_url": "",
            "nickname": f"test_{surname}",
            "timestamp": timestamp_ms
        }
    ]
    try:
        # POST发送接口
        res = requests.post(url=API_URL, headers=headers, json=req_body, timeout=10)
        if res.status_code == 200:
            print(f"【{surname}】落座消息发送成功｜接口返回：{res.text}")
        else:
            print(f"【{surname}】发送失败｜状态码：{res.status_code}，返回：{res.text}")
    except Exception as e:
        print(f"接口请求异常（核对{API_URL}地址）：{str(e)}")


if __name__ == "__main__":
    # E:\yebao\test_yaml\icon\test_1.png

    print("===== 姓氏识别+落座发送程序（支持PNG/JPG/JPEG，循环替换图片） =====")
    # 主循环：可无限替换图片
    while True:
        input_path = input("\n请输入图片本地路径(如D:/name.png)，输入exit结束程序：").strip()
        if input_path.lower() == "exit":
            print("程序退出")
            break
        # 检查文件是否存在
        if not os.path.exists(input_path):
            print("错误：文件不存在，请检查路径")
            continue
        # AI提取所有姓氏
        surname_arr = get_all_surname_by_ai(input_path)
        if len(surname_arr) == 0:
            print("图片未识别到任何姓氏，跳过发送")
            continue
        print(f"识别到姓氏列表：{surname_arr}")
        # 遍历逐个发送落座
        for s in surname_arr:
            send_seat_notify(s)