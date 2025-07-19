import copy
import os
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


def setup_repo(container, build_path, workdir, repo_info, quick_mode=False):
    logger.info(f"Setup repo in quick mode: {quick_mode}")
    # 将repo代码复制到容器中
    copy_to_container(container, repo_info["repo_dir"], workdir)

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
    setup_py_path = os.path.join(repo_info["repo_dir"], "setup.py")
    pyproject_toml_path = os.path.join(repo_info["repo_dir"], "pyproject.toml")
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

    report = EvalReport(repo_info["repo_name"])

    dockerfile_content = DOCKERFILE.format(workdir=f"/{repo_info['repo_name']}")

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
                f"{image_tag}.{repo_info['repo_dir'].strip('/').replace('/', '_')}"
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
            return report

        workdir = f'/{repo_info["repo_name"]}'

        # import pdb; pdb.set_trace()
        # 设置repo环境
        success = setup_repo(
            container, build_path, workdir, repo_info, quick_mode=quick_mode
        )
        if not success:
            logger.error(f"Failed to setup repo for {repo_info['repo_name']}")
            return report

        # 在container中运行测试
        test_cmd = f"""PYTHONPATH=.:$PYTHONPATH pytest --timeout={SINGLE_TEST_TIMEOUT} -rA --cov --cov-context=test -vv --cov-config=".coveragerc_tmp" --cov-report=json:coverage_report.json --json-report --json-report-file=pytest_report.json"""
        if get_test_cmd(repo_info["repo_name"]) is not None:
            test_cmd = get_test_cmd(repo_info["repo_name"])

        test_command = f"""bash -c 'COVERAGERC_CONTENT="[run]\nbranch = true\nsource = .\nomit =\n    tests/*\n    test/*\n    */site-packages/*\n\n[json]\nshow_contexts = true\n"; echo "$COVERAGERC_CONTENT" > ".coveragerc_tmp"; {test_cmd}'"""

        logger.info(f"Start testing: {test_command}")
        exec_result = container.exec_run(test_command, workdir=workdir)
        logger.info(f"Test result: {exec_result.output.decode("utf-8")}")
        exec_result = container.exec_run("cat ./pytest_report.json", workdir=workdir)
        pytest_result = exec_result.output.decode("utf-8")
        # logger.debug(f"pytest_result: {pytest_result}") # 调试输出
        pytest_result = json.loads(pytest_result)
        report.set_detail(pytest_result)

        try:
            exec_result = container.exec_run("cat ./coverage_report.json", workdir=workdir)
            coverage_result = exec_result.output.decode("utf-8")
            coverage_result = json.loads(coverage_result)
        except Exception as e:
            logger.error(f"Error getting coverage report for result: `{coverage_result}`")
            coverage_result = {"totals": {"error": 1, "percent_covered": 0}}

        for test in pytest_result["tests"]:
            report.add_test_result(test["nodeid"], test["outcome"])

        # for file_name, file_cov in coverage_result["files"].items():
        #     report.add_coverage_result(file_name, file_cov)

        report.add_coverage_report(coverage_result["totals"])

        report.finalize()
        logger.success(f"Test case results for {repo_info['repo_name']}:")
        logger.info(f"success rate: {report.success_rate}")
        logger.info(f"success count: {report.success_count}")
        logger.info(f"failed count: {report.failed_count}")
        logger.info(f"skipped count: {report.skipped_count}")
        logger.info(f"error count: {report.error_count}")
        logger.info(f"unknown count: {report.unknown_count}")
        logger.info(f"coverage rate: {report.coverage_report['percent_covered']}")

        # import pdb; pdb.set_trace()
    except Exception as e:
        logger.error(f"Error evaluating {repo_info['repo_name']}: {str(e)}")
    finally:
        if not quick_mode:
            save_container(container, f"lpbench.eval.{repo_info['repo_name']}")
        # 停止运行并删除容器以及对应的镜像
        # import pdb; pdb.set_trace()
        stop_remove_container(container)
        # pass
    return report


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
                    if result is not None:
                        report_dict = result.to_dict()
                        item["tests"] = report_dict
                        report_list.append(item)
    else:
        # 单线程评估
        logger.info(f"Evaluating {len(items_to_eval)} repos with single thread")
        for item in tqdm(items_to_eval, desc="Evaluating Repos"):
            try:
                result = evaluate_repo(item)
                if result is not None:
                    report_dict = result.to_dict()
                    item["tests"] = report_dict
                    report_list.append(item)
            except Exception as e:
                logger.exception(f"Error evaluating {item['repo_name']}")

    details = []
    (
        success_count,
        failed_count,
        error_count,
        skipped_count,
        unknown_count,
        total_count,
    ) = (0, 0, 0, 0, 0, 0)
    for i, item in enumerate(report_list):
        new_eval_tests = copy.deepcopy(item["tests"])
        new_eval_tests["total_count"] = dataset_dict[item["repo_name"]]["tests"]["total_count"]
        new_eval_tests["failed_count"] = (
            new_eval_tests["total_count"]
            - new_eval_tests["success_count"]
            - new_eval_tests["error_count"]
            - new_eval_tests["skipped_count"]
            - new_eval_tests["unknown_count"]
        )
        new_eval_tests["success_rate"] = new_eval_tests["success_count"] / (
            new_eval_tests["total_count"] - new_eval_tests["skipped_count"]
        )

        success_count += new_eval_tests["success_count"]
        failed_count += new_eval_tests["failed_count"]
        error_count += new_eval_tests["error_count"]
        skipped_count += new_eval_tests["skipped_count"]
        unknown_count += new_eval_tests["unknown_count"]
        total_count += new_eval_tests["total_count"]

        details.append(
            {
                "repo_name": item["repo_name"],
                "eval_test": new_eval_tests,
                "ori_test": dataset_dict[item["repo_name"]]["tests"],
            }
        )
    details.sort(key=lambda x: x["repo_name"])
    report = {
        "overall": {
            "success_avg": np.mean(
                [item["eval_test"]["success_rate"] for item in details]
            ),
            "success_rate": success_count / (total_count - skipped_count),
            "success_count": success_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "error_count": error_count,
            "unknown_count": unknown_count,
            "total_count": total_count,
        },
        "details": details,
    }
    logger.info(
        f"Evaluation Report: \n{json.dumps(report['overall'], ensure_ascii=False, indent=4)}"
    )
    # 保存评估结果
    with open(args.output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=4)
