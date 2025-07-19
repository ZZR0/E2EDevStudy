"""
需要用pip安装metagpt包
metagpt llm的配置在/home/zzr/.metagpt/config2.yaml
"""

from metagpt.software_company import generate_repo
from metagpt.utils.project_repo import ProjectRepo
import os
import json
import shutil
import os
import glob
import argparse
import asyncio
from pathlib import Path

import agentops
import typer

from metagpt.const import CONFIG_ROOT


def generate_repo_custumized(
    idea,
    investment=3.0,
    n_round=5,
    code_review=True,
    run_tests=False,
    implement=True,
    project_name="",
    inc=False,
    project_path="",
    reqa_file="",
    max_auto_summarize_code=0,
    recover_path=None,
) -> ProjectRepo:
    """Run the startup logic. Can be called from CLI or other Python scripts."""
    from metagpt.config2 import config
    from metagpt.context import Context
    from metagpt.roles import (
        Architect,
        Engineer,
        ProductManager,
        ProjectManager,
        QaEngineer,
    )
    from metagpt.team import Team

    if config.agentops_api_key != "":
        agentops.init(config.agentops_api_key, tags=["software_company"])

    config.update_via_cli(project_path, project_name, inc, reqa_file, max_auto_summarize_code)
    ctx = Context(config=config)

    if not recover_path:
        company = Team(context=ctx)
        company.hire(
            [
                ProductManager(),
                Architect(),
                ProjectManager(),
            ]
        )

        if implement or code_review:
            company.hire([Engineer(n_borg=5, use_code_review=code_review)])

        if run_tests:
            company.hire([QaEngineer()])
            if n_round < 8:
                n_round = 8  # If `--run-tests` is enabled, at least 8 rounds are required to run all QA actions.
    else:
        stg_path = Path(recover_path)
        if not stg_path.exists() or not str(stg_path).endswith("team"):
            raise FileNotFoundError(f"{recover_path} not exists or not endswith `team`")

        company = Team.deserialize(stg_path=stg_path, context=ctx)
        idea = company.idea

    company.invest(investment)
    company.run_project(idea)
    asyncio.run(company.run(n_round=n_round))

    if config.agentops_api_key != "":
        agentops.end_session("Success")

    return ctx.repo

parser = argparse.ArgumentParser()
parser.add_argument(
    "--dataset-file",
    type=str,
    default="./data/datasets/pypi-2024-01-dataset-final.json",
    help="Path to the dataset file",
)
args = parser.parse_args()
# 导入数据集
dataset_path = args.dataset_file
with open(dataset_path, "r") as f:
    dataset = json.load(f)
for data in dataset[8:9]:  # 临时只对一个项目进行测试
    name = data["repo_name"]
    SRS_document = data["SRS_document"]
    minimal_code_skeleton_str = str(data["minimal_code_skeleton"])
    minimal_test_cases_str = str(data["minimal_test_cases"])

    # 生成代码
    idea = (
        "Develop a Python package based on the SRS document below.\n"
        + SRS_document
        + "\n"
        + "The following message should be attached to the SRS document:\n"
        + "You should implement the following interfaces, make sure all interfaces can be invoked at the specified locations:\n"
        + minimal_code_skeleton_str
        + "\n"
        + "You should consider the following test cases. Implement the interfaces corresponding to the positions specified in the covers arrays:\n"
        + minimal_test_cases_str
    )
    metagpt_workspace_path = (
        "/hdd1/zzr/MetaGPT/workspace"  # metagpt生成的项目会保存在这个文件夹下
    )
    # 清空metagpt_workspace_path
    for file in glob.glob(os.path.join(metagpt_workspace_path, "*")):
        if os.path.isdir(file):
            shutil.rmtree(file)
        else:
            os.remove(file)
    # 生成代码
    repo: ProjectRepo = generate_repo_custumized(
        idea=idea,
        investment=10,
    )
    print(repo)
    # 生成的代码保存在指定目录下，默认在metagpt包的workspace目录
    repo_path = repo.git_repo.workdir
    # 获取当前工作目录
    current_dir = os.getcwd()
    # 设置项目路径
    project_path = os.path.join(current_dir, "data/metagpt_results")
    save_path = os.path.join(project_path, name)
    if not os.path.exists(save_path):
        os.makedirs(save_path)
    shutil.copytree(repo_path, save_path, dirs_exist_ok=True)
