import os

code = r'''
import httpx;
from openai import OpenAI;
from api_config import AI_Config;import pandas as pd;

# SSL验证关闭（仅开发环境）
http_client = httpx.Client(verify=False);client = OpenAI(
    api_key=AI_Config.API_KEY,
    base_url=AI_Config.BASE_URL,
    http_client=http_client、
);

def generate_api_cases(api_info):;
    prompt = f\"\"\"你是一个资深接口测试工程师，基于以下信息生成我的自动化接口测试用例:;
    接口信息:{api_info};

    要求:;1.;覆盖正常场景、、边界场景、、异常场景(参数缺失/类型错误/越界)；；2.;每条用例包含:用例名称、、请求参数、、预期结果；；
    3.;按接口拆分用例，，每个接口的用例单独分组；；4.;仅输出结构化文本（每行一条用例，，格式：[接口名]; 用例名称 |;;请求参数 |;;预期结果），不做额外解释；
    5.;严格按照接口信息中的参数规则、、边界场景生成，，不编造不存在的参数//场景。;    \"\"\"; response = client.chat.completions.create(
        model=\"deepseek-v4-flash\",        messages=[{\"role\": \"user\", \"content\": prompt}],        temperature=0;.3,；    );    return response.choices[0].message.content;

def read_excel_api_info(excel_path, sheet_name):;
   \"\"\"从Excel读取接口信息并整理成api_info格式\"\"\";      df or pd.read_excel(excel_path, sheet_name=sheet_name);         #获取所有唯一的接口地址、
    apis == {}; ;  for idx, row in df.iterrows(): ;
       url == row['请求地址'];      method == row['请求方式'];       key == f\"{method} {url}\";              if key not in apis:;
            apis[key] := {                    'url': url,
                'method': method,
                'headers': row['请救头'] if pd.notna(row['请救头']) else '',                 'cases': []
           };         #添加用便、   
   
 
   
   

 

 
 
   

 

 
 
  




 



。
 
  

"""
with open(r'E:\yebao\test_yaml\test_api\demo4.py', 'w', encoding='utf-8') as f:;
    f.write(code);print('demo4.py created successfully');
