import os.path

from langchain_core.tools import tool
from rag.rag_service import RagSummarizeService
import random
from utils.config_handler import agent_conf
from utils.path_tool import get_abs_path
from utils.logger_handler import logger
rag = RagSummarizeService()

@tool(description="向量存储中检索资料")
def rag_summarize(query):
    return rag.rag_summarize(query)

@tool(description="获取指定城市天气信息")
def get_weather(city):
    return f"当前{city}的天气是晴朗，温度25摄氏度。南方10级风，湿度60%。"

@tool(description="获取用户的城市名称")
def get_user_location():
    return random.choice(["北京", "上海", "广州", "深圳", "杭州"])

@tool(description="获取用户的id")
def get_user_id():
    return str(random.randint(1, 100))

@tool(description="获取当前月份")
def get_current_month():
    return str(random.randint(1, 12))

external_data = {}

def generate_external_data():
    if external_data:
        return
    external_data_path = get_abs_path(agent_conf["external_data_path"])
    if not os.path.exists(external_data_path):
        raise FileNotFoundError(f"外部数据文件{external_data_path}不存在")

    with open(external_data_path, "r", encoding="utf-8") as f:
        for line in f.readlines():
            arr = line.strip().split(",")
            user_id = arr[0].replace('"', "")
            feature = arr[1].replace('"', "")
            efficiency = arr[2].replace('"', "")
            consumable = arr[3].replace('"', "")
            comparison = arr[4].replace('"', "")
            time = arr[5].replace('"', "")
            if user_id not in external_data:
                external_data[user_id] = {}
            external_data[user_id][time] = {
                "特征": feature,
                "效率": efficiency,
                "耗材": consumable,
                "对比": comparison,
            }


@tool(description="获取指定用户在指定月份的使用记录")
def fetch_external_data(user_id, month):
    generate_external_data()
    try:
        return external_data[user_id][month]
    except KeyError:
        logger.warning(f"未能检索到用户{user_id}在{month}的使用数据")
        return ""

@tool(description="调用后触发中间件自动为报告生成的场景动态注入上下文信息，为后续提示词切换提供上下文信息")
def fill_context_for_report():
    return "fill_context_for_report已调用"
