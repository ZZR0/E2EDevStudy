"""
运行CodeS的生成脚本
调用了from_scratch_inference.py和transfer_output_to_repo.py两个脚本
对这两个脚本以及相关的prompt均进行了修改
"""

import argparse
import os
import subprocess
import sys
from loguru import logger
import json

# CodeS 脚本所在路径，包含 from_scratch_inference.py 和 transfer_output_to_repo.py
CODES_PATH = "/hdd1/zzr/collect_data/baselines/CodeS"

INSTRUCTION = """
Here are requirements document, a part of code skeleton and some reference test cases for a project.
Key implementation constraints:
- Build upon the provided code skeleton
- You MAY create new modules/files when necessary
- Implementation MUST PASS all provided test cases
- All interfaces MUST strictly adhere to:
  a) Function signatures defined in test cases
  b) Return data formats demonstrated in test samples
  c) Class method patterns shown in test expectations
- Any deviation from test-defined interfaces will cause failure
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset-file",
        type=str,
        default="./data/datasets/pypi-2024-01-dataset-final.json",
        help="Path to the dataset file",
    )
    parser.add_argument(
        "--inference-output",
        type=str,
        default="/hdd1/zzr/collect_data/baselines/run/CodeS_results/from_scratch_inference_results",
        help="存放 from_scratch_inference.py 的中间输出结果的根目录",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gemini-2.5-pro-preview-05-06",
        help="使用的模型名称，会作为子目录名",
    )
    parser.add_argument("--base_url", type=str, default="http://127.0.0.1:4000/v1")
    parser.add_argument(
        "--api-key",
        type=str,
        default="sk-2Wyk3U0TrbVTYs18czoImh2UYHS17yepEC5OsfbABMM7EVxm",
    )
    parser.add_argument(
        "--final-output",
        type=str,
        default="data/CodeS_results",
        help="最终生成完整仓库的输出目录",
    )
    args = parser.parse_args()

    # 准备必要目录
    cleaned_repos_root = os.path.join(CODES_PATH, "benchmark_repos")
    os.makedirs(cleaned_repos_root, exist_ok=True)
    os.makedirs(args.inference_output, exist_ok=True)
    os.makedirs(args.final_output, exist_ok=True)

    # 从 dataset-file 中读取数据集
    with open(args.dataset_file, "r") as f:
        dataset = json.load(f)

    # 脚本路径，对脚本进行了修改以使用llm api
    from_scratch_script = (
        CODES_PATH + "/validation/evaluation_scripts/from_scratch_inference.py"
    )
    transfer_script = (
        CODES_PATH + "/validation/evaluation_scripts/transfer_output_to_repo.py"
    )

    # 对数据集中每个项目执行生成和转移
    # 临时只对一个项目进行测试
    for data in dataset[2:3]:
        
        name = data["repo_name"]
        SRS_document = data["SRS_document"]
        minimal_code_skeleton = str(data["minimal_code_skeleton"])
        minimal_test_cases = str(data["minimal_test_cases"])
        test_cases = str(data["test_cases"])
        full_code_skeleton = str(data["full_code_skeleton"])
        
        input_readme_file_content = (
            INSTRUCTION
            + SRS_document
            + "\nHere is a part of code skeleton:\n"
            + full_code_skeleton
            + "\nHere are some test cases:\n"
            + test_cases
        )

        # 创建仓库输入目录并写 README.md
        repo_input_dir = os.path.join(cleaned_repos_root, name)
        os.makedirs(repo_input_dir, exist_ok=True)
        readme_path = os.path.join(repo_input_dir, "README.md")
        with open(readme_path, "w") as f:
            f.write(input_readme_file_content)

        # 运行 from_scratch_inference.py
        logger.info(f"开始对仓库 {name} 运行 from_scratch_inference 脚本")
        cmd1 = [
            sys.executable,
            from_scratch_script,
            "--project",
            name,
            "--repo_dir",
            cleaned_repos_root,
            "--output_dir",
            args.inference_output,
            "--model",
            args.model,
            "--base_url",
            args.base_url,
            "--api_key",
            args.api_key,
        ]
        res1 = subprocess.run(cmd1, check=False)
        if res1.returncode != 0:
            logger.error(
                f"from_scratch_inference 脚本运行失败，返回码：{res1.returncode}"
            )
            continue

        # 运行 transfer_output_to_repo.py
        logger.info(f"开始对仓库 {name} 运行 transfer_output_to_repo 脚本")
        cmd2 = [
            sys.executable,
            transfer_script,
            "--project",
            name,
            "--input_dir",
            os.path.join(args.inference_output, args.model),
            "--output_dir",
            args.final_output,
        ]
        res2 = subprocess.run(cmd2, check=False)
        if res2.returncode != 0:
            logger.error(
                f"transfer_output_to_repo 脚本运行失败，返回码：{res2.returncode}"
            )
            continue


if __name__ == "__main__":
    main()
