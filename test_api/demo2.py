import httpx
from openai import OpenAI
from api_config import AI_Config

# 创建不验证SSL证书的httpx客户端（⚠️仅用于开发环境，生产环境禁止使用）
http_client = httpx.Client(verify=False)

# 接入AI接口 -- DeepSeek
client = OpenAI(
    api_key=AI_Config.API_KEY,
    base_url=AI_Config.BASE_URL,
    http_client=http_client
)

# 自动化测试用例生成
def generate_api_cases(api_info):
    prompt = f"""
        你是一个资深接口测试工程师，基于以下信息生成我的自动化接口测试用例:
        接口信息:{api_info}

        要求:
        1. 覆盖正常场景、边界场景、异常场景(参数缺失/类型错误/越界/重复请求)；
        2. 每条用例包含:用例名称、请求参数、预期结果；
        3. 按接口拆分用例，每个接口的用例单独分组；
        4. 仅输出结构化文本（每行一条用例，格式：[接口名] 用例名称 | 请求参数 | 预期结果），不做额外解释；
        5. 严格按照接口信息中的参数规则、边界场景生成，不编造不存在的参数/场景。
        """

    response = client.chat.completions.create(
        model = "deepseek-v4-flash", # DeepSeek模型
        messages = [{"role":"user", "content":prompt}],
        temperature= 0.3 #控制AI的随机性,越小越稳定
    )

    return response.choices[0].message.content

if __name__ == "__main__":
    api_info = """
    接口基础信息:
      完整域名: https://wwyd.vip.hnhxzkj.com
      请求方式: POST（所有接口均为 POST）
      Headers 固定参数:
        - User-Agent: Dalvik/2.1.0 (Linux; U; Android 12; V2366GA Build/55cac2b.0)
        - Host: wwyd.vip.hnhxzkj.com
        - Authorization: Bearer {token}（登录成功后由系统自动注入，登录接口不需要）
      响应结构: {"code": 0成功/非0失败, "msg": "提示信息", "data": {...} 或 null}

    接口1 - 发送短信验证码:
      接口路径: /api/login/send_sms
      请求参数（JSON body）:
        - phone: string, 必填, 手机号, 示例: "13227367247"
      预期响应: code=500, msg="本次测试验证码为:1111", data=[]
      边界: 已注册手机号 / 未注册手机号 / 格式错误手机号

    接口2 - 验证码登录（登录接口）:
      接口路径: /api/login/index
      请求参数（JSON body）:
        - platform: string 或 integer, 必填, 平台标识, 示例: "4"（Android微信登录）
        - phone: string, 必填, 手机号, 示例: "13227367247"
        - sms_code: string, 必填, 短信验证码, 示例: "1111"
      预期响应: code=0, msg="ok", data.token=登录令牌字符串
      边界: 正确验证码 / 错误验证码 / platform参数错误 / 手机号不匹配

    接口3 - 获取用户信息:
      接口路径: /api/user/info
      Headers: 需携带 Authorization（Bearer token，登录成功后获取）
      请求参数（JSON body）: 空对象 {}
      预期响应: code=0, msg="ok", data={用户信息}
      边界: 带有效token / token过期或无效

    接口4 - 小游戏开启:
      接口路径: /api/user/game_start
      Headers: 需携带 Authorization
      请求参数（JSON body）:
        - type: string, 必填, 游戏类型, 取值: "game_one" / "game_two" / "game_three"
      预期响应: code=0, msg="ok", data.game_id=游戏会话ID（后续结算需要）
      边界: type有效值 / type无效值

    接口5 - 小游戏结算:
      接口路径: /api/user/game_over
      Headers: 需携带 Authorization
      请求参数（JSON body）:
        - type: string, 必填, 同开启接口
        - game_id: string, 必填, 开启接口返回的会话ID, 示例: "G177915563949470"
        - score: integer, 必填, 游戏得分, 示例: 222
      预期响应: code=0, msg="ok"
      边界: 正确game_id+score / game_id错误 / score超限

    接口6 - 接收心情数据:
      接口路径: /api/mood/receive
      Headers: 需携带 Authorization
      请求参数（JSON body）:
        - id: integer, 必填, 心情值ID, 示例: 1
      预期响应: code=0可领取 / code=500且msg="未达到对应心情值"不可领 / msg="该奖励已领取"已领
      边界: 未达条件 / 可领取 / 已领取

    接口7 - 购买服装/道具:
      接口路径: /api/dress/buy
      Headers: 需携带 Authorization
      请求参数（JSON body）:
        - dress_id: integer, 必填, 服装ID, 示例: 2003（有效）/ 6003（无效测试）
        - is_bind: boolean, 必填, 是否绑定, 示例: true
      预期响应: code=0成功 / code=500且msg="配置表错误"（dress_id无效）
      边界: 有效dress_id / 无效dress_id / dress_id类型错误
    """
    cases = generate_api_cases(api_info)
    print("AI生成的测试用例:  \n", cases)
