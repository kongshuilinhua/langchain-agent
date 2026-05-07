"""
为整个工程提供统一的绝对路径
"""
import os


def get_project_root() -> str:
    """
    获取项目根目录。

    当前文件位于 utils/ 下，因此向上一层就是仓库根目录。
    """
    # 先拿到当前工具文件，再逐级回溯到项目根目录。
    current_file = os.path.abspath(__file__)
    current_dir = os.path.dirname(current_file)
    project_root = os.path.dirname(current_dir)
    return project_root

def get_abs_path(relative_path: str) -> str:
    """
    把项目内相对路径转换成绝对路径。
    """
    project_root = get_project_root()
    return os.path.abspath(os.path.join(project_root, relative_path))

if __name__ == '__main__':
    print(get_abs_path('data'))
