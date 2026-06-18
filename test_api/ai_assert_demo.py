from openai import OpenAI
from api_config import AI_Config
client = OpenAI(
    api_key= AI_Config.API_KEY,
    base_url= AI_Config.BASE_URL
)