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

    def execute_stream(self, messages: list[dict]):
        input_dict = {"messages": self._normalize_messages(messages)}

        # 第三个参数context就是上下文runtime中的信息，就是我们做提示词切换的标记
        for chunk in self.agent.stream(input_dict, stream_mode="values", context={"report": False}):
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
