#!/usr/bin/env python3
from pathlib import Path
import random
import shutil
import subprocess
import json
import os
import argparse
from loguru import logger
from tqdm import tqdm

from harness.utils.constants import CODEPATHS, get_pre_install, apply_patch, check_env_cmd

VENV_PATH = "./baselines/SWE-agent/.venv"
SWE_AGENT_PATH = "./baselines/SWE-agent"


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


def _remove_paths(repo_path, paths_to_remove):
    for p in paths_to_remove:
        path_to_remove = os.path.join(repo_path, p)
        if os.path.isdir(path_to_remove):
            shutil.rmtree(path_to_remove)
        elif os.path.isfile(path_to_remove):
            os.remove(path_to_remove)


def extract_patch_from_traj(traj_path):
    """
    从traj文件中的history属性读取bash命令，从中获取带有pip install或export命令的bash命令，
    然后运行以更新环境。
    """
    patches_dict = {}
    # 根据 prediction_path 和 repo_name 构建 traj 文件的路径
    if not os.path.exists(traj_path):
        logger.warning(f"Trajectory file not found for {traj_path}, skipping environment setup from trajectory.")
        raise FileNotFoundError(f"Trajectory file not found for {traj_path}")
    
    with open(traj_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for i, entry in enumerate(data["trajectory"]):
        if "diff" in entry["state"]:
            patches_dict[i] = entry["state"]["diff"]
    return patches_dict

def extract_commands_from_traj(traj_path):
    """
    从traj文件中的history属性读取bash命令，从中获取带有pip install或export命令的bash命令，
    然后运行以更新环境。
    """
    commands_to_run = []
    
    # 根据 prediction_path 和 repo_name 构建 traj 文件的路径
    if not os.path.exists(traj_path):
        logger.warning(f"Trajectory file not found for {traj_path}, skipping environment setup from trajectory.")
        raise FileNotFoundError(f"Trajectory file not found for {traj_path}")

    with open(traj_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for entry in data["history"]:
        if entry.get("role") == "assistant" and "tool_calls" in entry:
            tool_calls = entry.get("tool_calls", [])
            if not isinstance(tool_calls, list):
                continue
            for call in tool_calls:
                if (
                    isinstance(call, dict)
                    and "function" in call
                    and isinstance(call.get("function"), dict)
                    and "name" in call.get("function")
                ):
                    tool_name = call["function"]["name"]
                    if tool_name == "bash":
                        try:
                            # The 'arguments' field is a JSON string.
                            args_str = call["function"].get("arguments", "{}")
                            args_json = json.loads(args_str)
                            command = args_json.get("command")
                            commands_to_run.append(command)
                        except (json.JSONDecodeError, AttributeError):
                            # Ignore if arguments are not as expected
                            pass

    return commands_to_run


def build_repo_skeleton(repo_dir, skeletons):
    for sk in skeletons:
        file_path = sk['file_path']
        file_content = sk['code']
        if file_path.startswith("/"):
            logger.error(f"Skipping file {file_path} because it is a directory")
        os.makedirs(os.path.dirname(os.path.join(repo_dir, file_path)), exist_ok=True)
        with open(os.path.join(repo_dir, file_path), "w") as f:
            f.write(file_content)


def build_task_repo(args, ori_repos_dir, save_repo_dir, instance, mode="debug"):
    if mode == "eval_test":
        model_patch_path = os.path.join(save_repo_dir, "../runs/generation.jsonl")
        model_patch = load_file(model_patch_path)
        model_patch = [p for p in model_patch if p['repo_name'] == instance['repo_name']][0]['model_patch']
        max_patch_step = max([int(k) for k in model_patch.keys()])
        choice_step = min(args.eval_step, max_patch_step)
        patch = model_patch[str(choice_step)]
    elif mode == "eval_judge":
        model_patch_path = os.path.join(save_repo_dir.replace("repos_eval_judge", "runs_eval_test"), "generation.jsonl")
        model_patch = load_file(model_patch_path)
        model_patch = [p for p in model_patch if p['repo_name'] == instance['repo_name']][0]['model_patch']
        max_patch_step = max([int(k) for k in model_patch.keys()])
        patch = model_patch[str(max_patch_step)]
    else:
        patch = None
    
    if mode == "eval_test":
        ori_repo_path = os.path.join(save_repo_dir.replace(f"repos_eval_test_{args.eval_step}", "repos"), instance['repo_name'])
    elif mode == "eval_judge":
        ori_repo_path = os.path.join(save_repo_dir.replace(f"repos_eval_judge", "repos_eval_test"), instance['repo_name'])
    elif mode != "debug":
        ori_repo_path = f"{ori_repos_dir}/{instance['repo_name']}"
    else: # debug mode uses the original repo path for simplicity
        ori_repo_path = f"{ori_repos_dir}/{instance['repo_name']}"
        
    save_repo_path = os.path.join(save_repo_dir, instance['repo_name'])
    os.makedirs(save_repo_dir, exist_ok=True)
    if os.path.exists(save_repo_path):
        shutil.rmtree(save_repo_path)
    shutil.copytree(ori_repo_path, save_repo_path)
    
    instance['code_paths'] = CODEPATHS[instance['repo_name']]['code_paths']
    instance['test_paths'] = CODEPATHS[instance['repo_name']]['test_paths']
    
    if mode in ["full_skeleton", "min_skeleton"]:
        _remove_paths(save_repo_path, instance['code_paths'])
        if mode == "full_skeleton":
            skeleton = instance["full_code_skeleton_structured"]
        else:
            skeleton = instance["minimal_code_skeleton_structured"]
        build_repo_skeleton(save_repo_path, skeleton)
    elif mode == "from_scratch":
        _remove_paths(save_repo_path, instance['code_paths'])
        _remove_paths(save_repo_path, instance['test_paths'])
    elif mode in ["eval_test", "eval_judge", "debug"]:
        pass
    else:
        raise ValueError(f"Invalid mode: {mode}")
    
    if patch is not None:
        patch_path = os.path.join(save_repo_path, f"../{instance['repo_name']}.patch")
        save_file(patch_path, patch)
        success = apply_patch(Path(patch_path), Path(save_repo_path))
        if not success:
            raise ValueError(f"Failed to apply patch {patch_path} to {save_repo_path}")
            return None
    
    # if mode in ["eval_test"]:
    #     _remove_paths(save_repo_path, instance['test_paths']+["tests"])
    
    pre_install_cmds = get_pre_install(instance['repo_name'])
    if pre_install_cmds is not None:
        for cmd in pre_install_cmds:
            logger.info(f"pre_install_cmd: {cmd}")
            os.system(f"cd {save_repo_path} && {cmd}")
            
    os.system(f"cd {save_repo_path} && rm -rf .git && git init && git add . && git commit -m 'Initial commit'")

    return os.path.join(save_repo_dir, instance['repo_name'])

def build_problem_statement(ori_repo_path, instance, mode):
    test_files = [f.split('::')[0] for f in instance['tests']['test_case_result'].keys()]
    test_files = list(set([f for f in test_files if f.endswith('.py')]))
    
    reference_tests = ""
    for test_file in test_files:
        test_file_path = os.path.join(ori_repo_path, test_file)
        if not os.path.exists(test_file_path):
            continue
        with open(test_file_path, "r") as f:
            test_file_content = f.read()
        reference_tests += f"### `{test_file}`:\n```python\n{test_file_content}\n```\n\n"
    
    # import pdb; pdb.set_trace()
    if "test_replace" in CODEPATHS[instance['repo_name']]:
        for replace_test in CODEPATHS[instance['repo_name']]['test_replace']:
            reference_tests = reference_tests.replace(replace_test[0], replace_test[1])
    # if mode == "agent_eval":
    #     problem_statement = (
    #         "Requirements Document:\n"
    #         "<requirements_document>\n"
    #         f"{instance['SRS_document'].strip()}\n"
    #         "</requirements_document>\n"
    #         "\n"
    #         "Reference Test Cases:\n"
    #         "<reference_tests>\n"
    #         f"{reference_tests.strip()}\n"
    #         "</reference_tests>"
    #     )
    #     return problem_statement
    # else:
    #     return instance['SRS_document']
    
    return instance['SRS_document'], reference_tests  


def create_tasks(args, source_results=None):
    swe_datasets = load_file(args.dataset_file)
    
    if args.agent_config == "eval_test":
        save_repo_dir = os.path.join(args.output_dir, f"repos_eval_test_{args.eval_step}")
        runs_dir = os.path.join(args.output_dir, f"runs_eval_test_{args.eval_step}")
    elif args.agent_config == "eval_judge":
        save_repo_dir = os.path.join(args.output_dir, f"repos_eval_judge_{args.eval_step}")
        runs_dir = os.path.join(args.output_dir, f"runs_eval_judge_{args.eval_step}")
    else:
        save_repo_dir = os.path.join(args.output_dir, "repos")
        runs_dir = os.path.join(args.output_dir, "runs")
    
    save_problem_statement_dir = os.path.join(save_repo_dir, f"_problem_statement")
    ori_repos_dir = args.repos_dir
    
    os.makedirs(save_problem_statement_dir, exist_ok=True)
    os.makedirs(save_repo_dir, exist_ok=True)
    
    mode = "full_skeleton"
    pytest_cmd = "pytest -x -v -rfE --disable-warnings -o asyncio_default_fixture_loop_scope=function --timeout=250"
    if args.agent_config == "from_scratch":
        mode = "from_scratch"
        pytest_cmd = "pytest -x -v -rfE --disable-warnings -o asyncio_default_fixture_loop_scope=function --timeout=250"
    elif args.agent_config == "eval_test":
        mode = "eval_test"
        pytest_cmd = "pytest -v -rfE --tb=short --disable-warnings -o asyncio_default_fixture_loop_scope=function --timeout=250"
    elif args.agent_config == "eval_judge":
        mode = "eval_judge"
        pytest_cmd = "pytest -v -rfE --tb=short --disable-warnings -o asyncio_default_fixture_loop_scope=function --timeout=250"
    elif args.agent_config == "dev_test":
        mode = "from_scratch"
        pytest_cmd = "pytest -v -rfE --tb=short --disable-warnings -o asyncio_default_fixture_loop_scope=function --timeout=250"
    elif args.agent_config == "design_dev_test":
        mode = "from_scratch"
        pytest_cmd = "pytest -v -rfE --tb=short --disable-warnings -o asyncio_default_fixture_loop_scope=function --timeout=250"
    
    swe_agent_datasets = []
    for swe_instance in swe_datasets:
        ori_repo_path = os.path.join(ori_repos_dir, swe_instance['repo_name'])
        if args.instance_ids is not None and swe_instance['repo_name'] not in args.instance_ids:
            continue
        if not os.path.exists(ori_repo_path):
            logger.warning(f"Skipping repo {swe_instance['repo_name']} because it is not found in {ori_repos_dir}")
            continue
        problem_statement, reference_test_cases = build_problem_statement(ori_repo_path, swe_instance, mode)
        problem_statement_path = os.path.join(save_problem_statement_dir, f"{swe_instance['repo_name']}.md")
        with open(problem_statement_path, "w") as f:
            f.write(problem_statement)
        reference_test_cases_path = os.path.join(save_problem_statement_dir, f"{swe_instance['repo_name']}_test_cases.md")
        with open(reference_test_cases_path, "w") as f:
            f.write(reference_test_cases)
            
        repo_path = build_task_repo(args, ori_repos_dir, save_repo_dir, swe_instance, mode=mode)
        if repo_path is None:
            continue
        task_data = {
            "instance_id": swe_instance['repo_name'],
            "problem_statement": {"type": "text", "text": problem_statement, "id": swe_instance['repo_name']},
            "env": {
                "deployment": {
                    "type": "docker",
                    "image": f"lpbench.eval.{swe_instance['repo_name'].replace(":", "_").lower()}:latest",
                    "docker_args": [
                        "--mount", f"type=bind,source=./baselines/SWE-agent/.venv/lib/python3.12/site-packages/swerex,target=/root/.local/share/pipx/venvs/swe-rex/lib/python3.12/site-packages/swerex,readonly",
                        "--mount", f"type=bind,source={problem_statement_path},target=/project_requirements.md,readonly",
                    ],
                },
                "repo": {
                    "path": repo_path,
                },
                "post_startup_commands": [
                    f"export PYTEST_EXEC_COMMAND='{pytest_cmd}'",
                    "export http_proxy=http://172.17.0.1:10809",
                    "export https_proxy=http://172.17.0.1:10809",
                    "export all_proxy=http://172.17.0.1:10809",
                ]
            },
        }
        
        if args.agent_config in ["eval_test", "eval_judge"]:
            task_data["env"]["deployment"]["docker_args"].append(f"--mount")
            task_data["env"]["deployment"]["docker_args"].append(f"type=bind,source={ori_repo_path},target=/reference_repo,readonly")
            task_data["env"]["deployment"]["docker_args"].append(f"--mount")
            task_data["env"]["deployment"]["docker_args"].append(f"type=bind,source={reference_test_cases_path},target=/reference_test_cases.md,readonly")
            cmds = source_results[swe_instance['repo_name']]["commands"] if source_results is not None else []
            for cmd in cmds:
                if cmd and check_env_cmd(cmd):
                    task_data["env"]["post_startup_commands"].append(cmd)
                
            if args.agent_config == "eval_test":
                task_data["env"]["post_startup_commands"].append("export AGENT_MODE='eval_test'")
            else:
                task_data["env"]["post_startup_commands"].append("export AGENT_MODE='eval_judge'")
        else:
            task_data["env"]["post_startup_commands"].append("export AGENT_MODE='default'")
        
        swe_agent_datasets.append(task_data)

    save_file(os.path.join(runs_dir, "swe_agent_datasets.jsonl"), swe_agent_datasets)
    return swe_agent_datasets

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run PR Agent with multithreading")
    parser.add_argument("--num-threads", type=int, default=4, help="Maximum number of worker threads")
    parser.add_argument("--dataset-file", type=str, default="./data/datasets/pypi-2024-01-dataset-final.json",
                        help="Path to the dataset file")
    parser.add_argument("--instance-ids", type=str, default=None,
                        help="Instance IDs")
    parser.add_argument("--repos-dir", type=str, default="./data/repos",
                        help="Path to the repos directory")
    parser.add_argument("--output-dir", type=str, default="data/pr_agent_results",
                        help="Path to the output directory")
    parser.add_argument("--model", type=str, default="gpt-4o-mini",
                        help="Model name")
    parser.add_argument("--base-url", type=str, default=None,
                        help="Base URL")
    parser.add_argument("--api-key", type=str, default="sk-proj-1234567890",
                        help="API key")
    parser.add_argument("--clean", action="store_true", default=False,
                        help="Clean the output directory")
    parser.add_argument("--agent-config", type=str, default="default",
                        help="Agent config file")
    parser.add_argument("--eval-step", type=int, default=-1, help="target evaluation step")
    args = parser.parse_args()
    
    if args.agent_config == "eval_test":
        assert args.eval_step >= 0
        runs_dir = os.path.join(args.output_dir, f"runs_eval_test_{args.eval_step}")
        source_results = load_file(os.path.join(args.output_dir, "runs", "generation.jsonl"))
        source_results = {p['repo_name']: p for p in source_results}
    elif args.agent_config == "eval_judge":
        assert args.eval_step >= 0
        runs_dir = os.path.join(args.output_dir, f"runs_eval_judge_{args.eval_step}")
        source_results = load_file(os.path.join(runs_dir.replace("runs_eval_judge", "runs_eval_test"), "generation.jsonl"))
        source_results = {p['repo_name']: p for p in source_results}
    else:
        runs_dir = os.path.join(args.output_dir, "runs")
        source_results = None

    if args.clean:
        shutil.rmtree(runs_dir, ignore_errors=True)
    os.makedirs(runs_dir, exist_ok=True)
    
    tasks = create_tasks(args, source_results)
    
    if args.model in ["deepseek/deepseek-chat"]:
        MODEL_KEY = f"DEEPSEEK_API_KEY={args.api_key}"
    elif args.model in [
        "gemini/gemini-2.5-flash-preview-04-17", 
        "gemini/gemini-2.5-pro-preview-03-25", 
        "gemini/gemini-2.5-pro-preview-05-06",
        "gemini/gemini-2.5-pro-preview-06-05", 
        "gemini/gemini-2.5-pro", 
        "gemini/gemini-2.5-flash",
        "gemini/gemini-2.5-flash-lite"
    ]:
        MODEL_KEY = f"GEMINI_API_KEY={args.api_key}"
    else:
        MODEL_KEY = f"OPENAI_API_KEY={args.api_key} OPENAI_API_BASE_URL={args.base_url}"
    args.api_key = args.api_key.split(",")
    random.shuffle(args.api_key)
    args.api_key = ":::".join(args.api_key)
    
    choose_api_key_by_thread = "false"
    agent_config = None
    default_model_settings = f"""--agent.model.name={args.model} \
        --agent.model.api_key={args.api_key} \
        --agent.model.choose_api_key_by_thread={choose_api_key_by_thread} \
        --agent.model.temperature=0.2 \
        --agent.model.completion_kwargs='{{"thinkingConfig":{{"thinkingBudget":-1}}}}' \
        --agent.model.per_instance_cost_limit=100.0 \
        --agent.model.per_instance_call_limit=200 \
        --agent.model.max_input_tokens=512000"""
    
    if args.agent_config == "default":
        agent_config = f"""--config {os.path.join(SWE_AGENT_PATH, "config/coding_project_test.yaml")} \
            {default_model_settings}"""
    elif args.agent_config == "default_adv":
        agent_config = f"""--config {os.path.join(SWE_AGENT_PATH, "config/coding_project_test_defaultadv.yaml")} \
            {default_model_settings}"""
    elif args.agent_config == "from_scratch":
        agent_config = f"""--config {os.path.join(SWE_AGENT_PATH, "config/coding_project_fromscratch.yaml")} \
            {default_model_settings}"""
    elif args.agent_config == "eval_test":
        agent_config = f"""--config {os.path.join(SWE_AGENT_PATH, "config/coding_project_eval_test.yaml")} \
            {default_model_settings}"""
        agent_config = agent_config.replace("--agent.model.per_instance_call_limit=200", "--agent.model.per_instance_call_limit=100")
    elif args.agent_config == "eval_judge":
        agent_config = f"""--config {os.path.join(SWE_AGENT_PATH, "config/coding_project_eval_judge.yaml")} \
            {default_model_settings}"""
    elif args.agent_config == "dev_test":
        agent_config = f"""--config {os.path.join(SWE_AGENT_PATH, "config/coding_project_dev_test.yaml")} \
            --agent.dev.model.name={args.model} \
            --agent.dev.model.api_key={args.api_key} \
            --agent.dev.model.choose_api_key_by_thread={choose_api_key_by_thread} \
            --agent.dev.model.temperature=0.2 \
            --agent.dev.model.per_instance_cost_limit=100.0 \
            --agent.dev.model.per_instance_call_limit=200 \
            --agent.dev.model.max_input_tokens=512000 \
            --agent.test.model.name={args.model} \
            --agent.test.model.api_key={args.api_key} \
            --agent.test.model.choose_api_key_by_thread={choose_api_key_by_thread} \
            --agent.test.model.temperature=0.2 \
            --agent.test.model.per_instance_cost_limit=100.0 \
            --agent.test.model.per_instance_call_limit=200 \
            --agent.test.model.max_input_tokens=512000"""
    elif args.agent_config == "design_dev_test":
        agent_config = f"""--config {os.path.join(SWE_AGENT_PATH, "config/coding_project_design_dev_test.yaml")} \
            --agent.design.model.name={args.model} \
            --agent.design.model.api_key={args.api_key} \
            --agent.design.model.choose_api_key_by_thread={choose_api_key_by_thread} \
            --agent.design.model.temperature=0.2 \
            --agent.design.model.per_instance_cost_limit=100.0 \
            --agent.design.model.per_instance_call_limit=200 \
            --agent.design.model.max_input_tokens=512000 \
            --agent.dev.model.name={args.model} \
            --agent.dev.model.api_key={args.api_key} \
            --agent.dev.model.choose_api_key_by_thread={choose_api_key_by_thread} \
            --agent.dev.model.temperature=0.2 \
            --agent.dev.model.per_instance_cost_limit=100.0 \
            --agent.dev.model.per_instance_call_limit=200 \
            --agent.dev.model.max_input_tokens=512000 \
            --agent.test.model.name={args.model} \
            --agent.test.model.api_key={args.api_key} \
            --agent.test.model.choose_api_key_by_thread={choose_api_key_by_thread} \
            --agent.test.model.temperature=0.2 \
            --agent.test.model.per_instance_cost_limit=100.0 \
            --agent.test.model.per_instance_call_limit=200 \
            --agent.test.model.max_input_tokens=512000"""
    elif args.agent_config == "trae_agent":
        agent_config = f"""--config {os.path.join(SWE_AGENT_PATH, "config/coding_project_trae_adv.yaml")} \
            {default_model_settings}"""
    else:
        raise ValueError(f"Invalid agent config: {args.agent_config}")
    
    cmd = f"""{MODEL_KEY} LITELLM_LOCAL_MODEL_COST_MAP=True \
        sweagent run-batch \
            {agent_config} \
            --instances.type expert_file \
            --instances.path {os.path.join(runs_dir, "swe_agent_datasets.jsonl")} \
            --instances.shuffle=False \
            --output_dir {runs_dir} \
            --num_workers {args.num_threads}
                
    """
    # if args.base_url is not None:
    #     cmd += f" --agent.model.api_base={args.base_url} "
    
    
    # Use the original command for Unix-like systems
    full_cmd = f"source {VENV_PATH}/bin/activate && {cmd}"
    process = None
    try:
        print(full_cmd)
        # exit()
        # Use preexec_fn to create a new process group
        process = subprocess.Popen(full_cmd, shell=True, executable="/bin/bash", 
                                  preexec_fn=os.setsid)
        process.wait()
        print(f"Completed review for {args.dataset_file}")
    except Exception as e:
        print(f"Error processing {args.dataset_file}: {str(e)}")
    finally:
        # Kill the entire process group, not just the shell
        if process and process.poll() is None:
            try:
                print("Terminating subprocess and all child processes...")
                # Send signal to the entire process group
                os.killpg(os.getpgid(process.pid), 15)  # SIGTERM to process group
                process.wait(timeout=5)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                try:
                    os.killpg(os.getpgid(process.pid), 9)  # SIGKILL to process group
                except ProcessLookupError:
                    pass
                
        # Also find and kill any remaining 'sweagent run-batch' processes
        try:
            # Find all sweagent processes for this specific run
            pkill_cmd = f"pkill -f 'sweagent run-batch.*--output_dir {runs_dir}'"
            subprocess.run(
                pkill_cmd,
                shell=True, 
                executable="/bin/bash"
            )
        except Exception:
            pass

    # Collect results
    results = []
    for task in tasks:
        model_patch = {}
        
        model_patch = extract_patch_from_traj(os.path.join(runs_dir, task['instance_id'], f"{task['instance_id']}.traj"))
        cmds = extract_commands_from_traj(os.path.join(runs_dir, task['instance_id'], f"{task['instance_id']}.traj"))
        source_cmds = source_results[task['instance_id']]["commands"] if source_results is not None else []
        repo_source_path = os.path.join(runs_dir.replace("runs", "repos"), task['instance_id'])
        assert os.path.exists(repo_source_path), f"Repo source path {repo_source_path} does not exist"
        
        task_result = {
            "repo_name": task['instance_id'],
            "repo_source_path": repo_source_path,
            "repo_path": None,
            "commands": cmds + source_cmds,
            "model_patch": model_patch
        }

        if args.agent_config == "eval_judge":
            max_patch_idx = max(task_result["model_patch"].keys())
            task_result["evaluation_report"] = task_result["model_patch"][max_patch_idx]

        results.append(task_result)

    results_path = os.path.join(runs_dir, "generation.jsonl")
    print_message = f"All tasks completed. Results saved to {results_path}"
    with open(results_path, "w") as f:
        for result in results:
            f.write(json.dumps(result) + "\n")
    
    print(print_message)

