import httpx
import base64
import warnings
from typing import Optional
from dataclasses import dataclass

from openai import OpenAI

from api_config import AI_Config

# 忽略 SSL 证书验证警告（Windows 环境证书链不完整时需跳过）
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

# 系统提示词
SYSTEM_PROMPT = """
    你是Protobuf协议专家，精通proto2/proto3语法，能完成以下任务：
    1. 补全不完整的Protobuf定义（补全字段、tag、注释、类型）；
    2. 为Protobuf字段添加清晰的业务注释；
    3. 无完整proto时，分析二进制数据（Base64编码）的字段含义；
    4. 将自然语言业务描述转为合法的Protobuf定义；
    5. 检测Protobuf定义错误（如tag冲突、类型不匹配）并给出修复方案。
    输出仅返回Protobuf内容或解析结果，不添加多余解释。"""

_deepseek_client = None
_dashscope_client = None


@dataclass
class AIProtobufHelper:
    """统一的生成结果"""
    success: bool
    error: str = ""

    @staticmethod
    def _get_deepseek():
        """deepseek OpenAI"""
        global _deepseek_client
        if _deepseek_client is None:
            _deepseek_client = OpenAI(
                api_key=AI_Config.API_KEY,
                base_url=AI_Config.BASE_URL,
                http_client=httpx.Client(verify=False),
            )
        return _deepseek_client
    def _call_deepseek(self, user_message: str) -> str:
        """deepseek OpenAI"""
        client = AIProtobufHelper._get_deepseek()
        try:
            resp = client.chat.completions.create(
                model="deepseek-v4-flash",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.1
            )
            raw = resp.choices[0].message.content
            return raw
        except Exception as e:
            err_msg = str(e)
            if "auth" in err_msg.lower() or "401" in err_msg:
                return "[ERROR] 认证失败，请检查 API_KEY 是否有效"
            return f"[ERROR] AI调用失败: {err_msg}"

    def complete_proto(self,incomplete: str, business_desc: Optional[str] = None) -> str:
        """AI补全Protobuf定义+添加注释"""
        user_prompt = f"""补全以下不完整的Protobuf定义，并为每个字段添加业务注释（基于业务描述：{business_desc}）：
        要求：
        1. 补全缺失的字段tag、类型、必填/可选标记；
        2. 符合proto3语法；
        3. 注释清晰，贴合业务含义；
        4. 若有重复tag，自动修正。

        不完整的proto：
        {incomplete}"""
        return self._call_deepseek(user_prompt)

    def parse_binary_without_proto(self, binary_data: bytes, hint: Optional[str] = None) -> str:
        """无proto时，AI解析二进制数据"""
        # 二进制数据转Base64（方便LLM处理）
        b64_data = base64.b64encode(binary_data).decode("utf-8")
        user_prompt = f"""分析以下Base64编码的Protobuf二进制数据，推测字段含义和结构：
        提示（业务类型）：{hint}
        要求：
        1. 输出结构化的字段列表（tag、类型、推测值、业务含义）；
        2. 若无法确定，标注“未知”；
        3. 给出可能的Protobuf定义片段。

        Base64数据：{b64_data}"""
        return self._call_deepseek(user_prompt)

    def nl_to_proto(self, natural_language: str) -> str:
        """自然语言转Protobuf定义"""
        user_prompt = f"""将以下自然语言业务描述转为合法的proto3定义：
        要求：
        1. 字段名符合Protobuf规范（小写下划线）；
        2. 合理分配tag（从1开始）；
        3. 添加必要的注释；
        4. 包含message定义，名称为BusinessData。

        业务描述：{natural_language}"""
        return self._call_deepseek(user_prompt)

    def debug_proto_error(self, proto_content: str, error_msg: str) -> str:
        """AI定位Protobuf调试错误并给出修复方案"""
        user_prompt = f"""分析以下Protobuf定义的错误，并给出修复方案：
        错误信息：{error_msg}
        Protobuf定义：{proto_content}
        要求：
        1. 指出错误位置和原因；
        2. 输出修复后的完整proto定义；
        3. 给出调试建议。"""
        return self._call_deepseek(user_prompt)
