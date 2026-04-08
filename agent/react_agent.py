import re
from typing import Iterable

from langchain.agents import create_agent
from model.factory import get_chat_model
from utils.prompt_loader import load_system_prompts
from agent.tools.agent_tools import (
    rag_summarize,
    get_weather,
    get_user_location,
    get_user_id,
    get_current_month,
    list_report_months,
    fetch_latest_external_data,
    get_user_profile,
    fetch_external_data,
    fill_context_for_report,
)
from agent.tools.middleware import monitor_tool, log_before_model, report_prompt_switch



class ReactAgent:
    COMMON_CITIES = [
        "北京", "上海", "广州", "深圳", "杭州", "苏州", "南京", "成都", "重庆", "天津",
        "武汉", "西安", "长沙", "青岛", "宁波", "厦门", "郑州", "合肥", "福州", "济南",
    ]
    INVALID_CITY_VALUES = {"哪个城市", "什么城市", "哪座城市", "哪个市", "哪里", "哪儿"}

    def __init__(self):
        self.agent = create_agent(
            model=get_chat_model(),
            system_prompt=load_system_prompts(),
            tools=[rag_summarize, get_weather, get_user_location, get_user_id,
                   get_current_month, list_report_months, fetch_latest_external_data,
                   get_user_profile, fetch_external_data, fill_context_for_report],
            middleware=[monitor_tool, log_before_model, report_prompt_switch],
        )

    @staticmethod
    def _normalize_messages(messages: Iterable[dict]) -> list[dict]:
        normalized = []
        for message in messages:
            role = message.get("role")
            content = (message.get("content") or "").strip()
            if role not in {"user", "assistant"} or not content:
                continue
            normalized.append({"role": role, "content": content})
        return normalized

    @classmethod
    def _extract_session_facts(cls, messages: list[dict]) -> dict:
        facts = {}

        for message in messages:
            content = (message.get("content") or "").strip()
            if not content:
                continue

            for city in cls.COMMON_CITIES:
                if city in content:
                    facts["city"] = city

            city_match = re.search(
                r"(?:在|住在|来自|位于)([^\s，。！？,.!?]{2,12}(?:市|县|区|北京|上海|广州|深圳|杭州|苏州|南京|成都|重庆|天津|武汉|西安|长沙|青岛|宁波|厦门|郑州|合肥|福州|济南))",
                content,
            )
            if city_match:
                candidate_city = city_match.group(1)
                if candidate_city not in cls.INVALID_CITY_VALUES:
                    facts["city"] = candidate_city

            user_id_match = re.search(r"(?:用户ID|ID|id)[：:\s]*([0-9]{3,})", content)
            if user_id_match:
                facts["user_id"] = user_id_match.group(1)

        return facts

    def execute_stream(self, messages: list[dict]):
        normalized_messages = self._normalize_messages(messages)
        session_facts = self._extract_session_facts(normalized_messages)
        input_dict = {"messages": normalized_messages}

        # 第三个参数context就是上下文runtime中的信息，就是我们做提示词切换的标记
        for chunk in self.agent.stream(
            input_dict,
            stream_mode="values",
            context={"report": False, "session_facts": session_facts},
        ):
            latest_message = chunk["messages"][-1]
            # 仅向前端透出最终回答，避免展示中间的工具规划与思考文本。
            if (
                getattr(latest_message, "type", "") == "ai"
                and not getattr(latest_message, "tool_calls", None)
                and latest_message.content
            ):
                yield latest_message.content.strip() + "\n"



if __name__ == '__main__':
    agent = ReactAgent()
    res = agent.execute_stream([{"role": "user", "content": "扫地机器人在我所在地区的气温下如何保养"}])
    for chunk in res:
        print(chunk, end="", flush=True)
