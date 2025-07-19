# 用于存储一些工具函数

import os
import subprocess
import time
import threading
from loguru import logger
from typing import Optional
from pydantic import BaseModel
import requests
import shutil  # 导入 shutil 模块
import json

class StructuredRating(BaseModel):
    """
    用于存储评分的数据类
    """

    reason: str
    project_type: str
    difficulty: str
    rating: int
    
StructuredRating_Format = {
    "type": "json_schema",
    "json_schema": {
        "name": "rating",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
                "project_type": {"type": "string"},
                "difficulty": {"type": "string"},
                "rating": {"type": "integer"},
            },
            "required": ["reason", "project_type", "difficulty", "rating"],
            "additionalProperties": False
        }
    }
}


class Traceability(BaseModel):
    id: str
    description: str

class StructuredRequirementItem(BaseModel):
    """
    用于存储结构化需求的数据类
    """

    requirement_id: str
    requirement_description: str
    test_traceability: list[Traceability]
    code_traceability: list[Traceability]

class StructuredRequirement(BaseModel):
    """
    一个列表，包含多个结构化需求
    """
    requirement_document: str
    requirement_traceability: list[StructuredRequirementItem]

StructuredRequirement_Format = {
    "type": "json_schema",
    "json_schema": {
        "name": "requirement",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "requirement_document": {"type": "string"},
                "requirement_traceability": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "requirement_id": {"type": "string"},
                            "requirement_description": {"type": "string"},
                            "test_traceability": {
                                "type": "array", 
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string"},
                                        "description": {"type": "string"},
                                    },
                                        "required": ["id", "description"],
                                }
                            },
                            "code_traceability": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string"},
                                        "description": {"type": "string"},
                                    },
                                    "required": ["id", "description"],
                                }
                            },
                        },
                        "required": ["requirement_id", "requirement_description", "test_traceability", "code_traceability"],
                        "additionalProperties": False
                    }
                }
            },
            "required": ["requirement_document", "requirement_traceability"],
            "additionalProperties": False
        }
    }
}


class StructuredTest(BaseModel):
    """
    用于存储结构化测试数据的数据类
    """

    id: int
    test_file_path: str
    test_class: Optional[str] = None
    test_method: str
    test_implementation: str = ""  # 增加字段存储测试函数的完整实现代码

class StructuredTestList(BaseModel):
    """
    一个列表，包含多个结构化测试数据
    """

    tests: list[StructuredTest]

StructuredTestList_Format = {
    "type": "json_schema",
    "json_schema": {
        "name": "test_case_list",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "tests": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "test_file_path": {"type": "string"},
                            "test_class": {"type": "string"},
                            "test_method": {"type": "string"},
                        },
                        "required": ["id", "test_file_path", "test_method"],
                        "additionalProperties": False
                    }
                }
            },
            "required": ["tests"],
            "additionalProperties": False
        }
    }
}


class StructuredTestIdList(BaseModel):
    """
    用于存储结构化测试数据的ID列表
    """

    test_ids: list[int]

StructuredTestIdList_Format = {
    "type": "json_schema",
    "json_schema": {
        "name": "test_id_list",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "test_ids": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["test_ids"],
            "additionalProperties": False
        }
    }
}


class StructuredCodeDesign(BaseModel):
    """
    用于存储结构化代码设计的数据类
    """

    interface_name: str
    input_parameters: str
    output_values: str
    functionality: str

class StructuredCodeDesignList(BaseModel):
    """
    一个列表，包含多个结构化代码设计数据
    """

    code_designs: list[StructuredCodeDesign]

StructuredCodeDesignList_Format = {
    "type": "json_schema",
    "json_schema": {
        "name": "code_design_list",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "code_designs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "interface_name": {"type": "string"},
                            "input_parameters": {"type": "string"},
                            "output_values": {"type": "string"},
                            "functionality": {"type": "string"},
                        },
                        "required": ["interface_name", "input_parameters", "output_values", "functionality"],
                        "additionalProperties": False
                    }
                }
            },
            "required": ["code_designs"],
            "additionalProperties": False
        }
    }
}


def get_json_schema(structured_output_class):
    if structured_output_class == StructuredTestList:
        return StructuredTestList_Format
    elif structured_output_class == StructuredRequirement:
        return StructuredRequirement_Format
    elif structured_output_class == StructuredRating:
        return StructuredRating_Format
    elif structured_output_class == StructuredCodeDesignList:
        return StructuredCodeDesignList_Format
    elif structured_output_class == StructuredTestIdList:
        return StructuredTestIdList_Format
    else:
        raise ValueError(f"Unsupported structured output class: {structured_output_class}")

def parse_structured_output(structured_output_class, response):
    try:
        data_dict = json.loads(response)
        structured_instance = structured_output_class(**data_dict)
        return structured_instance
    except json.JSONDecodeError as e:
        logger.error(f"JSON 解析错误: {e}")
    except Exception as e: # 捕获 Pydantic 验证错误等
        logger.error(f"创建 {structured_output_class} 实例时出错: {e}")


class TokenManager:
    """
    用于管理GitHub API令牌的类
    """

    def __init__(self, tokens):
        self.tokens = tokens
        self.current_index = 0
        self.lock = threading.Lock()

    def get_token(self):
        with self.lock:
            if not self.tokens:
                raise ValueError("No tokens available")
            token = self.tokens[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.tokens)
            return token


# 将github模块返回的仓库信息转换为字典
def repo_to_dict(repo):
    return {
        "repo_name": repo.full_name.replace("/", "_"),
        "url": repo.html_url,
        "description": repo.description,
        "stars": repo.stargazers_count,
        "forks": repo.forks_count,
        "language": repo.language.lower(),
        "size": repo.size,
    }


def get_dependencies(package_name):
    """
    获取PyPI包的依赖项
    """
    url = f"https://pypi.org/pypi/{package_name}/json"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        dependencies = data.get("info", {}).get("requires_dist", [])
        return dependencies
    else:
        return f"Failed to fetch information for package: {package_name}"


def clone_repo(
    repo_url, repo_dir, retries=5, timeout=600, github_token=None, refresh=False
):
    """
    克隆仓库到指定目录
    参数：
    repo_url (str): 仓库URL
    repo_dir (str): 目标目录
    retries (int): 重试次数
    timeout (int): 超时时间(秒)
    github_token (str): GitHub令牌，用于认证以避免限流
    refresh (bool): 如果为True且目录已存在，则删除并重新克隆
    返回：
    bool: 克隆是否成功
    """
    if os.path.exists(repo_dir):
        if refresh:
            logger.info(
                f"Refresh flag is True. Removing existing directory: {repo_dir}"
            )
            try:
                shutil.rmtree(repo_dir)
                logger.info(f"Directory {repo_dir} removed successfully.")
            except Exception as e:
                logger.error(f"Failed to remove directory {repo_dir}: {str(e)}")
                return False  # 无法移除旧目录，克隆失败
        else:
            # logger.info(
            #     f"Repo {repo_dir} already exists and refresh is False. Skipping clone."
            # )
            return True

    # 如果提供了token，则使用token进行认证
    if github_token and github_token is not None:
        # 在URL中添加token认证
        if repo_url.startswith("https://github.com"):
            # 替换URL格式为带token的URL
            auth_repo_url = repo_url.replace(
                "https://github.com", f"https://{github_token}@github.com"
            )
        else:
            auth_repo_url = repo_url
    else:
        auth_repo_url = repo_url

    for attempt in range(retries):
        try:
            logger.info(f"Cloning {repo_dir} with token {github_token}...")
            result = subprocess.run(
                ["git", "clone", "--depth", "1", auth_repo_url, repo_dir],
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                timeout=timeout,
            )
            if result.returncode == 0:
                logger.success(f"Repo {repo_dir} cloned successfully.")
                return True
            else:
                # 如果克隆失败，记录错误信息
                error_message = result.stderr.strip()
                logger.error(
                    f"Attempt {attempt} Cloning {repo_dir} failed with return code {result.returncode}. Error: {error_message}"
                )
            time.sleep(5 * (attempt + 1))  # 退避
        except Exception as e:
            logger.error(f"Error: {str(e)}")

    logger.error(f"Failed to clone after {retries} attempts")
    return False


def save_to_file(data, file_path):
    """
    将数据保存到文件
    """
    with open(file_path, "w", encoding="utf-8") as f:
        if file_path.endswith(".json"):
            json.dump(data, f, ensure_ascii=False, indent=4)
        else:
            f.write(data)

def load_from_file(file_path):
    """
    从文件中加载数据
    """
    with open(file_path, "r", encoding="utf-8") as f:
        if file_path.endswith(".json"):
            return json.load(f)
        else:
            return f.read()

def save_json(data, file_path):
    """
    将数据保存为JSON文件
    """
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    # 测试函数
    repo_dir = "../../../repos/The-Pocket_PocketFlow"
    # print(get_structured_tests(repo_dir))
