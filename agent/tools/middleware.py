from typing import Callable
from utils.prompt_loader import load_system_prompts, load_report_prompts
from langchain.agents import AgentState
from langchain.agents.middleware import wrap_tool_call, before_model, dynamic_prompt, ModelRequest
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import Command
from utils.logger_handler import logger



@wrap_tool_call
def monitor_tool(
        # 请求的数据封装
        request: ToolCallRequest,
        # 执行的函数本身
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:             # 工具执行的监控
    """统一记录工具调用日志，并在必要时修改 runtime context。"""
    tool_name = request.tool_call.get("name", "unknown_tool")
    tool_args = request.tool_call.get("args", {})
    logger.info(f"[tool monitor]执行工具：{tool_name}")
    logger.info(f"[tool monitor]传入参数：{tool_args}")

    try:
        result = handler(request)
        logger.info(f"[tool monitor]工具{tool_name}调用成功")

        # 报告模式不靠模型自己记忆，而是由专门工具显式打开上下文开关。
        if tool_name == "fill_context_for_report":
            request.runtime.context["report"] = True

        return result
    except Exception as e:
        logger.error(f"工具{tool_name}调用失败，原因：{str(e)}", exc_info=True)
        return ToolMessage(
            content=f"工具{tool_name}调用失败：{str(e)}",
            tool_call_id=request.tool_call.get("id", tool_name),
        )


@before_model
def log_before_model(
        state: AgentState,          # 整个Agent智能体中的状态记录
        runtime: Runtime,           # 记录了整个执行过程中的上下文信息
):         # 在模型执行前输出日志
    """在每轮模型调用前输出简要日志，方便定位对话链路。"""
    logger.info(f"[log_before_model]即将调用模型，带有{len(state['messages'])}条消息。")

    logger.debug(f"[log_before_model]{type(state['messages'][-1]).__name__} | {state['messages'][-1].content.strip()}")

    return None


@dynamic_prompt                 # 每一次在生成提示词之前，调用此函数
def report_prompt_switch(request: ModelRequest):     # 动态切换提示词
    """根据 runtime context 动态拼接主提示词、报告提示词和会话事实。"""
    is_report = request.runtime.context.get("report", False)
    session_facts = request.runtime.context.get("session_facts", {})
    facts_prompt = ""
    if session_facts:
        # 这里把历史中抽取出的稳定事实显式塞进提示词，降低模型遗忘概率。
        fact_lines = [f"- {key}: {value}" for key, value in session_facts.items()]
        facts_prompt = "\n\n已知会话事实：\n" + "\n".join(fact_lines) + "\n请优先使用这些历史事实回答，不要忽略用户之前已经明确提到的信息。"
    if is_report:               # 是报告生成场景，返回报告生成提示词内容
        return load_report_prompts() + facts_prompt

    return load_system_prompts() + facts_prompt
