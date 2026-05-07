import os

from utils.config_handler import agent_conf, chroma_conf, prompts_conf, rag_conf
from utils.path_tool import get_abs_path


def validate_runtime() -> list[str]:
    """
    启动前自检。

    返回值是问题列表；为空表示当前运行环境满足启动要求。
    """
    issues = []

    if not os.getenv("DASHSCOPE_API_KEY"):
        issues.append("缺少环境变量 DASHSCOPE_API_KEY，请先在运行环境中配置后再启动应用。")

    # 这些路径缺任何一个，应用都无法完整工作。
    required_paths = [
        ("主提示词", prompts_conf.get("main_prompt_path")),
        ("RAG 提示词", prompts_conf.get("rag_summarize_prompt_path")),
        ("报告提示词", prompts_conf.get("report_prompt_path")),
        ("知识库目录", chroma_conf.get("data_path")),
        ("外部数据文件", agent_conf.get("external_data_path")),
    ]
    for label, relative_path in required_paths:
        if not relative_path:
            issues.append(f"{label}未在配置中声明。")
            continue
        abs_path = get_abs_path(relative_path)
        if not os.path.exists(abs_path):
            issues.append(f"{label}不存在: {abs_path}")

    # 模型配置和向量库配置属于“缺了就不该继续运行”的硬依赖。
    for key in ("chat_model_name", "embedding_model_name"):
        if not rag_conf.get(key):
            issues.append(f"模型配置缺失: {key}")

    for key in ("collection_name", "persist_directory", "data_path", "md5_hex_store"):
        if not chroma_conf.get(key):
            issues.append(f"向量库配置缺失: {key}")

    prompt_keys = (
        prompts_conf.get("main_prompt_path"),
        prompts_conf.get("rag_summarize_prompt_path"),
        prompts_conf.get("report_prompt_path"),
    )
    # 提示词如果不是 UTF-8，运行中很容易出现不可读字符串或直接报错。
    for relative_path in prompt_keys:
        if not relative_path:
            continue
        abs_path = get_abs_path(relative_path)
        if not os.path.exists(abs_path):
            continue
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                f.read()
        except UnicodeDecodeError:
            issues.append(f"提示词文件不是 UTF-8 编码: {abs_path}")

    return issues
