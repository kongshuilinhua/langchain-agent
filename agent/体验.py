from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate

# 1. 定义工具
@tool
def get_weather(location: str = "默认") -> str:
    """查询天气"""
    return "雨天"

# 2. 创建运行的 Prompt 模板
# 注意：使用 Agent 时，必须要有 {input} 作为用户输入，同时必须要有 {agent_scratchpad} 用来存储模型思考和调用工具的中间过程。
prompt = ChatPromptTemplate.from_messages([
    ("system", "你是一个聊天助手，可以回答用户问题"),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

# 3. 实例化模型和工具
model = ChatTongyi(model="qwen3-max")
tools = [get_weather]

# 4. 创建 Agent (决定下一步采取什么动作)
agent = create_tool_calling_agent(model, tools, prompt)

# 5. 创建 AgentExecutor (实际不停循环执行动作和调用的执行器)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

# 6. 调用模型
res = agent_executor.invoke(
    {
        "input": "明天天气如何？"
    }
)

print(res["output"])
