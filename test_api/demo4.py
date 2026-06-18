"""
AI修图脚本 - demo4.py
功能：指定本地图片 → AI分析图片内容生成提示词 → 调用图像生成API修图 → 保存结果
用法：
  python demo4.py                          # 默认处理 icon/1.png
  python demo4.py --image icon/1.png       # 指定图片路径
  python demo4.py --image icon/1.png --prompt "将其改为赛博朋克风格"  # 自定义修图指令
"""

import base64
import json
import os
import sys
import time
import argparse
from pathlib import Path

import requests


# ===================== 配置 =====================

class Config:
    # DeepSeek API 配置（复用项目 api_config）
    BASE_URL = "https://api.deepseek.com/v1"
    API_KEY = "sk-7e65bce01c0b4520a4b8ba4296d29788"

    # 图像生成接口（需要支持图片编辑的API）
    # 如果用的是 DeepSeek 且不支持图像生成，可替换为其他支持图像编辑的API
    # 例如硅基流动(SiliconFlow)、智谱(CogView)、百度文心等
    IMAGE_GEN_URL = "https://api.siliconflow.cn/v1/images/generations"
    IMAGE_GEN_KEY = ""  # 填入你的图像生成API Key

    # 输出目录
    OUTPUT_DIR = "output"

    # 默认图片路径
    DEFAULT_IMAGE = os.path.join("icon", "1.png")


# ===================== 图片编码 =====================

def encode_image_to_base64(image_path: str) -> tuple[str, str]:
    """将本地图片编码为 base64，返回 (base64_str, mime_type)"""
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"图片不存在: {image_path}")

    suffix_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }
    mime = suffix_map.get(path.suffix.lower(), "image/png")

    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return b64, mime


def get_image_url(image_path: str) -> str:
    """生成 data URI 格式的图片URL"""
    b64, mime = encode_image_to_base64(image_path)
    return f"data:{mime};base64,{b64}"


# ===================== AI 图片分析（生成提示词） =====================

def analyze_image(image_path: str) -> str:
    """
    用AI视觉模型分析图片内容，生成适合图像编辑的英文提示词。
    使用DeepSeek的视觉理解能力。
    """
    print(f"[1/3] 正在分析图片: {image_path}")
    image_url = get_image_url(image_path)

    system_prompt = """You are an expert image analyst and prompt engineer. 
When given an image, analyze its content in detail and generate an English prompt 
suitable for AI image generation/editing. The prompt should:
1. Describe the main subject, style, colors, composition
2. Be detailed enough to recreate a similar image
3. Use descriptive keywords separated by commas
4. Include style references (e.g., "digital art", "photorealistic", "illustration")
5. Be in English, concise but comprehensive

Output ONLY the prompt text, nothing else."""

    resp = requests.post(
        f"{Config.BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {Config.API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": image_url},
                        },
                        {
                            "type": "text",
                            "text": "Analyze this image and generate a detailed prompt that can be used to recreate or edit it with an AI image generator.",
                        },
                    ],
                },
            ],
            "max_tokens": 500,
            "temperature": 0.7,
        },
        timeout=60,
    )

    resp.raise_for_status()
    prompt = resp.json()["choices"][0]["message"]["content"].strip()
    print(f"      生成提示词: {prompt[:100]}...")
    return prompt


# ===================== 图像生成/编辑 =====================

def generate_image(prompt: str, reference_image_path: str = None, user_edit_prompt: str = None) -> str:
    """
    调用图像生成API，支持参考图片+编辑指令。
    返回生成图片的URL。
    
    注意：不同平台的图像编辑API接口不同，这里提供通用框架。
    请根据实际使用的API调整此函数。
    """
    print(f"[2/3] 正在生成图片...")

    # 合并提示词：原始分析 + 用户自定义编辑指令
    final_prompt = prompt
    if user_edit_prompt:
        final_prompt = f"{prompt}, {user_edit_prompt}"

    # ==================== 方案1：硅基流动（SiliconFlow）====================
    # 支持图生图（img2img），需要 IMAGE_GEN_KEY
    if Config.IMAGE_GEN_KEY:
        headers = {
            "Authorization": f"Bearer {Config.IMAGE_GEN_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "stabilityai/stable-diffusion-3-5-large",  # 可换模型
            "prompt": final_prompt,
            "image_size": "1024x1024",
            "batch_size": 1,
            "num_inference_steps": 20,
        }

        # 如果有参考图，尝试img2img
        if reference_image_path and Path(reference_image_path).exists():
            b64, mime = encode_image_to_base64(reference_image_path)
            payload["image"] = f"data:{mime};base64,{b64}"
            payload["strength"] = 0.7  # 变化强度 0-1

        resp = requests.post(
            Config.IMAGE_GEN_URL,
            headers=headers,
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()

        if "images" in data and len(data["images"]) > 0:
            image_url = data["images"][0].get("url", "")
            if image_url:
                print(f"      生成成功，图片URL已获取")
                return image_url

    # ==================== 方案2：DeepSeek + DALL-E风格（通用OpenAI兼容）====================
    print("      [INFO] 未配置图像生成API Key，将输出提示词供手动使用。")
    print("      [INFO] 如需自动生成，请配置 Config.IMAGE_GEN_KEY")
    return None


# ===================== 下载 & 保存 =====================

def download_image(url: str, save_path: str) -> str:
    """下载图片并保存到本地"""
    print(f"[3/3] 正在下载图片...")
    resp = requests.get(url, timeout=60, stream=True)
    resp.raise_for_status()

    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    with open(save_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    print(f"      已保存: {save_path}")
    return save_path


def save_prompt_text(prompt: str, user_edit: str, save_path: str):
    """将提示词保存为文本文件"""
    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    with open(save_path, "w", encoding="utf-8") as f:
        f.write(f"=== 图片分析提示词 ===\n{prompt}\n\n")
        if user_edit:
            f.write(f"=== 用户编辑指令 ===\n{user_edit}\n\n")
            f.write(f"=== 合并后提示词 ===\n{prompt}, {user_edit}\n")
    print(f"      提示词已保存: {save_path}")


# ===================== 主流程 =====================

def main():
    parser = argparse.ArgumentParser(description="AI修图工具 - 分析图片内容并生成修图提示词")
    parser.add_argument("--image", "-i", default=Config.DEFAULT_IMAGE,
                        help="输入图片路径（默认: icon/1.png）")
    parser.add_argument("--prompt", "-p", default=None,
                        help="自定义修图指令，如'将其改为赛博朋克风格'")
    parser.add_argument("--output", "-o", default=None,
                        help="输出目录（默认: output）")
    args = parser.parse_args()

    # 检查图片是否存在
    if not Path(args.image).exists():
        print(f"[ERROR] 图片不存在: {args.image}")
        print(f"[INFO]   请将图片放到 icon/ 文件夹，或用 --image 指定路径")
        sys.exit(1)

    # 输出目录
    output_dir = args.output or Config.OUTPUT_DIR
    stem = Path(args.image).stem
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    print(f"\n{'='*60}")
    print(f"  AI修图工具")
    print(f"  输入图片: {args.image}")
    print(f"  修图指令: {args.user_prompt or '无（仅分析）'}")
    print(f"{'='*60}\n")

    # Step 1: 分析图片，生成提示词
    prompt = analyze_image(args.image)

    # Step 2: 保存提示词
    prompt_path = os.path.join(output_dir, f"{stem}_prompt_{timestamp}.txt")
    save_prompt_text(prompt, args.prompt, prompt_path)

    # Step 3: 尝试生成图片
    image_url = generate_image(prompt, reference_image_path=args.image, user_edit_prompt=args.prompt)

    if image_url:
        img_path = os.path.join(output_dir, f"{stem}_edited_{timestamp}.png")
        download_image(image_url, img_path)
        print(f"\n[DONE] 修图完成!")
        print(f"       原图: {args.image}")
        print(f"       修图: {img_path}")
        print(f"       提示词: {prompt_path}")
    else:
        print(f"\n[DONE] 提示词生成完成（未配置图像生成API，仅输出提示词）")
        print(f"       提示词: {prompt_path}")
        print(f"\n       提示词内容:\n")
        print(f"       {prompt}")
        if args.prompt:
            print(f"\n       + 用户指令: {args.prompt}")
            print(f"       = 合并: {prompt}, {args.prompt}")


if __name__ == "__main__":
    main()
