import copy
import os
import shutil
import subprocess
import sys
from pathlib import Path

# 添加父目录到模块搜索路径
import json
import time
import argparse
from loguru import logger
from utils.utils import EvalReport, load_file, save_file
from utils.dockerfiles import DOCKERFILE
from utils.constants import (
    get_pip_packages,
    get_post_install,
    get_pre_install,
    get_install,
    get_test_cmd,
    check_env_cmd,
    apply_patch
)
from docker_utils import (
    build_container,
    copy_to_container,
    save_container,
    stop_remove_container,
    build_image_from_dockerfile,
    check_image_exists,
)
import re
import concurrent.futures
from tqdm import tqdm
import numpy as np

# 添加文件日志记录器
log_file_path = "evaluation.log"
if os.path.exists(log_file_path):
    os.remove(log_file_path)  # 删除旧的日志文件
logger.add(
    log_file_path,
    rotation="100 MB",
    level="INFO",
    format="{time} {level} [{function}:{line}] {message}",
    enqueue=True,
)

INSTALL_TIMEOUT = 600
EVALUATION_TIMEOUT = 1200
SINGLE_TEST_TIMEOUT = 300

TEST_SCRIPT_COLLECT = """#!/bin/bash
# 脚本说明：
# 1. 运行 pytest --collect-only 来识别导致收集错误的测试文件。
# 2. 输出错误的测试文件列表。

# 步骤 1: 发现有采集错误的测试文件
ERROR_LOG=$(mktemp)
trap 'rm -f "$ERROR_LOG"' EXIT

echo "Phase 1: Finding files with collection errors..."
# 使用 '&>' 将 stdout 和 stderr 全部重定向，以保留完整的 pytest 报告格式。
PYTHONPATH=/:$(pwd):$(pwd)/src:$PYTHONPATH pytest --collect-only "$@" &> "$ERROR_LOG"

# 从日志中解析出错误的测试文件
BAD_FILES=$(awk '/^=.* short test summary info .*=/{f=1} f && /^ERROR/{print $2}' "$ERROR_LOG" | sort -u | xargs)

echo "$BAD_FILES"
echo "---COLLECTION_ERROR_LOG_SEPARATOR---"
cat "$ERROR_LOG"
"""

TEST_SCRIPT_RUN = """#!/bin/bash
# 脚本说明：
# 该脚本负责：
# 1. 动态创建 .coveragerc 配置文件。
# 2. 使用正确的参数和环境变量执行实际的测试。

# 步骤 1: 创建 .coveragerc 配置文件
COVERAGERC_CONTENT="[run]
branch = true
source = .
omit =
    tests/*
    new_tests/*
    test/*
    */site-packages/*

[json]
show_contexts = true
"
echo "$COVERAGERC_CONTENT" > .coveragerc_tmp

# 步骤 2: 执行真正的 pytest 命令
echo "Phase 2: Running tests..."
# 使用从外部传入的参数（$@）来执行测试
# shellcheck disable=SC2086
# 设置 PYTHONPATH 以确保本地模块可被导入
PYTHONPATH=/:$(pwd):$(pwd)/src:$PYTHONPATH pytest "$@"
"""

def setup_env(build_path):
    # 设置测试环境配置脚本
    setup_env = f"pip install --default-timeout={INSTALL_TIMEOUT} \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    pytest pytest-cov pytest_asyncio pytest-httpbin pytest-timeout pytest-json-report mock\n"
    logger.info(f"setup_env: {setup_env}")
    setup_scripts = {"setup_env.sh": setup_env}
    # 写入设置脚本
    for script_name, script_content in setup_scripts.items():
        script_path = os.path.join(build_path, script_name)
        save_file(script_path, script_content)


def install_from_traj(container, repo_info, workdir):
    """
    从traj文件中的history属性读取bash命令，从中获取带有pip install或export命令的bash命令，
    然后运行以更新环境。
    """
    # 根据 prediction_path 和 repo_name 构建 traj 文件的路径
    commands_to_run = []
    for command in repo_info["commands"]:
        if command and check_env_cmd(command):
            # 为pip命令添加国内镜像源以加速
            if 'pip install' in command and "pypi.tuna.tsinghua.edu.cn" not in command:
                command = command.replace(
                    "pip install",
                    "pip install -i https://pypi.tuna.tsinghua.edu.cn/simple",
                )
            commands_to_run.append(command)

    if commands_to_run:
        logger.info(
            f"Found {len(commands_to_run)} pip/export commands in trajectory. Executing them now."
        )
        for cmd in commands_to_run:
            logger.info(f"Executing: {cmd}")
            exec_result = container.exec_run(cmd, workdir=workdir)
            result_str = exec_result.output.decode("utf-8")
            if exec_result.exit_code == 0:
                logger.success(f"Successfully executed: {cmd}\nOutput:\n{result_str}")
            else:
                logger.warning(f"Failed to execute: {cmd}\nError:\n{result_str}")
    else:
        logger.info("No 'pip install' or 'export' commands found in trajectory.")


def setup_repo(container, build_path, workdir, repo_info, quick_mode=False):
    logger.info(f"Setup repo in quick mode: {quick_mode}")
    # 将repo代码复制到容器中
    result = container.exec_run(f"rm -rf {workdir}", workdir="/")
    result = container.exec_run(f"mkdir -p {workdir}", workdir="/")
    result = container.exec_run(f"ls {workdir}", workdir="/")
    assert result.output.decode('utf-8') == "", f"workdir {workdir} is not empty"
    copy_to_container(container, repo_info["repo_path"], workdir)

    pre_install_cmds = get_pre_install(repo_info["repo_name"])
    if pre_install_cmds is not None:
        for cmd in pre_install_cmds:
            logger.info(f"pre_install_cmd: {cmd}")
            exec_result = container.exec_run(cmd, workdir=workdir)
            result_str = exec_result.output.decode("utf-8")
            logger.info(f"result_str: {result_str}")

    if quick_mode:
        return True
    
    # 安装程序的依赖包
    # 检查仓库根目录下是否存在 setup.py 或 pyproject.toml
    dependencies_cmd = ""
    setup_py_path = os.path.join(repo_info["repo_path"], "setup.py")
    pyproject_toml_path = os.path.join(repo_info["repo_path"], "pyproject.toml")
    install_cmd = get_install(repo_info["repo_name"])
    if install_cmd is not None:
        dependencies_cmd += f"{install_cmd}\n"
    elif os.path.exists(setup_py_path) or os.path.exists(pyproject_toml_path):
        # 如果存在则在docker对应目录运行安装命令
        dependencies_cmd += f"pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple --default-timeout={INSTALL_TIMEOUT}\n"
    else:
        # 如果不存在则从数据集中读取依赖，加到环境配置脚本中
        if repo_info["dependencies"] is not None:
            # 读取依赖
            for dep in repo_info["dependencies"]:
                # 使用正则表达式匹配包名和版本要求（忽略分号后的条件）
                match = re.match(r"^([^;]+)", dep.strip())
                if match:
                    package_spec = match.group(1).strip()
                    dependencies_cmd += f'pip install --default-timeout=300 -i https://pypi.tuna.tsinghua.edu.cn/simple "{package_spec}" \n'

    pip_packages = get_pip_packages(repo_info["repo_name"])
    if pip_packages is not None:
        for pkg in pip_packages:
            dependencies_cmd += f"pip install --default-timeout=300 -i https://pypi.tuna.tsinghua.edu.cn/simple {pkg} \n"

    # 运行安装依赖包的命令
    if dependencies_cmd != "":
        logger.info(f"dependencies_cmd: {dependencies_cmd}")
        # 将安装依赖的命令存入文件
        dep_cmd_path = os.path.join(build_path, "setup_dep.sh")
        with open(dep_cmd_path, "w") as f:
            f.write(dependencies_cmd)
        logger.success(f"setup_dep.sh: {dependencies_cmd}")
        copy_to_container(container, dep_cmd_path, "/tmp/setup_dep.sh")
        logger.info("Running setup_dep.sh...")
        # 运行安装依赖的命令
        exec_result = container.exec_run(
            f"bash /tmp/setup_dep.sh",
            workdir=workdir,
        )
        result_str = exec_result.output.decode("utf-8")
        logger.success(f"result_str: {result_str}")
        if "ERROR" in result_str:
            logger.error(f"Failed to install dependencies for {repo_info['repo_name']}")
            return False

    post_install_cmds = get_post_install(repo_info["repo_name"])
    if post_install_cmds is not None:
        for cmd in post_install_cmds:
            logger.info(f"post_install_cmd: {cmd}")
            exec_result = container.exec_run(cmd, workdir=workdir)
            result_str = exec_result.output.decode("utf-8")
            logger.info(f"result_str: {result_str}")

    return True


def evaluate_repo(repo_info):
    """
    评估repo的函数
    :param repo_info: repo信息
    :return: report 这个repo的评估结果
    """
    # 拼接构建路径
    build_path = os.path.join("build_dir", repo_info["repo_name"])
    os.makedirs(build_path, exist_ok=True)

    setup_env(build_path)

    dockerfile_content = DOCKERFILE.format(workdir=f"/{repo_info['repo_name']}")
    container = None
    all_reports = {}

    try:
        image_tag = f"LPBench.eval.{repo_info['repo_name']}"  # 替换冒号以避免路径问题
        image_tag = image_tag.replace(":", "_").replace("/", "_")
        image_tag = image_tag.lower()  # 转换为小写以避免路径问题
        quick_mode = check_image_exists(image_tag)

        retry_count = 0
        while retry_count < 3:
            # 构建镜像
            image = build_image_from_dockerfile(
                path=build_path,
                tag=image_tag,
                dockerfile_content=dockerfile_content,
                build_args=None,
                nocache=False,
            )

            if image is None:
                logger.error("Failed to build image, cannot run container")
                retry_count += 1
                continue

            container_name = (
                f"{image_tag}.{repo_info['repo_path'].strip('/').replace('/', '_')}"
            )

            # 构建并运行docker容器
            container = build_container(
                image_tag=image_tag,
                container_name=container_name,
            )
            if container is None:
                logger.error(
                    f"Failed to build container for {repo_info['repo_name']}, retry {retry_count + 1}"
                )
                retry_count += 1
                continue
            break

        if container is None:
            logger.error(f"Failed to build container for {repo_info['repo_name']}")
            return None

        workdir = f'/{repo_info["repo_name"]}'

        # 在主机上检查测试目录是否存在
        tests_dir_exists = os.path.isdir(os.path.join(repo_info["repo_path"], "tests"))
        new_tests_dir_exists = os.path.isdir(
            os.path.join(repo_info["repo_path"], "new_tests")
        )
        if not tests_dir_exists:
            logger.warning(f"Tests directory not found in {repo_info['repo_path']}")
        if not new_tests_dir_exists:
            logger.error(f"New tests directory not found in {repo_info['repo_path']}")
            return None
        
        # import pdb; pdb.set_trace()
        # 设置repo环境
        success = setup_repo(
            container, build_path, workdir, repo_info, quick_mode=quick_mode
        )
        if not success:
            logger.error(f"Failed to setup repo for {repo_info['repo_name']}")
            return None
        install_from_traj(container, repo_info, workdir)

        # 准备并执行测试脚本
        # 1. 收集错误的测试文件
        collect_script_path = os.path.join(build_path, "run_collect_tests.sh")
        save_file(collect_script_path, TEST_SCRIPT_COLLECT)
        copy_to_container(container, collect_script_path, f"{workdir}/run_collect_tests.sh")
        container.exec_run(f"chmod +x {workdir}/run_collect_tests.sh", workdir=workdir)
        
        test_files_to_collect = " ".join(repo_info["test_files"])
        collect_cmd = f"./run_collect_tests.sh {test_files_to_collect}"
        logger.info(f"Collecting bad files with command: {collect_cmd}")
        collect_result = container.exec_run(collect_cmd, workdir=workdir)
        collect_output = collect_result.output.decode("utf-8")
        parts = collect_output.split("---COLLECTION_ERROR_LOG_SEPARATOR---", 1)
        bad_files_str = parts[0].strip()
        collection_log = ""
        if len(parts) > 1:
            collection_log = parts[1].strip()

        logger.info(f"Collected bad files: '{bad_files_str}'")
        bad_files_list = bad_files_str.split()
        

        # 2. 准备执行测试的脚本
        test_script_path = os.path.join(build_path, "run_tests.sh")
        save_file(test_script_path, TEST_SCRIPT_RUN)
        copy_to_container(container, test_script_path, f"{workdir}/run_tests.sh")
        container.exec_run(f"chmod +x {workdir}/run_tests.sh", workdir=workdir)

        test_runs = [
            {"name": "ori_tests", "test_args": [t for t in repo_info["test_files"] if "new_tests" not in t]},
            {"name": "new_tests", "test_args": [t for t in repo_info["test_files"] if "new_tests" in t]},
            {"name": "all_tests", "test_args": [t for t in repo_info["test_files"]]},
        ]

        for test_run in test_runs:
            run_name = test_run["name"]
            filtered_test_args = [
                t for t in test_run["test_args"] if t not in bad_files_list
            ]
            if len(filtered_test_args) == 0:
                logger.warning(f"No test files to run for {run_name}")
                all_reports[run_name] = EvalReport(repo_info["repo_name"])
                continue
            test_args = " ".join(filtered_test_args)
            pytest_report_file = f"pytest_report_{run_name}.json"
            coverage_report_file = f"coverage_report_{run_name}.json"
            # 准备传递给 run_tests.sh 的 pytest 参数
            pytest_args = f"""{test_args} --timeout={SINGLE_TEST_TIMEOUT} -rA --cov --cov-context=test --cov-config=".coveragerc_tmp" --cov-report=json:{coverage_report_file} --json-report --json-report-file={pytest_report_file}"""

            # 新的测试命令
            test_command = f"./run_tests.sh {pytest_args}"

            logger.info(f"Start testing for {run_name}: {test_command}")
            exec_result = container.exec_run(test_command, workdir=workdir)
            # logger.info(f"Test result for {run_name}: {exec_result.output.decode('utf-8')}")

            report = EvalReport(repo_info["repo_name"])
            report.test_output = exec_result.output.decode("utf-8")
            if bad_files_list:
                report.collection_log = collection_log

            exec_result = container.exec_run(
                f"cat ./{pytest_report_file}", workdir=workdir
            )
            pytest_result_str = exec_result.output.decode("utf-8")
            if exec_result.exit_code != 0:
                logger.error(
                    f"Could not find pytest report for {run_name}. Output: {pytest_result_str}"
                )
                pytest_result = {"tests": [], "summary": {}}
            else:
                try:
                    pytest_result = json.loads(pytest_result_str)
                except json.JSONDecodeError:
                    logger.error(
                        f"Failed to parse pytest report for {run_name}. Content: {pytest_result_str}"
                    )
                    pytest_result = {"tests": [], "summary": {}}

            report.set_detail(pytest_result)

            coverage_result_str = ""
            try:
                exec_result = container.exec_run(
                    f"cat ./{coverage_report_file}", workdir=workdir
                )
                coverage_result_str = exec_result.output.decode("utf-8")
                coverage_result = json.loads(coverage_result_str)
            except Exception as e:
                logger.error(
                    f"Error getting coverage report for {run_name}: `{coverage_result_str}`"
                )
                coverage_result = {"totals": {"error": 1, "percent_covered": 0}}

            for test in pytest_result.get("tests", []):
                report.add_test_result(test["nodeid"], test["outcome"])

            report.add_coverage_report(coverage_result.get("totals", {}))

            report.finalize()
            logger.success(f"Test case results for {repo_info['repo_name']} ({run_name}):")
            logger.info(f"  success rate: {report.success_rate}")
            logger.info(f"  success count: {report.success_count}")
            logger.info(f"  failed count: {report.failed_count}")
            logger.info(f"  skipped count: {report.skipped_count}")
            logger.info(f"  error count: {report.error_count}")
            logger.info(f"  unknown count: {report.unknown_count}")
            logger.info(f"  coverage rate: {report.coverage_report.get('percent_covered', 0)}")
            all_reports[run_name] = report

    except Exception as e:
        logger.error(f"Error evaluating {repo_info['repo_name']}: {str(e)}")
        # import pdb; pdb.set_trace()
    finally:
        # import pdb; pdb.set_trace()
        if container is not None:
            if not quick_mode:
                save_container(container, f"lpbench.eval.{repo_info['repo_name']}")
            # 停止运行并删除容器以及对应的镜像
            stop_remove_container(container)
    return all_reports


def add_tests_init_file(repo_path):
    for tests_dirname in ["tests", "new_tests"]:
        tests_dir = os.path.join(repo_path, tests_dirname)
        if os.path.isdir(tests_dir):
            for dirpath, _, _ in os.walk(tests_dir):
                init_py_path = os.path.join(dirpath, "__init__.py")
                if not os.path.exists(init_py_path):
                    with open(init_py_path, "w") as f:
                        f.write("")

def find_pytest_files(repo_path):
    """
    遍历 repo_path 路径下的所有符合 pytest 命名规范的测试文件，并返回它们的相对路径列表。
    pytest 的文件发现规则是查找 'test_*.py' 或 '*_test.py' 文件。
    """
    test_files = []
    # 排除常见的目录
    exclude_dirs = {'.git', '.svn', 'CVS', '.hg', 'venv', '.venv', 'env', 'venvs', '__pycache__', 'build', 'dist'}
    
    repo_path_str = str(repo_path)
    for root, dirs, files in os.walk(repo_path_str, topdown=True):
        # 从遍历中排除指定目录
        dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith('.')]
        
        for file in files:
            if (file.startswith("test") and file.endswith(".py")) \
                or (file.startswith("new_test") and file.endswith(".py")) \
                or file.endswith("test.py") or file.endswith("tests.py"):
                full_path = os.path.join(root, file)
                relative_path = os.path.relpath(full_path, repo_path_str)
                test_files.append(relative_path)
    return test_files

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run repo evaluation.")
    parser.add_argument(
        "--dataset_file",
        type=str,
        default="../data/python_dataset.json",
        help="Path to dataset json file",
    )
    parser.add_argument(
        "--prediction_path",
        type=str,
        default=None,
        help="Path to prediction json file",
    )
    parser.add_argument(
        "--output_path",
        type=str,
        default=None,
        help="Path to output json file",
    )
    parser.add_argument(
        "--target_repos",
        type=str,
        default=None,
        help="Target repos to evaluate, if is None then evaluate all repos in the prediction file",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of workers for parallel evaluation",
    )
    args = parser.parse_args()
    # 读取dataset
    dataset = load_file(args.dataset_file)
    dataset_dict = {item["repo_name"]: item for item in dataset}
    # 读取结果
    predictions = load_file(args.prediction_path)

    report_list = []
    # 过滤需要评估的项目
    items_to_eval = predictions
    if args.target_repos is not None:
        items_to_eval = [
            item for item in predictions if item["repo_name"] in args.target_repos
        ]
    
    for item in items_to_eval:
        assert os.path.exists(item["repo_source_path"]), f"Repo source path {item['repo_source_path']} does not exist"
        repo_path = os.path.join(os.path.dirname(args.prediction_path), item["repo_name"], item["repo_name"])
        if os.path.exists(repo_path):
            shutil.rmtree(repo_path)
        shutil.copytree(item["repo_source_path"], repo_path)
        patch_path = os.path.join(os.path.dirname(args.prediction_path), item["repo_name"], f"{item['repo_name']}.patch")
        patch_idx = max([int(k) for k in item["model_patch"].keys()])
        patch = item["model_patch"][str(patch_idx)]
        save_file(patch_path, patch)
        success = apply_patch(Path(patch_path), Path(repo_path))
        assert success, f"Failed to apply patch {patch_path} to {repo_path}"
        add_tests_init_file(repo_path)
        test_files = find_pytest_files(repo_path)
        item["test_files"] = test_files
        if not success:
            logger.error(f"Failed to apply patch {patch_path} to {repo_path}")
            raise Exception(f"Failed to apply patch {patch_path} to {repo_path}")
        item["repo_path"] = repo_path

    if args.workers > 1:
        # 并行评估
        logger.info(
            f"Evaluating {len(items_to_eval)} repos with {args.workers} workers"
        )
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=args.workers
        ) as executor:
            future_to_item = {
                executor.submit(evaluate_repo, item): item for item in items_to_eval
            }
            # 使用 tqdm 包装 as_completed 来显示进度条
            for future in tqdm(
                concurrent.futures.as_completed(future_to_item),
                total=len(items_to_eval),
                desc="Evaluating Repos",
            ):
                item = future_to_item[future]
                try:
                    result = future.result()
                except Exception as e:
                    # 确保错误信息也被记录到文件中
                    logger.exception(
                        f"Error evaluating {item['repo_name']}"
                    )  # 使用 logger.exception 记录完整堆栈跟踪
                    item["tests"] = None
                    report_list.append(item)
                else:
                    if result:
                        report_dicts = {k: v.to_dict() for k, v in result.items()}
                        item["tests"] = report_dicts
                        report_list.append(item)
    else:
        # 单线程评估
        logger.info(f"Evaluating {len(items_to_eval)} repos with single thread")
        for item in tqdm(items_to_eval, desc="Evaluating Repos"):
            try:
                result = evaluate_repo(item)
                if result:
                    report_dicts = {k: v.to_dict() for k, v in result.items()}
                    item["tests"] = report_dicts
                    report_list.append(item)
            except Exception as e:
                logger.exception(f"Error evaluating {item['repo_name']}")

    details = []
    overall_stats = {
        "ori_tests": {
            "success_count": 0, "failed_count": 0, "error_count": 0, "skipped_count": 0,
            "unknown_count": 0, "total_count": 0, "rates": [],
            "coverage_rates": [], "covered_lines": 0, "num_statements": 0,
            "covered_branches": 0, "missing_branches": 0, "num_branches": 0,
        },
        "new_tests": {
            "success_count": 0, "failed_count": 0, "error_count": 0, "skipped_count": 0,
            "unknown_count": 0, "total_count": 0, "rates": [],
            "coverage_rates": [], "covered_lines": 0, "num_statements": 0,
            "covered_branches": 0, "missing_branches": 0, "num_branches": 0,
        },
        "all_tests": {
            "success_count": 0, "failed_count": 0, "error_count": 0, "skipped_count": 0,
            "unknown_count": 0, "total_count": 0, "rates": [],
            "coverage_rates": [], "covered_lines": 0, "num_statements": 0,
            "covered_branches": 0, "missing_branches": 0, "num_branches": 0,
        },
    }

    for i, item in enumerate(report_list):
        if not item.get("tests"):
            continue

        eval_results_by_type = copy.deepcopy(item["tests"])
        new_eval_tests_agg = {}

        for test_type, eval_report in eval_results_by_type.items():
            stats_agg = overall_stats[test_type]
            
            eval_report["total_count"] = (
                eval_report["success_count"]
                + eval_report["failed_count"]
                + eval_report["error_count"]
                + eval_report["skipped_count"]
                + eval_report["unknown_count"]
            )

            if (eval_report["total_count"] - eval_report["skipped_count"]) > 0:
                eval_report["success_rate"] = eval_report["success_count"] / (
                    eval_report["total_count"] - eval_report["skipped_count"]
                )
            else:
                eval_report["success_rate"] = 0

            stats_agg["success_count"] += eval_report["success_count"]
            stats_agg["failed_count"] += eval_report["failed_count"]
            stats_agg["error_count"] += eval_report["error_count"]
            stats_agg["skipped_count"] += eval_report["skipped_count"]
            stats_agg["unknown_count"] += eval_report["unknown_count"]
            stats_agg["total_count"] += eval_report["total_count"]
            stats_agg["rates"].append(eval_report["success_rate"])
            
            if eval_report.get("coverage_report"):
                coverage_report = eval_report["coverage_report"]
                if coverage_report and coverage_report.get("num_statements"):
                    stats_agg["coverage_rates"].append(coverage_report.get("percent_covered", 0))
                    stats_agg["covered_lines"] += coverage_report.get("covered_lines", 0)
                    stats_agg["num_statements"] += coverage_report.get("num_statements", 0)
                    stats_agg["covered_branches"] += coverage_report.get("covered_branches", 0)
                    stats_agg["missing_branches"] += coverage_report.get("missing_branches", 0)
                    stats_agg["num_branches"] += coverage_report.get("num_branches", 0)
            
            new_eval_tests_agg[test_type] = eval_report

        details.append(
            {
                "repo_name": item["repo_name"],
                "eval_test": new_eval_tests_agg,
                "reference_test": dataset_dict[item["repo_name"]]["tests"],
            }
        )

    details.sort(key=lambda x: x["repo_name"])
    
    final_overall = {}
    for test_type, stats in overall_stats.items():
        if (stats["total_count"] - stats["skipped_count"]) > 0:
            success_rate = stats["success_count"] / (stats["total_count"] - stats["skipped_count"])
        else:
            success_rate = 0

        if stats["num_statements"] > 0:
            overall_coverage = (stats["covered_lines"] / stats["num_statements"]) * 100
        else:
            overall_coverage = 0
            
        if stats["num_branches"] > 0:
            overall_branch_coverage = (stats["covered_branches"] / stats["num_branches"]) * 100
        else:
            overall_branch_coverage = 0

        final_overall[test_type] = {
            "success_avg": np.mean(stats["rates"]) if stats["rates"] else 0,
            "success_rate": success_rate,
            "success_count": stats["success_count"],
            "failed_count": stats["failed_count"],
            "skipped_count": stats["skipped_count"],
            "error_count": stats["error_count"],
            "unknown_count": stats["unknown_count"],
            "total_count": stats["total_count"],
            "coverage_avg": np.mean(stats["coverage_rates"]) if stats["coverage_rates"] else 0,
            "overall_coverage": overall_coverage,
            "covered_branches": stats["covered_branches"],
            "missing_branches": stats["missing_branches"],
            "num_branches": stats["num_branches"],
            "overall_branch_coverage": overall_branch_coverage,
        }

    report = {
        "overall": final_overall,
        "details": details,
    }
    logger.info(
        f"Evaluation Report: \n{json.dumps(report['overall'], ensure_ascii=False, indent=4)}"
    )

    def F(obj):
        if isinstance(obj, dict):
            return {k: F(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [F(x) for x in obj]
        if isinstance(obj, str):
            return obj.encode("utf-8", "replace").decode("utf-8")
        return obj
    report = F(report)

    # 保存评估结果
    if args.output_path is None:
        args.output_path = os.path.join(os.path.dirname(args.prediction_path), "evaluation_test.json")
    with open(args.output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=4)
