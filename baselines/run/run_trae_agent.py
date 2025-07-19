#!/usr/bin/env python3
from pathlib import Path
import shutil
import subprocess
import json
import os
import argparse
from loguru import logger
from tqdm import tqdm
import docker

from harness.utils.constants import get_pre_install

CODEPATHS = {
    "6mini_holidayskr": {
        "code_paths": ["holidayskr"],
    },
    "chrisK824_retry": {
        "code_paths": ["retry_reloaded"],
    },
    "DanielAvdar_pandas-pyarrow": {
        "code_paths": ["pandas_pyarrow", "docs"],
    },
    "databrickslabs_pylint-plugin": {
        "code_paths": ["src", "scripts"],
    },
    "pga2rn_simple-sqlite3-orm": {
        "code_paths": ["src"],
    },
    "pomponchik_emptylog": {
        "code_paths": ["docs", "emptylog"],
    },
    "simonw_files-to-prompt": {
        "code_paths": ["files_to_prompt"],
    },
    "sr-murthy_continuedfractions": {
        "code_paths": ["docs", "src"],
    },
    "ul-mds_gecko": {
        "code_paths": ["docs", "gecko"],
    },
    "yezz123_pgqb": {
        "code_paths": ["pgqb", "scripts"],
    },
    "thomasborgen_hypermedia":{
        "code_paths": ["hypermedia"],
    },
    "amaslyaev_noorm":{
        "code_paths": ["noorm"],
    },
    "Halvani_alphabetic":{
        "code_paths": ["alphabetic"],
    },
    "Peter-van-Tol_pydantic-shapely":{
        "code_paths": ["docs", "src"],
    },
    "andrew000_FTL-Extract":{
        "code_paths": ["src"],
    },
    "dnlzrgz_memotica":{
        "code_paths": ["src"],
    },
    "ItsNotSoftware_lions":{
        "code_paths": ["lionsc"],
    },
    "BrianWeiHaoMa_csvuniondiff":{
        "code_paths": ["csvuniondiff"],
    },
    "makyol_landusemix":{
        "code_paths": ["docs","landusemix"],
    },
    "ParisNeo_pipmaster":{
        "code_paths": ["pipmaster", "docs"],
    },
}

def load_file(file_path):
    if file_path.endswith(".jsonl"):
        with open(file_path, "r") as f:
            return [json.loads(line) for line in f]
    elif file_path.endswith(".json"):
        with open(file_path, "r") as f:
            return json.load(f)
    else:
        logger.warning(f"Unknown file type return as text: {file_path}")
        with open(file_path, "r") as f:
            return f.read()

def save_file(file_path, data):
    if file_path.endswith(".jsonl"):
        with open(file_path, "w") as f:
            for item in data:
                f.write(json.dumps(item) + "\n")
    elif file_path.endswith(".json"):
        with open(file_path, "w") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    else:
        logger.warning(f"Unknown file type save as text: {file_path}")
        with open(file_path, "w") as f:
            f.write(data)


def build_repo_skeleton(repo_dir, skeletons):
    for sk in skeletons:
        file_path = sk['file_path']
        file_content = sk['code']
        if file_path.startswith("/"):
            logger.error(f"Skipping file {file_path} because it is a directory")
        os.makedirs(os.path.dirname(os.path.join(repo_dir, file_path)), exist_ok=True)
        with open(os.path.join(repo_dir, file_path), "w") as f:
            f.write(file_content)


def build_task_repo(ori_repos_dir, save_repo_dir, instance, mode="test"):
    # import pdb; pdb.set_trace()
    ori_repo_path = f"{ori_repos_dir}/{instance['repo_name']}"
    save_repo_path = os.path.join(save_repo_dir, instance['repo_name'])
    os.makedirs(save_repo_dir, exist_ok=True)
    if os.path.exists(save_repo_path):
        shutil.rmtree(save_repo_path)
    shutil.copytree(ori_repo_path, save_repo_path)
    
    instance['code_paths'] = CODEPATHS[instance['repo_name']]['code_paths']
    
    for code_path in instance['code_paths']:
        shutil.rmtree(os.path.join(save_repo_dir, instance['repo_name'], code_path))
    
    if mode == "full_skeleton":
        skeleton = instance["full_code_skeleton_structured"]
        build_repo_skeleton(save_repo_path, skeleton)
    elif mode == "min_skeleton":
        skeleton = instance["minimal_code_skeleton_structured"]
        build_repo_skeleton(save_repo_path, skeleton)
    elif mode == "test":
        pass
    else:
        raise ValueError(f"Invalid mode: {mode}")
    
    pre_install_cmds = get_pre_install(instance['repo_name'])
    if pre_install_cmds is not None:
        for cmd in pre_install_cmds:
            logger.info(f"pre_install_cmd: {cmd}")
            os.system(f"cd {save_repo_path} && {cmd}")
            
    # os.system(f"cd {save_repo_path} && rm -rf .git && git init && git add . && git commit -m 'Initial commit'")

    return save_repo_path

def create_tasks(args):
    dataset = load_file(args.dataset_file)
    tasks = []
    save_problem_statement_dir = os.path.join(args.output_dir, "problem_statement")
    os.makedirs(save_problem_statement_dir, exist_ok=True)
    save_repo_dir = os.path.join(args.output_dir, "runs")
    os.makedirs(save_repo_dir, exist_ok=True)
    traj_dir = os.path.join(save_repo_dir, "traj")
    os.makedirs(traj_dir, exist_ok=True)
    ori_repos_dir = args.repos_dir
    for instance in tqdm(dataset, desc="Creating tasks"):
        if args.instance_ids is not None and instance['repo_name'] not in args.instance_ids:
            continue
        problem_statement = instance['SRS_document']
        repo_path = build_task_repo(ori_repos_dir, save_repo_dir, instance, mode="full_skeleton")
        repo_name = instance['repo_name']
        if args.nost:
            # 使用无sequentialthinking的trae-agent
            image_name = f"lpbench.eval.trae.nost.{repo_name.replace(':', '_').lower()}:latest"
            container_name = f"lpbench_eval_trae_nost_{repo_name.replace(':', '_').lower()}"
        else:
            image_name = f"lpbench.eval.trae.{repo_name.replace(":", "_").lower()}:latest"
            container_name = f"lpbench_eval_trae_{repo_name.replace(":", "_").lower()}"
        tasks.append({
            "instance_id": instance['repo_name'],
            "problem_statement": problem_statement,
            "problem_statement_path": os.path.join(save_problem_statement_dir, f"{instance['repo_name']}.md"),
            "repo_path": repo_path,
            "config_path": args.agent_config,
            "traj_dir": traj_dir,
            "image_name": image_name,
            "container_name": container_name,
        })
        problem_statement_path = os.path.join(save_problem_statement_dir, f"{instance['repo_name']}.md")
        with open(problem_statement_path, "w") as f:
            f.write(problem_statement)
        
    return tasks

def build_container_for_task(task: dict) -> docker.models.containers.Container | None:
    """
    为指定的任务创建一个 Docker 容器。
    会进行如下操作：
    1. 将本机对应的仓库目录挂载到容器的 /{repo_name} 目录下。
    2. 把problem_statement_path 的文档挂载到容器的 /problem_statement.md。
    """
    repo_name = task['instance_id']
    repo_path = task['repo_path']
    problem_statement_path = task['problem_statement_path']
    config_path = task['config_path']
    traj_dir = task['traj_dir']
    image_name = task['image_name']
    container_name = task['container_name']
    
    client = docker.from_env()
    # # 将镜像名称和容器名称转换为小写
    # image_name = f"lpbench.eval.trae.{repo_name.replace(":", "_").lower()}:latest"
    # container_name = f"lpbench_eval_trae_{repo_name.replace(":", "_").lower()}"
    
    # Remove existing container if it exists
    try:
        existing_container = client.containers.get(container_name)
        existing_container.remove(force=True)
    except docker.errors.NotFound:
        pass
    uid = os.getuid()
    gid = os.getgid()
    # Create and start the container
    try:
        container = client.containers.run(
            image=image_name,
            name=container_name,
            command="/bin/bash",
            volumes={
                repo_path: {'bind': f'/{repo_name}', 'mode': 'rw'},  # 挂载仓库目录到容器的 /{repo_name} 目录
                problem_statement_path: {'bind': '/problem_statement.md', 'mode': 'ro'},  # 挂载问题描述文档到容器的 /problem_statement.md
                config_path: {'bind': '/config.json', 'mode': 'ro'},  # 挂载配置文件到容器的 /config.json
                traj_dir: {'bind': '/traj', 'mode': 'rw'},  # 挂载轨迹目录到容器的 /trae_agent/traj
            },
            detach=True,  # 分离模式运行容器
            tty=True,     # 允许伪终端
            stdin_open=True, # 允许标准输入
            remove=True,  # 自动删除容器
            user=f"{uid}:{gid}", # 设置容器内的用户为当前用户
            network_mode="host", # 使用主机网络模式
            environment={
                "HTTP_PROXY":  "http://127.0.0.1:10809",
                "HTTPS_PROXY": "http://127.0.0.1:10809",
                "ALL_PROXY":   "http://127.0.0.1:10809",
                "NO_PROXY":    "localhost,127.0.0.1",
            }
        )
    except Exception as e:
        logger.error(f"Failed to create container for {repo_name}: {e}")
        return None
    
    logger.info(f"Created Docker container {container_name} for {repo_name}")
    return container

if __name__ == "__main__":
    # 所有路径参数都必须是绝对路径
    parser = argparse.ArgumentParser(description="Run PR Agent with multithreading")
    parser.add_argument("--num-threads", type=int, default=1, help="Maximum number of worker threads")
    parser.add_argument("--dataset-file", type=str, default="./data/datasets/pypi-2024-01-dataset-final.json",
                        help="Path to the dataset file")
    parser.add_argument("--instance-ids", type=str, default=None,
                        help="Instance IDs")
    parser.add_argument("--repos-dir", type=str, default="./data/repos",
                        help="Path to the repos directory")
    parser.add_argument("--output-dir", type=str, default="data/pr_agent_results",
                        help="Path to the output directory")
    parser.add_argument("--clean", action="store_true", default=False,
                        help="Clean the output directory")
    parser.add_argument("--agent-config", type=str, default="default",
                        help="Agent config file path")
    parser.add_argument(
        "--nost",
        action="store_true",
    )
    args = parser.parse_args()
    if args.clean:
        logger.info(f"Cleaning output directory: {args.output_dir}/runs and {args.output_dir}/traj")
        shutil.rmtree(os.path.join(args.output_dir, "runs"), ignore_errors=True)
        shutil.rmtree(os.path.join(args.output_dir, "traj"), ignore_errors=True)
    
    os.makedirs(os.path.join(args.output_dir, "runs"), exist_ok=True)
    
    tasks = create_tasks(args)

    # Collect results
    results = []
    client = docker.from_env()
    for task in tasks:
        repo_name = task['instance_id']
        repo_path = task['repo_path']
        problem_statement = task['problem_statement']
        trajectory_file_path = os.path.join(args.output_dir, "traj", f"{repo_name}_trajectory.json")
        
        container = build_container_for_task(task)
        
        if container is None:
            logger.error(f"Failed to create container for {repo_name}. Skipping task.")
            results.append({
                "repo_name": repo_name,
                "repo_dir": repo_path,
                "result": "Container creation failed"
            })
            continue
        
        # Run the agent
        task_description = f'"Develop a Python package based on the requirment document, whose absolute path is `/problem_statement.md`. Some of the code skeleton is already provided in the repository, but you need to implement the missing parts. Make sure every code file is inspected and completed."'
        
        cmd = f"trae-cli run {task_description} --working-dir /{repo_name} --config-file /config.json --trajectory-file /traj/{repo_name}_trajectory.json"
        
        # 在容器中运行agent命令
        try:
            logger.info(f"Running agent for {repo_name} at {repo_path}")
            
            # 使用流式输出执行命令
            exec_result = container.exec_run(
                cmd,
                workdir=f"/{repo_name}",
                tty=True,
                stream=True,
                demux=True,
            )
            
            stdout_lines = []
            stderr_lines = []
            
            # 实时读取流式输出
            for stdout, stderr in exec_result.output:
                if stdout:
                    stdout_text = stdout.decode('utf-8', errors='replace')
                    stdout_lines.append(stdout_text)
                    logger.info(f"[{repo_name}] {stdout_text.rstrip()}")
                    
                if stderr:
                    stderr_text = stderr.decode('utf-8', errors='replace')
                    stderr_lines.append(stderr_text)
                    logger.error(f"[{repo_name}] {stderr_text.rstrip()}")
            
            stdout_output = ''.join(stdout_lines)
            stderr_output = ''.join(stderr_lines)
            full_output = stdout_output + stderr_output

            if stderr_output:
                if stderr_output:
                    logger.error(f"Error output: {stderr_output}")
                results.append({
                    "repo_name": repo_name,
                    "repo_dir": repo_path,
                    "result": f"Error {full_output}"
                })
            else:
                logger.success(f"Agent run completed for {repo_name}")
                results.append({
                    "repo_name": repo_name,
                    "repo_dir": repo_path,
                    "result": "Success",
                })
        except Exception as e:
            logger.error(f"Error running agent for {repo_name}: {e}")
            results.append({
                "repo_name": repo_name,
                "repo_dir": repo_path,
                "result": str(e)
            })
        finally:
            # 确保容器被正确停止和删除
            try:
                container.stop(timeout=20)
                logger.info(f"Container {container.name} stopped for {repo_name}")
            except Exception as e:
                logger.warning(f"Failed to stop container for {repo_name}: {e}")
                try:
                    container.kill()
                    logger.info(f"Container {container.name} killed for {repo_name}")
                except Exception as kill_e:
                    logger.error(f"Failed to kill container for {repo_name}: {kill_e}")
        
    # 运行完之后，会在 output_dir 目录下生成每个任务的结果 generation.jsonl
    # 该文件每一项包含repo_name, repo_dir 和 result 字段
    # Save results to output file
    with open(os.path.join(args.output_dir, "generation.jsonl"), "w") as f:
        for result in results:
            f.write(json.dumps(result) + "\n")
    
    logger.success(f"All tasks completed. Results saved to {args.output_dir}/generation.jsonl")

