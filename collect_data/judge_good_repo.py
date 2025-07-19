import json
import os
import openai
from loguru import logger

# 将日志输出到文件
logger.add(
    "judge_good_project.log",
    rotation="1 day",
    level="INFO",
    format="{time} {level} {message}",
)

from utils.repo_info import (
    count_python_files,
    count_python_code_lines,
    count_java_files,
    count_java_code_lines,
    count_python_comment_lines,
    count_java_comment_lines,
    find_test_file,
    get_test_files_content,
    get_structured_tests,
    get_pyfile_content,
    get_readme_content,
    find_metadata,
    get_repo_structure
)
from utils.utils import (
    clone_repo,
    StructuredRating,
)

from utils.config import (
    PYTHON_FILE_MINIMUM,
    PYTHON_FILE_MAXIMUM,
    CODELENGTH_MINIMUM,
    CODELENGTH_MAXIMUM,
    TEST_CODELENGTH_MINIMUM,
    TEST_CODELENGTH_MAXIMUM,
    JAVA_FILE_MINIMUM,
    JAVA_FILE_MAXIMUM,
    COMMENT_RATIO,
    STARS_NUM,
    README_MINIMUM,
    TEST_CASE_NUM,
    CHECK_STANDALONE_PROJECT_MODEL,
)

from utils.llm import LLM
from utils.prompts import system_prompt_for_judging_good_project


def llm_check_good_project(readme_content, test_file_content, code_structure):
    """
    利用大模型判断是否是一个独立的项目
    参数：
    readme_content (str): readme文件内容
    test_file_content (str): 测试文件内容
    code_structure (str): 代码结构
    """
    messages = [
        {"role": "user", "content": system_prompt_for_judging_good_project.format(
            readme_content=readme_content, code_structure=code_structure, test_file_content=test_file_content
        )},
    ]
    try:
        answer = LLM.call_llm_with_structured_output(
            model_name=CHECK_STANDALONE_PROJECT_MODEL,
            messages=messages,
            structured_output_class=StructuredRating,
            max_retries=15,
        )
        rating = answer.model_dump()["rating"]
        reason = answer.model_dump()["reason"]
        project_type = answer.model_dump()["project_type"]
        difficulty = answer.model_dump()["difficulty"]
        logger.info(f"Rating: {rating}")
        logger.info(f"Reason: {reason}")
        logger.info(f"Project Type: {project_type}")
        logger.info(f"Difficulty: {difficulty}")
        return rating, reason, project_type, difficulty
    except Exception as e:
        logger.error(f"Failed to judge good project: {e}")
        return 0, "Failed to judge good project", "Failed to judge good project", "Failed to judge good project"

def run_judge_project(repo, language):
    judge_info = repo["judge_info"]
    
    if repo["stars"] < STARS_NUM:
        return False, f"Stars Number Failed"
    
    if not "comment_ratio" in judge_info:
        return False, f"Empty judge info"
    
    if (
        judge_info["python_file_num"] < PYTHON_FILE_MINIMUM
        or judge_info["python_file_num"] > PYTHON_FILE_MAXIMUM
    ):
        return False, f"Python File Count Failed"
    
    if judge_info["comment_ratio"] < COMMENT_RATIO:
        return False, f"Comment Ratio Failed"
    
    if judge_info["pyfile_content_length"] < CODELENGTH_MINIMUM or judge_info["pyfile_content_length"] > CODELENGTH_MAXIMUM:
        return False, f"Code File Content Length Failed"
    
    if (
        judge_info["pyfile_content_length"] < CODELENGTH_MINIMUM
        or judge_info["pyfile_content_length"] > CODELENGTH_MAXIMUM
    ):
        return False, f"Code File Content Length Failed"

    if (
        judge_info["test_file_content_length"] < TEST_CODELENGTH_MINIMUM
        # or judge_info["test_file_content_length"] > TEST_CODELENGTH_MAXIMUM
    ):
        return False, f"Test File Content Length Failed"
    
    if not judge_info["pytest_framework"]:
        return False, f"Test Framework Failed"
    if not judge_info["test_file_exist"]:
        return False, f"No Test Files Found"
    
    if judge_info["test_case_num"] < TEST_CASE_NUM:
        return False, f"Test Case Number Failed"
    
    # 检查元数据文件是否只有一个
    # if len(judge_info["metadata_path"]) > 1:
    #     logger.info(f"More than one metadata file found.")
    #     return False, f"Metadata File Number Failed"
    # 检查元数据文件是否在根目录，即metadata_path[0]是一个单独的文件名
    if len(judge_info["metadata_path"]) == 0 or os.path.dirname(judge_info["metadata_path"][0]) != "":
        logger.info(f"Metadata file is not in the root directory.")
        return False, f"Metadata File Location Failed"
    
    if judge_info["readme_content_length"] == 0:
        return False, f"No Readme File Found"
    # readme文件内容长度大于README_MINIMUM
    if judge_info["readme_content_length"] < README_MINIMUM:
        return False, f"Readme File Content Length Failed"
    if judge_info["llm_rating"] < 70:
        return False, f"LLM Rating Failed"

    return True, f"LLM Rating Passed"
    
def get_judge_info(path_to_repo, language):
    """
    利用大模型，根据readme文件中的信息，判断

    1. 代码文件个数适中
    2. 代码总长度适中
    3. 包含测试文件，并且测试框架是pytest或者unittest
    4. 测试文件的内容长度在一定范围内
    5. 注释的比例大于一定值
    6. 若有元数据，只能有一个且在根目录
    7. 是否是一个独立的python项目
    参数：
    path_to_repo (str): 仓库目录
    """
    judge_info = {
        "language": language,
        "is_good_project": False,
        "reason": "",
    }
    # 检查代码文件个数是否适中
    if language == "python":
        # 检查该项目是否符合要求：包含的python文件数量大于PYTHON_FILE_MINIMUM，小于PYTHON_FILE_MAXIMUM
        python_file_num = count_python_files(path_to_repo)
        judge_info["python_file_num"] = python_file_num
        comment_lines = count_python_comment_lines(path_to_repo)
        code_lines = count_python_code_lines(path_to_repo)
        judge_info["comment_ratio"] = comment_lines / code_lines
    elif language == "java":
        # 检查该项目是否符合要求：包含的java文件数量大于2，小于200
        java_file_num = count_java_files(path_to_repo)
        judge_info["java_file_num"] = java_file_num
        comment_lines = count_java_comment_lines(path_to_repo)
        code_lines = count_java_code_lines(path_to_repo)
        judge_info["comment_ratio"] = comment_lines / code_lines

    # 检查代码文件的总长度是否在一定范围内
    pyfile_content = get_pyfile_content(path_to_repo)
    judge_info["pyfile_content_length"] = len(pyfile_content)
    judge_info["pyfile_code_lines"] = count_python_code_lines(path_to_repo)

    # 检查该项目是否包含测试文件
    test_file_path_list = find_test_file(path_to_repo, language)
    judge_info["test_file_exist"] = True if test_file_path_list else False

    # 检查测试文件的总长度是否在一定范围内
    test_file_content = get_test_files_content(path_to_repo)
    judge_info["test_file_content_length"] = len(test_file_content)
    judge_info["pytest_framework"] = True if "pytest" in test_file_content or "unittest" in test_file_content else False
    
    try:
        structure_dict = get_repo_structure(path_to_repo, language)
        structure_dict_str = json.dumps(structure_dict, indent=4)
    except Exception as e:
        logger.error(f"Failed to get repo structure: {e}")
        structure_dict_str = ""
    
    # 检查测试点的个数是否大于一定值
    structured_tests = get_structured_tests(path_to_repo)
    judge_info["test_case_num"] = len(structured_tests)

    # 检查元数据文件是否符合要求
    metadata_path = find_metadata(path_to_repo)
    judge_info["metadata_path"] = metadata_path

    # 获取readme文件内容
    readme_content = get_readme_content(path_to_repo)
    judge_info["readme_content_length"] = len(readme_content)

    if judge_info["test_file_exist"] == False or readme_content == "" or structure_dict_str == "":
        rating, reason, project_type, difficulty = 0, "Skipped to judge good project", "Skipped to judge good project", "Skipped to judge good project"
    else:
        # 检查是否是一个独立的项目
        rating, reason, project_type, difficulty = llm_check_good_project(readme_content, test_file_content, structure_dict_str)
        
    judge_info["llm_reason"] = reason
    judge_info["llm_project_type"] = project_type
    judge_info["llm_rating"] = rating
    judge_info["llm_difficulty"] = difficulty
    return judge_info


if __name__ == "__main__":
    path_to_repo = "../../repos/character-ai_prompt-poet"
    language = "python"
    # print(judge_good_project(path_to_repo, language))
