import ast
import javalang
import os
import warnings
from loguru import logger
from git import Repo

warnings.filterwarnings(
    "ignore", category=SyntaxWarning, message="invalid escape sequence"
)


def get_commit_sha(path_to_repo: str):
    """
    获取仓库的commit sha
    """
    repo = Repo(path_to_repo)
    return repo.head.commit.hexsha


def extract_structure_from_pyfile(path_to_file: str, relpath: str):
    """
    从文件中提取类和函数的结构，包括:
    1. docstrings和以#开头的注释
    2. 函数和方法的参数

    返回一个字典structure，包含以下字段:
    - filepath: 文件路径
    - functions: 函数列表，每个函数是一个字典，包含以下字段:
        - name: 函数名
        - docstring: 函数的docstring
        - comments: 函数的注释
        - args: 函数的参数列表
    - classes: 类列表，每个类是一个字典，包含以下字段:
        - name: 类名
        - docstring: 类的docstring
        - comments: 类的注释
        - attributes: 类的属性列表
        - methods: 方法列表，每个方法是一个字典，包含以下字段:
            - name: 方法名
            - docstring: 方法的docstring
            - comments: 方法的注释
            - args: 方法的参数列表
    """
    with open(path_to_file, "r", encoding="utf-8") as f:
        try:
            source = f.read()
            tree = ast.parse(source, filename=path_to_file)
            lines = source.splitlines()
        except Exception as e:
            print(f"Error parsing file: {relpath}")
            print(e)
            return {"filepath": relpath, "functions": [], "classes": [], "elements": []}

    structure = {"file": relpath, "functions": [], "classes": [], "elements": []}
    add_parent_info(tree)  # 添加parent信息
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and isinstance(node.parent, ast.Module):
            # 获取函数的参数
            func_info = {
                "type": "function",
                "name": node.name,
                "docstring": ast.get_docstring(node),
                "comments": get_py_preceding_comments(lines, node.lineno),
                "args": [arg.arg for arg in node.args.args],
            }
            structure["functions"].append(func_info)
            structure["elements"].append(func_info)
        elif isinstance(node, ast.ClassDef):
            # 获取类的属性
            class_info = {
                "type": "class",
                "name": node.name,
                "docstring": ast.get_docstring(node),
                "comments": get_py_preceding_comments(lines, node.lineno),
                "methods": [],
                "attributes": [],
            }

            for class_node in node.body:
                if isinstance(class_node, ast.FunctionDef):
                    method_info = {
                        "name": class_node.name,
                        "docstring": ast.get_docstring(class_node),
                        "comments": get_py_preceding_comments(lines, class_node.lineno),
                        "args": [arg.arg for arg in class_node.args.args],
                    }
                    class_info["methods"].append(method_info)
                elif isinstance(class_node, ast.Assign):
                    for target in class_node.targets:
                        if isinstance(target, ast.Name):
                            class_info["attributes"].append(target.id)

            structure["classes"].append(class_info)
            structure["elements"].append(class_info)
    return structure


def get_py_preceding_comments(lines, lineno, max_lines=10) -> str:
    """
    获取位于指定行号前的连续注释行
    """
    comments = []
    index = lineno - 2  # 因为行号是从1开始，列表索引从0开始
    while index >= 0 and (lineno - index - 1) <= max_lines:
        line = lines[index].strip()
        if line.startswith("#"):
            # 去除#和前后的空白字符
            comment = line.lstrip("#").strip()
            comments.insert(0, comment)  # 将注释放在最前面
            index -= 1
        elif line == "":
            # 如果是空行，继续向上查找
            index -= 1
        else:
            # 如果遇到非注释且非空行，停止查找
            break
    if comments == []:
        return None
    return "\n".join(comments)


def add_parent_info(tree: ast.AST) -> None:
    """
    为AST节点添加parent属性，以便识别节点的父节点
    """
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node


def extract_structure_from_java_file(path_to_file: str, file_relpath: str) -> dict:
    """
    从Java文件中提取类和函数的结构，包括:
    1. 类和方法的注释
    2. 方法的参数

    返回一个字典
    """
    classes = []
    functions = []
    try:
        with open(path_to_file, "r", encoding="utf-8") as f:
            source = f.read()
        tree = javalang.parse.parse(source)
    except Exception as e:
        print(f"Error parsing file: {file_relpath}")
        print(e)
        return {"file": file_relpath, "functions": [], "classes": []}

    for path, node in tree:
        if isinstance(node, javalang.tree.ClassDeclaration):
            class_name = node.name
            class_comment = node.documentation
            class_methods = []
            for method in node.methods:
                method_name = method.name
                method_comment = method.documentation
                class_methods.append({"name": method_name, "comment": method_comment})
            classes.append(
                {
                    "name": class_name,
                    "comment": class_comment,
                    "functions": class_methods,
                }
            )
        elif isinstance(node, javalang.tree.MethodDeclaration):
            function_name = node.name
            function_comment = node.documentation
            functions.append({"name": function_name, "comment": function_comment})

    return {"file": file_relpath, "functions": functions, "classes": classes}


def get_java_preceding_comments(source, position, max_lines=10):
    """
    获取位于指定位置前的注释内容
    """
    comments = []
    lines = source.splitlines()
    line_number = source.count("\n", 0, position)
    index = line_number - 1

    # 向上查找注释
    while index >= 0 and len(comments) < max_lines:
        line = lines[index].strip()
        if line.startswith("//"):
            comments.insert(0, line.lstrip("//").strip())  # 行注释
        elif line.startswith("/*"):
            comment_block = [line.lstrip("/*").strip()]
            index -= 1
            while index >= 0 and not lines[index].startswith("*/"):
                comment_block.append(lines[index].strip())
                index -= 1
            comments.insert(0, "\n".join(comment_block))  # 块注释
        elif line == "":
            # 空行，继续查找
            pass
        else:
            break  # 遇到非注释且非空行停止查找
        index -= 1

    return "\n".join(comments)


def get_repo_structure(path_to_repo: str, language: str) -> dict:
    """
    从仓库中读取所有代码文件的类和函数的结构
    返回字典格式的结构
    """
    all_structure = []
    for root, dirs, files in os.walk(path_to_repo):
        for file in files:
            if language == "python" and file.endswith(".py"):
                file_path = os.path.join(root, file)
                file_relpath = os.path.relpath(file_path, path_to_repo)
                with open(file_path, "r", encoding="utf-8") as f:
                    try:
                        source = f.read()
                        tree = ast.parse(source, filename=file_path)
                        add_parent_info(tree)  # 添加parent信息
                    except Exception as e:
                        print(f"Error parsing file: {file_relpath}")
                        print(e)
                        all_structure.append(
                            {"file": file_relpath, "functions": [], "classes": [], "elements": []}
                        )
                        continue
                structure = extract_structure_from_pyfile(file_path, file_relpath)
                all_structure.append(structure)
            elif language == "java" and file.endswith(".java"):
                file_path = os.path.join(root, file)
                file_relpath = os.path.relpath(file_path, path_to_repo)
                structure = extract_structure_from_java_file(file_path, file_relpath)
                all_structure.append(structure)
    # structure_json = json.dumps(all_structure, indent=4)
    return all_structure


def get_repo_code_content(path_to_repo: str, language: str, mode: str = "all") -> dict:
    """
    从仓库中读取所有代码文件的类和函数的结构
    返回字典格式的结构
    """
    all_code = []
    for root, dirs, files in os.walk(path_to_repo):
        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                file_relpath = os.path.relpath(file_path, path_to_repo)
                with open(file_path, "r", encoding="utf-8") as f:
                    source = f.read()
                
                if mode == "all":
                    all_code.append(f"**FILE_PATH: {file_relpath}**\n```python\n{source}\n```")
                elif mode == "code" and not file_relpath.startswith("test"):
                    all_code.append(f"**FILE_PATH: {file_relpath}**\n```python\n{source}\n```")
                elif mode == "test" and file_relpath.startswith("test"):
                    all_code.append(f"**FILE_PATH: {file_relpath}**\n```python\n{source}\n```")
    if all_code == []:
        logger.error(f"No `{mode}` content found in {path_to_repo}")
        return ""
    return "\n\n".join(all_code)


def find_metadata(path_to_repo):
    """
    查找目录中的setup.py 或 pyproject.toml文件
    返回一个列表，是文件的相对path_to_repo的路径
    """
    metadata_files = []

    for root, _, files in os.walk(path_to_repo):
        for file in files:
            if file == "setup.py" or file == "pyproject.toml":
                rel_path = os.path.relpath(os.path.join(root, file), path_to_repo)
                metadata_files.append(rel_path)

    return metadata_files


def find_test_file(path_to_repo, language="python"):
    """
    查找该项目的测试代码路径
    参数：
    path_to_repo (str): 仓库目录
    language (str): 项目语言
    返回值：
    若有测试文件夹，返回一个列表，是测试文件夹或测试文件的相对path_to_repo的路径
    """
    test_file_path_list = []
    if language == "python":
        for root, dirs, files in os.walk(path_to_repo):
            for file in files:
                # 若文件名以 test_ 开头或以 _test 结尾，且是.py文件，则加入列表
                if (
                    file.lower().startswith("test_")
                    or file.lower().endswith("_test.py")
                ) and file.endswith(".py"):
                    relpath = os.path.relpath(os.path.join(root, file), path_to_repo)
                    test_file_path_list.append(relpath)
    return test_file_path_list


def get_test_files_content(path_to_repo, all_content=False):
    """
    获取所有测试文件的内容
    参数：
    path_to_repo (str): 仓库目录
    all_content (bool): 是否获取所有内容
    返回值：
    str: 所有测试文件的内容
    """
    test_file_path_list = find_test_file(path_to_repo, "python")
    test_file_content = ""
    for test_file_path in test_file_path_list:
        file_path = os.path.join(path_to_repo, test_file_path)
        if os.path.isfile(file_path) and file_path.endswith(".py"):
            with open(file_path, "r", encoding="utf-8") as f:
                test_file_content += (
                    '\nBelow content is from a testfile which path is: "'
                    + test_file_path
                    + '"\n'
                )
                if all_content:
                    test_file_content += f.read()
                else:
                    test_file_content += f.read(100000)
                test_file_content += f"End of test file {test_file_path}\n"
    return test_file_content


def get_all_python_files_content(path_to_repo):
    """
    获取所有python文件的内容
    参数：
    path_to_repo (str): 仓库目录
    返回值：
    str: 所有python文件的内容
    该函数会遍历所有子目录，读取每个python文件的前100000个字符
    """
    python_files_content = ""
    for root, _, files in os.walk(path_to_repo):
        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                python_files_content += (
                    f"\nBelow content is from python file {file_path}\n"
                )
                with open(file_path, "r", encoding="utf-8") as f:
                    python_files_content += f.read(100000)
                    python_files_content += f"End of python file {file_path}\n"
    return python_files_content


def get_structured_tests(path_to_repo):

    def add_parent_info(tree: ast.AST) -> None:
        """
        为AST节点添加parent属性，以便识别节点的父节点
        """
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                child.parent = node

    def get_function_source(file_content, node):
        """
        获取函数的源代码
        """
        # 获取函数的起始行和结束行
        start_line = node.lineno - 1  # AST的行号从1开始，而字符串列表索引从0开始
        end_line = node.end_lineno if hasattr(node, "end_lineno") else start_line

        # 分割文件内容为行
        lines = file_content.split("\n")

        # 提取函数的源代码
        function_lines = lines[start_line:end_line]

        # 合并为完整的函数实现
        function_source = "\n".join(function_lines)

        return function_source

    structured_test_list = []
    test_file_path_list = find_test_file(path_to_repo, "python")
    current_id = 1  # 给每个测试点分配唯一 ID
    for test_file_path in test_file_path_list:
        file_path = os.path.join(path_to_repo, test_file_path)
        # 利用ast模块解析python文件
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                file_content = f.read()
                tree = ast.parse(file_content, filename=file_path)
                add_parent_info(tree)  # 添加parent信息
                for node in ast.walk(tree):
                    # 只处理函数定义
                    if isinstance(node, ast.FunctionDef):
                        # 只处理以test_开头的函数
                        if node.name.startswith("test_"):
                            # 获取函数的类名
                            class_name = None
                            if hasattr(node, "parent") and isinstance(
                                node.parent, ast.ClassDef
                            ):
                                class_name = node.parent.name

                            # 获取函数的完整实现
                            test_implementation = get_function_source(
                                file_content, node
                            )

                            structured_test_list.append(
                                dict(
                                    id=current_id,
                                    test_file_path=test_file_path,
                                    test_class=class_name,
                                    test_method=node.name,
                                    test_implementation=test_implementation,
                                )
                            )
                            current_id += 1
        except SyntaxError:
            print(f"无法解析 {file_path}，跳过该文件（语法错误）")
            continue
        except Exception as e:
            print(f"处理文件 {file_path} 时发生错误：{str(e)}")
            continue

    return structured_test_list


def get_pyfile_content(path_to_repo):
    """
    获取所有python文件的内容
    参数：
    path_to_repo (str): 仓库目录
    返回值：
    str: 所有python文件的内容
    """
    pyfile_content = ""
    for root, _, files in os.walk(path_to_repo):
        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                with open(file_path, "r", encoding="utf-8") as f:
                    pyfile_content += (
                        f"\nBelow content is from python file {file_path}\n"
                    )
                    pyfile_content += f.read(100000)
                    pyfile_content += f"End of python file {file_path}\n"
    return pyfile_content


def get_readme_content(path_to_repo):
    """
    根据优先级获取仓库的 README 内容（支持 .md > .rst > .txt）

    参数：
        path_to_repo (str): 仓库本地路径

    返回：
        str: README 内容（前100000字符），找不到时返回空字符串
    """
    # 按优先级定义可能的文件名
    readme_files = ["README.md", "README.rst", "README.txt"]

    # 按优先级查找存在的文件
    for filename in readme_files:
        readme_path = os.path.join(path_to_repo, filename)
        if os.path.exists(readme_path):
            try:
                with open(readme_path, "r", encoding="utf-8", errors="ignore") as f:
                    return f.read(100000)
            except Exception as e:
                logger.error(f"Failed to read {filename} : {str(e)}")
                return ""

    return ""


def count_python_files(repo_dir):
    """
    计算指定目录下的python文件数量
    参数：
    repo_dir (str): 仓库目录
    """
    count = 0
    for root, _, files in os.walk(repo_dir):
        for file in files:
            if file.endswith(".py"):
                count += 1
    return count


def count_java_files(repo_dir):
    """
    计算指定目录下的java文件数量
    参数：
    repo_dir (str): 仓库目录
    """
    count = 0
    for root, _, files in os.walk(repo_dir):
        for file in files:
            if file.endswith(".java"):
                count += 1
    return count


def count_python_code_lines(repo_dir):
    """
    计算指定目录下的python代码行数
    参数：
    repo_dir (str): 仓库目录
    """
    if os.path.isdir(repo_dir):
        count = 0
        for root, _, files in os.walk(repo_dir):
            for file in files:
                if file.endswith(".py"):
                    with open(
                        os.path.join(root, file), "r", encoding="utf-8", errors="ignore"
                    ) as f:
                        count += len(f.readlines())
        return count
    else:
        with open(repo_dir, "r", encoding="utf-8", errors="ignore") as f:
            return len(f.readlines())


def count_java_code_lines(repo_dir):
    """
    计算指定目录下的java代码行数
    参数：
    repo_dir (str): 仓库目录
    """
    count = 0
    for root, _, files in os.walk(repo_dir):
        for file in files:
            if file.endswith(".java"):
                with open(
                    os.path.join(root, file), "r", encoding="utf-8", errors="ignore"
                ) as f:
                    count += len(f.readlines())
    return count


def count_python_comment_lines(repo_dir):
    """
    计算指定目录下的Python注释行数，包括：
    - 以#开头的行
    - 多行三引号（'''或\"\"\"）注释块内的行
    - 行尾的#注释（不在字符串中时）
    参数：
    repo_dir (str): 仓库目录
    """
    count = 0
    for root, _, files in os.walk(repo_dir):
        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        in_triple_block = False
                        block_quote_type = None
                        for line in f:
                            stripped_line = line.lstrip()  # 忽略前导空白字符
                            if in_triple_block:
                                # 处于三引号块中，该行计数
                                count += 1
                                # 检查是否结束三引号块
                                end_quote_idx = line.find(block_quote_type)
                                if end_quote_idx != -1:
                                    # 切换状态，可能该行后面还有其他内容
                                    in_triple_block = False
                                    block_quote_type = None
                            else:
                                # 检查是否开始三引号块
                                if stripped_line.startswith(
                                    '"""'
                                ) or stripped_line.startswith("'''"):
                                    quote_type = (
                                        '"""'
                                        if stripped_line.startswith('"""')
                                        else "'''"
                                    )
                                    # 统计该行中的引号数量
                                    quote_count = line.count(quote_type)
                                    # 判断是否成对闭合
                                    if quote_count % 2 != 0:
                                        # 奇数，块未闭合，进入块状态
                                        in_triple_block = True
                                        block_quote_type = quote_type
                                        count += 1
                                    else:
                                        # 在同一行开始并结束，算作注释行
                                        count += 1
                                else:
                                    # 处理单行注释和行尾注释
                                    if stripped_line.startswith("#"):
                                        count += 1
                                    else:
                                        # 检查行中是否有不在字符串中的#
                                        in_string = False
                                        current_quote = None
                                        escape = False
                                        for i, char in enumerate(line):
                                            if escape:
                                                escape = False
                                                continue
                                            if char == "\\":
                                                escape = True
                                                continue
                                            if in_string:
                                                # 处理字符串中的字符
                                                if char == current_quote:
                                                    # 结束字符串
                                                    in_string = False
                                                    current_quote = None
                                                elif (
                                                    len(current_quote) == 3
                                                    and i + 2 < len(line)
                                                    and line[i : i + 3] == current_quote
                                                ):
                                                    # 处理三引号结束
                                                    in_string = False
                                                    current_quote = None
                                                    i += 2  # 跳过剩余两个字符
                                            else:
                                                if char == "#":
                                                    # 找到注释
                                                    count += 1
                                                    break
                                                elif char in ('"', "'"):
                                                    # 检查是否是三引号
                                                    if (
                                                        i + 2 < len(line)
                                                        and line[i + 1] == char
                                                        and line[i + 2] == char
                                                    ):
                                                        current_quote = char * 3
                                                        in_string = True
                                                        i += 2  # 跳过接下来的两个字符
                                                    else:
                                                        current_quote = char
                                                        in_string = True
                except Exception as e:
                    logger.error(f"Error processing file {file_path}: {e}")
    return count


def count_java_comment_lines(repo_dir):
    """
    统计Java代码注释行数，包括：
    - 单行注释（// 开头的行）
    - 多行注释块（/* ... */ 包含的所有行）
    - 行尾注释（代码后的 // 注释）
    参数：
    repo_dir (str): 仓库目录
    """
    count = 0
    for root, _, files in os.walk(repo_dir):
        for file in files:
            if file.endswith(".java"):
                file_path = os.path.join(root, file)
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    in_block_comment = False  # 是否在多行注释块中
                    in_string = False  # 是否在字符串中（"..."）
                    in_char = False  # 是否在字符中（'...'）
                    escape_next = False  # 下一个字符是否被转义

                    for line in f:
                        line_has_comment = False
                        i = 0
                        line_len = len(line)

                        while i < line_len:
                            char = line[i]

                            # 处理转义字符
                            if escape_next:
                                escape_next = False
                                i += 1
                                continue

                            # 在多行注释块中
                            if in_block_comment:
                                line_has_comment = True
                                # 检查注释块是否结束
                                if (
                                    char == "*"
                                    and i + 1 < line_len
                                    and line[i + 1] == "/"
                                ):
                                    in_block_comment = False
                                    i += 2  # 跳过 */
                                    continue
                                else:
                                    i += 1

                            # 不在注释块中
                            else:
                                # 处理字符串中的内容
                                if in_string:
                                    if char == '"':
                                        in_string = False
                                    elif char == "\\":
                                        escape_next = True
                                    i += 1

                                # 处理字符中的内容
                                elif in_char:
                                    if char == "'":
                                        in_char = False
                                    elif char == "\\":
                                        escape_next = True
                                    i += 1

                                # 普通代码区域
                                else:
                                    # 检查字符串/字符/注释符号
                                    if char == '"':
                                        in_string = True
                                        i += 1
                                    elif char == "'":
                                        in_char = True
                                        i += 1
                                    elif char == "/":
                                        if i + 1 < line_len:
                                            next_char = line[i + 1]
                                            # 多行注释块开始
                                            if next_char == "*":
                                                in_block_comment = True
                                                line_has_comment = True
                                                i += 2  # 跳过 /*
                                            # 单行注释
                                            elif next_char == "/":
                                                line_has_comment = True
                                                break  # 剩余部分都是注释，直接结束本行处理
                                            else:
                                                i += 1  # 普通除号
                                        else:
                                            i += 1
                                    else:
                                        i += 1

                        # 如果当前行在注释块中，则整行算注释
                        if in_block_comment:
                            line_has_comment = True

                        # 统计注释行
                        if line_has_comment:
                            count += 1

    return count



if __name__ == "__main__":
    # 测试Python文件结构提取
    # pyfile = "utils.py"
    # py_structure = extract_structure_from_pyfile(pyfile, pyfile)
    # logger.info(json.dumps(py_structure, indent=2, ensure_ascii=False))

    # # 测试Java文件结构提取
    # javafile = "test.java"
    # java_structure = extract_structure_from_java_file(javafile, javafile)
    # logger.info(java_structure)

    # 测试仓库结构提取
    path_to_repo = "./data/repos/hugobrilhante_stompypy"
    language = "python"
    # repo_structure = get_repo_structure(path_to_repo, language)
    # logger.info(json.dumps(repo_structure, indent=2, ensure_ascii=False))

    # 测试仓库代码提取
    # repo_code = get_repo_code_content(path_to_repo, language, mode="test")
    # logger.info(repo_code)

    # 测试仓库commit sha
    commit_sha = get_commit_sha(path_to_repo)
    logger.info(commit_sha)
