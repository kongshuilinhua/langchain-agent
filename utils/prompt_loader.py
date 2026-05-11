from utils.config_handler import prompts_conf
from utils.path_tool import get_abs_path
from utils.logger_handler import logger


def _load_prompt(config_key: str, prompt_name: str) -> str:
    try:
        prompt_path = get_abs_path(prompts_conf[config_key])
    except KeyError as e:
        logger.error(f"{prompt_name}路径未在配置文件中找到: {str(e)}")
        raise

    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.error(f"加载{prompt_name}失败: {str(e)}")
        raise


def load_system_prompts():
    return _load_prompt("main_prompt_path", "系统提示词")


def load_rag_prompts():
    return _load_prompt("rag_summarize_prompt_path", "RAG总结提示词")


def load_report_prompts():
    return _load_prompt("report_prompt_path", "报告提示词")

if __name__ == '__main__':
    print(load_rag_prompts())
