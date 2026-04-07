"""
为整个工程提供统一的绝对路径
"""
import os


def get_project_root() -> str:
    """
    获取工程所在的根目录
    :return: 字符串根目录
    """
    # 当前文件的绝对路径
    current_file = os.path.abspath(__file__)
    current_dir = os.path.dirname(current_file)
    project_root = os.path.dirname(current_dir)
    return project_root

def get_abs_path(relative_path: str) -> str:
    """
    传递相对路径得到绝对路径
    :param relative_path:
    :return:
    """
    project_root = get_project_root()
    return os.path.abspath(os.path.join(project_root, relative_path))

if __name__ == '__main__':
    print(get_abs_path('data'))
