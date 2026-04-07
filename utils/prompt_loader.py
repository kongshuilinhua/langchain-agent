from utils.config_handler import prompts_conf
from utils.path_tool import get_abs_path
from utils.logger_handler import logger
def load_system_prompts():
    try:
        system_prompt_path = get_abs_path(prompts_conf['main_prompt_path'])
    except KeyError as e:
        logger.error(f"系统提示词路径未在配置文件中找到: {str(e)}")
        raise e
    try:
        return open(system_prompt_path, "r", encoding="utf-8").read()
    except Exception as e:
        logger.error(f"加载系统提示词失败: {str(e)}")
        raise e

def load_rag_prompts():
    try:
        system_prompt_path = get_abs_path(prompts_conf['rag_summarize_prompt_path'])
    except KeyError as e:
        logger.error(f"RAG总结提示词路径未在配置文件中找到: {str(e)}")
        raise e
    try:
        return open(system_prompt_path, "r", encoding="utf-8").read()
    except Exception as e:
        logger.error(f"加载RAG总结提示词失败: {str(e)}")
        raise e

def load_report_prompts():
    try:
        system_prompt_path = get_abs_path(prompts_conf['report_prompt_path'])
    except KeyError as e:
        logger.error(f"报告提示词路径未在配置文件中找到: {str(e)}")
        raise e
    try:
        return open(system_prompt_path, "r", encoding="utf-8").read()
    except Exception as e:
        logger.error(f"加载报告提示词失败: {str(e)}")
        raise e

if __name__ == '__main__':
    print(load_rag_prompts())