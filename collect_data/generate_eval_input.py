"""
生成测试的任务
Task1: Minimal Code Design
最小Code Design是指我们得首先分析测试用例, 看看测试用例直接调用了哪些代码接口。把这些被直接调用的接口的设计固定死，并提供给LLM, 以确保代码的接口跟测试的接口统一。
Task2: Minimal Test Case
最小Test Case是指我们得先分析测试用例, 找出一组最少的测试用例, 用这组测试用例就能够覆盖所有的被测试代码接口。
"""

import json
import re
from loguru import logger
from utils.utils import (
    StructuredCodeDesignList,
    StructuredTestList,
    StructuredTestIdList,
    StructuredRequirement,
    save_to_file,
    save_json
)
from utils.repo_info import (
    get_all_python_files_content,
    get_readme_content,
    get_repo_code_content,
    get_repo_structure,
)
from utils.config import MODEL_NAME
from utils.prompts import (
    system_prompt_for_generating_minimal_test_cases,
    system_prompt_for_generating_SRS_document,
    system_prompt_for_generating_structured_requirement,
    system_prompt_for_genereting_full_code_skeleton,
    system_prompt_for_genereting_minimal_code_skeleton,
)
from utils.llm import LLM


def generate_requirement_files(path_to_repo: str, test_cases: list, language: str):
    """
    给定仓库地址，生成功能需求文件
    1. 从仓库中读取readme文档
    2. 从仓库中读取类和函数的注释
    3. 生成功能需求文件
    """
    # 从仓库中读取readme文档
    readme_content = get_readme_content(path_to_repo)
    # 从仓库中读取代码
    code_test_content = get_repo_code_content(path_to_repo, language, mode="all")
    if code_test_content == "":
        logger.error(f"No code test content found in {path_to_repo}")
        return None

    # 使用llm生成功能需求文件
    messages = [
        {
            "role": "user",
            "content": system_prompt_for_generating_SRS_document.format(
                README_CONTENT=readme_content,
                CODE_TEST_CONTENT=code_test_content,
            ),
        }
    ]
    
    requirement_file = LLM.call_llm(MODEL_NAME, messages)
    if requirement_file is None:
        logger.error("Failed to generate requirement file")
        return None
    
    messages = [
        {
            "role": "user",
            "content": system_prompt_for_generating_structured_requirement.format(
                requirement_file=requirement_file,
            ),
        }
    ]
    requirement = LLM.call_llm_with_structured_output(
        model_name=MODEL_NAME,
        messages=messages,
        structured_output_class=StructuredRequirement,
    )
    requirement = requirement.model_dump()
    return requirement_file, requirement["requirement_document"], requirement["requirement_traceability"]


def generate_full_code_skeleton(
    path_to_repo: str
):
    """
    生成最小代码设计
    args:
        path_to_repo (str): 仓库地址
    return:
        code_skeleton (str): 最小代码设计
    """
    # 读取所有的python文件
    code_content = get_repo_code_content(path_to_repo, "python", mode="code")

    messages = [
        {
            "role": "user",
            "content": system_prompt_for_genereting_full_code_skeleton.format(
                code_content=code_content,
            ),
        },
    ]

    code_skeleton = LLM.call_llm(MODEL_NAME, messages, max_retries=10)
    if code_skeleton is None:
        logger.error("Failed to generate full code skeleton")
        return None

    return code_skeleton


def generate_minimal_code_skeleton(path_to_repo: str):
    """
    生成最小代码设计
    args:
        path_to_repo (str): 仓库地址
        SRS_document (str): 功能需求文档
        test_files_content (str): 测试用例内容

    return:
        code_skeleton (StructuredCodeDesignList): 最小代码设计
    """
    # 读取所有的python文件
    code_test_content = get_repo_code_content(path_to_repo, "python", mode="all")

    messages = [
        {
            "role": "user",
            "content": system_prompt_for_genereting_minimal_code_skeleton.format(
                code_content=code_test_content,
            ),
        },
    ]

    code_skeleton = LLM.call_llm(MODEL_NAME, messages, max_retries=10)
    if code_skeleton is None:
        logger.error("Failed to generate full code skeleton")
        return None

    return code_skeleton


def parse_code_skeleton(code_skeleton_str: str):
    """
    解析代码骨架
    """
    code_skeleton = []
    file_count = code_skeleton_str.count("--- File:")
    code_count = code_skeleton_str.count("```python")
    if file_count != code_count:
        logger.error("File count and code count do not match")
        return None
    # Regex to find file paths and their corresponding Python code blocks
    # Handles both LF and CRLF line endings
    pattern = re.compile(r"--- File: (.*?) ---\r?\n```python\r?\n(.*?)\r?```", re.DOTALL)
    matches = pattern.findall(code_skeleton_str)
    for match in matches:
        file_path = match[0]
        code = match[1]
        code_skeleton.append({"file_path": file_path, "code": code})
    if len(code_skeleton) != file_count:
        logger.error("Code skeleton length and file count do not match")
        return None
    return code_skeleton


def generate_minimal_test_cases(
    path_to_repo: str,
    test_case_list: list,
):
    """
    生成最小测试用例
    Args:
        path_to_repo (str): 仓库地址
        SRS_document (str): 功能需求文档
        test_files_content (str): 测试用例内容
        test_case_list (StructuredTestList): 测试用例列表

    return:
        minimal_test_cases (list): 一个整数列表, 代表最小测试用例对应的id
    """
    code_test_content = get_repo_code_content(path_to_repo, "python", mode="all")
    test_case_list_str = json.dumps(test_case_list, indent=2)
    
    messages = [
        {
            "role": "user",
            "content": system_prompt_for_generating_minimal_test_cases.format(
                code_content=code_test_content,
                test_content=test_case_list_str,
            ),
        },
    ]
    response = LLM.call_llm(MODEL_NAME, messages, max_retries=10)
    if response is None:
        logger.error("Failed to generate minimal test cases")
        return None
    try:
        # 解析返回的结果
        json_str = re.search(r"```json(.*)```", response, re.DOTALL).group(1)
        json_data = json.loads(json_str)
        return json_data
    except Exception as e:
        logger.error(f"Failed to parse minimal test cases: {e}")
        return None

def extract_repo_structure(path_to_repo: str):
    """
    提取仓库结构
    """
    repo_structure = get_repo_structure(path_to_repo, "python")
    structure_text = ""
    for item in repo_structure:
        if "tests/" in item["file"] or "setup.py" in item["file"]:
            continue
        file_text = ""
        for element in item["elements"]:
            if element["type"] == "function":
                function_args = ",".join(element["args"])
                file_text += f"def {element['name']}({function_args}):\n"
                if element["docstring"] is not None:
                    file_text += f"    \"\"\"{element['docstring']}\"\"\"\n"
                file_text += f"    pass\n"
            elif element["type"] == "class":
                file_text += f"class {element['name']}:\n"
                if element["docstring"] is not None:
                    file_text += f"    \"\"\"{element['docstring']}\"\"\"\n"
                if element["attributes"]:
                    for attribute in element["attributes"]:
                        file_text += f"    {attribute}\n"
                if element["methods"]:
                    for method in element["methods"]:
                        method_args = ",".join(method["args"])
                        file_text += f"    def {method['name']}({method_args}):\n"
                        if method["docstring"] is not None:
                            file_text += f"        \"\"\"{method['docstring']}\"\"\"\n"
                        file_text += f"        pass\n"
            structure_text += f"File: {item['file']}\n```python\n{file_text}\n```\n\n"
    return structure_text

if __name__ == "__main__":
    # 测试
    path_to_repo = "./data/repos/6mini_holidayskr"
    # 生成完整代码设计
    import pdb; pdb.set_trace()
    # full_code_skeleton = generate_full_code_skeleton(path_to_repo)
    # print(full_code_skeleton)
    
    repo_structure = extract_repo_structure(path_to_repo)
    print(repo_structure)
    
    # # 生成最小代码设计
    # minimal_code_design = generate_minimal_code_design(
    #     path_to_repo, SRS_document, test_files_content
    # )
    # print(type(minimal_code_design))
    # print(minimal_code_design)
    # # 生成最小测试用例
    # minimal_test_cases = generate_minimal_test_cases(
    #     path_to_repo, SRS_document, test_files_content, test_case_list
    # )
    # print(type(minimal_test_cases))
    # print(minimal_test_cases)
