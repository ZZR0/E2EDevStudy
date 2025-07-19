# 建立数据集
import os
import concurrent.futures
import json
import argparse
import threading  # 添加argparse模块用于处理命令行参数
from tqdm import tqdm
from loguru import logger
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError

log_file_path = "build_dataset.log"
if os.path.exists(log_file_path):
    os.remove(log_file_path)  # 删除旧的日志文件
logger.add(
    log_file_path,
    rotation="100 MB",
    level="INFO",
    format="{time} {level} [{function}:{line}] {message}",
    enqueue=True,
)

# 任务超时时间（秒）
TASK_TIMEOUT = 1000

# from get_top_github_repo import get_top_repo
from get_top_PyPI_package import get_top_PyPI_package
from judge_good_repo import get_judge_info, run_judge_project
from generate_eval_input import (
    generate_requirement_files,
    generate_full_code_skeleton,
    generate_minimal_code_skeleton,
    generate_minimal_test_cases,
    parse_code_skeleton,
)
from utils.utils import (
    clone_repo,
    TokenManager,
    save_json,
    save_to_file,
    load_from_file
)
from utils.repo_info import (
    count_python_files,
    count_python_code_lines,
    find_test_file,
    get_commit_sha,
    get_test_files_content,
    get_structured_tests,
    get_pyfile_content,
    get_repo_structure,
)

from utils.config import (
    LANGUAGE,
    STARS_NUM,
    SEARCH_REPO_NUM,  # 从api获取仓库列表的个数
    FILTER_REPO_NUM,  # 筛选仓库的个数
    DATASET_REPO_NUM,  # 用于建立数据集的仓库的个数
    REPO_SIZE_LIMIT,
    USE_EXISTING_REPO_LIST,
    USE_EXISITING_GOOD_REPO_LIST,
    USE_PROXY,
    PROXY_URL,
    ONLY_JUDGE,
    PRE_DOWNLOAD,
    SAVE_REPO_LIST_TO_FILE,
    SAVE_GOOD_REPO_LIST_TO_FILE,
    SAVE_DATASET_TO_FILE,
    GITHUB_TOKENS,
)
from utils.llm import LLM

if USE_PROXY:
    os.environ["all_proxy"] = PROXY_URL

# 路径参数（默认值）
REPOS_DIR = "../../repos"
OUTPUT_DIR = "./data/output"

def str_to_bool(value):
    """Converts a string representation of truth to True or False."""
    if isinstance(value, bool):
       return value
    if value.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif value.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')
token_manager = TokenManager(GITHUB_TOKENS)

def load_jsonl(file_path):
    data = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            data.append(json.loads(line))
    return data

# 预下载仓库函数
def pre_download_repos(
    repo_list, repos_dir, filter_repo_num, token_manager, task_timeout, workers=16
):
    """
    使用多线程预下载仓库列表中的仓库。
    """
    logger.info("pre-downloading all repos")

    def download_repo(repo):
        try:
            path_to_repo = os.path.join(repos_dir, repo["repo_name"])
            if (
                clone_repo(
                    repo_url=repo["url"],
                    repo_dir=path_to_repo,
                    github_token=token_manager.get_token(),
                )
                == True
            ):
                return repo["repo_name"], True
            else:
                return repo["repo_name"], False
        except Exception as e:
            logger.error(f"Error when downloading {repo['repo_name']}: {str(e)}")
            return repo["repo_name"], False

    # 使用线程池并行下载
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(download_repo, repo): repo["repo_name"]
            for repo in repo_list[:filter_repo_num]
        }

        # 使用tqdm显示进度
        for future in tqdm(
            as_completed(futures), total=len(futures), desc="Cloning Repos", unit="repo"
        ):
            repo_name = futures[future]
            try:
                name, success = future.result(timeout=task_timeout)
                if not success:
                    logger.error(f"Error cloning {name}.")
            except TimeoutError:
                logger.error(f"Timeout when cloning {repo_name}.")
            except Exception as e:
                logger.error(f"Exception occurred when cloning {repo_name}: {str(e)}")


# 筛选满足条件的仓库
def filter_repo(good_repo_list_name, repo_list, language, repos_dir, token_manager, workers=32):
    os.makedirs(repos_dir, exist_ok=True)
    good_repo_list_name_jsonl = good_repo_list_name + ".jsonl"
    if os.path.exists(good_repo_list_name_jsonl):
        logger.info(f"Loading existing {good_repo_list_name_jsonl} file.")
        processed_repo_list = load_jsonl(good_repo_list_name_jsonl)
        processed_repo_ids = [repo["idx"] for repo in processed_repo_list]
        repo_list = [repo for repo in repo_list if repo["idx"] not in processed_repo_ids]
    else:
        logger.info(f"No existing {good_repo_list_name_jsonl} file, creating new file.")
        
    file_lock = threading.Lock()
    def process_repo(repo):
        try:
            path_to_repo = os.path.join(repos_dir, repo["repo_name"])
            if (
                clone_repo(
                    repo["url"], path_to_repo, github_token=token_manager.get_token()
                )
                == True
            ):
                pass
            else:
                logger.error(f"Error cloning {repo['repo_name']}.")
            # print(f"Repo {repo['repo_name']} cloned successfully.")

            judge_info = get_judge_info(path_to_repo, language=language)
            
        except Exception as e:
            logger.error(f"Error processing {repo['repo_name']}: {str(e)}")
            is_good_project = False
            judge_info = {"is_good_project": is_good_project, "language": language, "reason": "Error processing repo"}
        
        repo["judge_info"] = judge_info
        with file_lock:
            with open(good_repo_list_name_jsonl, "a", encoding="utf-8") as f:
                f.write(json.dumps(repo) + "\n")

    # # 使用线程池并行处理
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=workers
    ) as executor:  # 调整max_workers数量
        # 提交所有任务
        futures = [
            executor.submit(process_repo, repo) for repo in repo_list[:FILTER_REPO_NUM]
        ]
        # 使用tqdm显示进度
        for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures), desc="Cloning and Evaluating Repos", unit="repo"):
            try:
                future.result(timeout=TASK_TIMEOUT)
            except TimeoutError:
                logger.error("Timeout when processing a repo in filter_repo.")
                continue
    
    # for repo in repo_list[:FILTER_REPO_NUM]:
    #     process_repo(repo)

    repo_list_result = load_jsonl(good_repo_list_name_jsonl)
    good_repo_list = []
    reason_dict = {}
    for repo in repo_list_result:
        good_project, reason = run_judge_project(repo, language)
        reason_dict[reason] = reason_dict.get(reason, 0) + 1
        if good_project:
            good_repo_list.append(repo)
    
    logger.info(f"Reason dict: {reason_dict}")
    
    # 按照rating数量排序
    good_repo_list.sort(key=lambda x: (x["judge_info"]["llm_rating"], x["stars"]), reverse=True)
    logger.info("saving good repo list...")
    with open(good_repo_list_name, "w", encoding="utf-8") as f:
        json.dump(good_repo_list, f, ensure_ascii=False, indent=4)
        logger.info("good repo list saved successfully.")
    return good_repo_list


# 生成数据集
def generate_dataset(
    good_repo_list,
    repos_dir,
    output_dir,
    workers=32,
):
    def process_repo(repo):
        try:
            repo_new = repo.copy()
            path_to_repo = os.path.join(repos_dir, repo["repo_name"])
            # 获取依赖包
            # package_name = repo["pypi_info"]["name"]
            # dependencies = get_dependencies(package_name)
            # repo_new["dependencies"] = dependencies
            # 计算代码行数和文件数
            repo_new["commit_sha"] = get_commit_sha(path_to_repo)
            repo_new["codelines_count"] = count_python_code_lines(path_to_repo)
            repo_new["codefiles_count"] = count_python_files(path_to_repo)

            # 计算代码总长度
            all_code = get_pyfile_content(path_to_repo)
            repo_new["code_length"] = len(all_code)

            # 计算测试文件数
            test_files_count = len(find_test_file(path_to_repo, language="python"))
            repo_new["test_files_count"] = test_files_count

            # 计算测试文件总长度
            test_files_content = get_test_files_content(path_to_repo)
            repo_new["test_code_length"] = len(test_files_content)

            # 生成类图
            language = repo["language"].lower()

            # 生成代码结构
            structure_dict = get_repo_structure(path_to_repo, language)
            if structure_dict is None:
                logger.warning(
                    f"Code structure for repo {repo['repo_name']} failed to generate."
                )
                return None
            repo_new["structure"] = structure_dict
            structure_path = os.path.join(
                output_dir, "code_structures", f"{repo['repo_name']}.json"
            )
            save_json(structure_dict, structure_path)
            logger.success(
                f"Code structure for repo {repo['repo_name']} generated successfully."
            )

            # 提取出文档的每个测试点
            test_cases = {t: {"testid": t, "result": test_res, "test_implementation": None} for t, test_res in repo['tests']['test_case_result'].items()}
            test_case_list = get_structured_tests(path_to_repo)
            test_case_dict = {f'{t["test_file_path"]}::{t["test_method"]}': t["test_implementation"] for t in test_case_list}
            for t in test_cases:
                testid = t.split("[")[0]
                testid = f'{testid.split("::")[0]}::{testid.split("::")[-1]}'
                if testid in test_case_dict:
                    test_cases[t]["test_implementation"] = test_case_dict[testid]
            
            # test_cases = [t for t in test_cases.values() if t["test_implementation"] is not None]
            repo_new["test_cases"] = test_cases

            # # 生成SRS文档
            # ori_SRS_document, SRS_document, structured_requirements = generate_requirement_files(path_to_repo, test_cases, language)
            # if ori_SRS_document is None or SRS_document is None or structured_requirements is None:
            #     logger.warning(
            #         f"SRS document and structured requirements for repo {repo['repo_name']} failed to generate."
            #     )
            #     return None  # SRS生成失败则不加入最终数据集

            # repo_new["structured_requirements"] = structured_requirements
            # logger.success(
            #     f"SRS document and structured requirements for repo {repo['repo_name']} generated successfully."
            # )
            save_path = os.path.join(output_dir, "SRS_documents", f"{repo['repo_name']}.md")
            # save_to_file(SRS_document, save_path)
            SRS_document = load_from_file(save_path)
            repo_new["SRS_document"] = SRS_document
            # save_to_file(ori_SRS_document, os.path.join(output_dir, "SRS_documents", f"{repo['repo_name']}_ORI.md"))
            
            # combined_data = {
            #     "requirements": structured_requirements,
            #     "test_cases": test_cases,
            # }
            # save_json(combined_data, os.path.join(output_dir, "structured_requirements", f"{repo['repo_name']}.json"))
            # import pdb; pdb.set_trace()
            
            # # 生成完整代码设计
            # full_code_skeleton = generate_full_code_skeleton(path_to_repo)
            # if full_code_skeleton is None:
            #     logger.warning(f"Full code skeleton for repo {repo['repo_name']} failed to generate.")
            #     return None
            save_path = os.path.join(output_dir, "full_code_skeleton", f"{repo['repo_name']}.md")
            # save_to_file(full_code_skeleton, save_path)
            full_code_skeleton = load_from_file(save_path)
            repo_new["full_code_skeleton"] = full_code_skeleton
            repo_new["full_code_skeleton_structured"] = parse_code_skeleton(full_code_skeleton)
            if repo_new["full_code_skeleton_structured"] is None:
                logger.error(f"Full code skeleton for repo {repo['repo_name']} failed to parse.")
            
            # # 生成最小代码设计
            # minimal_code_skeleton = generate_minimal_code_skeleton(path_to_repo)
            # if minimal_code_skeleton is None:
            #     logger.warning(f"Minimal code skeleton for repo {repo['repo_name']} failed to generate.")
            #     return None
            save_path = os.path.join(output_dir, "minimal_code_skeleton", f"{repo['repo_name']}.md")
            # save_to_file(minimal_code_skeleton, save_path)
            minimal_code_skeleton = load_from_file(save_path)
            repo_new["minimal_code_skeleton"] = minimal_code_skeleton
            repo_new["minimal_code_skeleton_structured"] = parse_code_skeleton(minimal_code_skeleton)
            if repo_new["minimal_code_skeleton_structured"] is None:
                logger.error(f"Minimal code skeleton for repo {repo['repo_name']} failed to parse.")
            
            # # 生成最小测试用例
            # test_cases = [t["testid"] for t in repo_new["test_cases"].values()]
            # minimal_test_cases = generate_minimal_test_cases(path_to_repo, test_cases)
            # if minimal_test_cases is None:
            #     logger.warning(f"Minimal test cases for repo {repo['repo_name']} failed to generate.")
            #     return None
            save_path = os.path.join(output_dir, "minimal_test_cases", f"{repo['repo_name']}.json")
            # save_json(minimal_test_cases, save_path)
            minimal_test_cases = load_from_file(save_path)
            repo_new["minimal_test_cases"] = minimal_test_cases

            return repo_new
        except Exception as e:
            logger.error(f"Error processing repo {repo['repo_name']}: {str(e)}")
            return None

    os.makedirs(os.path.join(output_dir, "code_structures"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "SRS_documents"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "structured_requirements"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "full_code_skeleton"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "minimal_code_skeleton"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "minimal_test_cases"), exist_ok=True)
    dataset = []
    # 使用线程池并发处理仓库
    with ThreadPoolExecutor(max_workers=workers) as executor:  # 根据实际情况调整max_workers
        futures = {executor.submit(process_repo, repo) for repo in good_repo_list}

        # 使用tqdm显示进度条
        for future in tqdm(as_completed(futures), total=len(futures), desc="Processing Repos", unit="repo"):
            try:
                result = future.result(timeout=TASK_TIMEOUT)
            except TimeoutError:
                logger.error("Timeout when processing a repo in generate_dataset.")
                continue
            if result is not None:
                dataset.append(result)
    
    # for repo in good_repo_list:
    #     try:
    #         result = process_repo(repo)
    #     except TimeoutError:
    #         logger.error("Timeout when processing a repo in generate_dataset.")
    #         continue
    #     if result is not None:
    #         dataset.append(result)

    return dataset


def main():
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="构建数据集工具")
    parser.add_argument(
        "--repos-dir",
        type=str,
        default=REPOS_DIR,
        help="仓库目录路径，默认值: " + REPOS_DIR,
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=OUTPUT_DIR,
        help="输出目录路径，默认值: " + OUTPUT_DIR,
    )
    parser.add_argument(
        "--use-existing-good-repo-list",
        type=str_to_bool,
        default=USE_EXISITING_GOOD_REPO_LIST,
        help="是否使用已有的good repo list，默认值: " + str(USE_EXISITING_GOOD_REPO_LIST),
    )
    parser.add_argument(
        "--use-existing-repo-list",
        type=str_to_bool,
        default=USE_EXISTING_REPO_LIST,
        help="是否使用已有的repo list，默认值: " + str(USE_EXISTING_REPO_LIST),
    )
    parser.add_argument(
        "--pre-download",
        type=str_to_bool,
        default=PRE_DOWNLOAD,
        help="是否预先下载仓库，默认值: " + str(PRE_DOWNLOAD),
    )
    parser.add_argument(
        "--only-judge",
        type=str_to_bool,
        default=ONLY_JUDGE,
        help="是否只进行筛选，不生成数据集，默认值: " + str(ONLY_JUDGE),
    )
    parser.add_argument(
        "--repo-list-name",
        type=str,
        default="python_repo_list.json",
        help="repo list文件名，默认值: " + "python_repo_list.json",
    )
    parser.add_argument(
        "--good-repo-list-name",
        type=str,
        default="good_python_repo_list.json",
        help="good repo list文件名，默认值: " + "good_python_repo_list.json",
    )
    parser.add_argument(
        "--dataset-name",
        type=str,
        default="python_dataset.json",
        help="dataset文件名，默认值: " + "python_dataset.json",
    )
    parser.add_argument(
        "--repos-name",
        type=str,
        default=None,
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=32,
        help="线程池的工作线程数量，默认值: 32",
    )

    args = parser.parse_args()

    repo_list_name = args.repo_list_name
    good_repo_list_name = args.good_repo_list_name
    dataset_name = args.dataset_name

    # 使用命令行参数覆盖默认路径
    repos_dir = args.repos_dir
    output_dir = args.output_dir
    
    # 日志中显示使用的路径
    logger.info(f"使用仓库目录: {repos_dir}")
    logger.info(f"使用输出目录: {output_dir}")

    if not args.use_existing_good_repo_list:
        if not args.use_existing_repo_list:
            logger.info("searching top repo")
            # 获取仓库列表
            repo_list = get_top_PyPI_package(
                repo_num=SEARCH_REPO_NUM,
                repo_size=REPO_SIZE_LIMIT,
            )
            if SAVE_REPO_LIST_TO_FILE:
                with open(repo_list_name, "w", encoding="utf-8") as f:
                    json.dump(repo_list, f, ensure_ascii=False, indent=4)
        else:
            logger.info("using existing repo list")

        ## 筛选满足条件的仓库
        try:
            with open(repo_list_name, "r", encoding="utf-8") as f:
                repo_list = json.load(f)
            # 去重
            seen_repo_names = set()
            unique_repo_list = []
            original_count = len(repo_list)
            for repo in repo_list:
                repo_name = repo.get("repo_name")
                if repo_name and repo_name not in seen_repo_names:
                    seen_repo_names.add(repo_name)
                    unique_repo_list.append(repo)
            repo_list = unique_repo_list
            logger.info(
                f"Removed duplicates based on repo_name. Original count: {original_count}, Unique count: {len(repo_list)}"
            )
        except FileNotFoundError:  # 更具体的异常处理
            logger.error(f"Error: No such file or directory: '{repo_list_name}'")
            return  # 文件不存在则退出
        except json.JSONDecodeError:  # 处理JSON解析错误
            logger.error(f"Error: Could not decode JSON from '{repo_list_name}'")
            return
        except Exception as e:  # 其他可能的异常
            logger.error(
                f"An unexpected error occurred while reading '{repo_list_name}': {e}"
            )
            return

        if args.pre_download:
            # 调用预下载函数
            pre_download_repos(
                repo_list,
                repos_dir,
                FILTER_REPO_NUM,
                token_manager,
                TASK_TIMEOUT,
                workers=16,
            )

        good_repo_list = filter_repo(
            good_repo_list_name,
            repo_list[:FILTER_REPO_NUM],
            language=LANGUAGE,
            repos_dir=repos_dir,
            token_manager=token_manager,
            workers=args.workers,
        )

    else:
        logger.info("using existing good repo list")
        # 如果使用现有的 good repo list，确保 good_repo_list 变量被正确加载
        try:
            with open(good_repo_list_name, "r", encoding="utf-8") as f:
                good_repo_list = json.load(f)
        except FileNotFoundError:
            logger.error(
                f"Error: No such file or directory: '{good_repo_list_name}' when USE_EXISITING_GOOD_REPO_LIST is True."
            )
            return
        except json.JSONDecodeError:
            logger.error(f"Error: Could not decode JSON from '{good_repo_list_name}'")
            return
        except Exception as e:
            logger.error(
                f"An unexpected error occurred while reading '{good_repo_list_name}': {e}"
            )
            return

    # 只生成good_repo_list，不生成数据集
    if args.only_judge:
        # 确保 good_repo_list 在此作用域内可用
        if "good_repo_list" not in locals():
            logger.error(
                "good_repo_list is not defined. Cannot proceed with ONLY_JUDGE."
            )
            return
        logger.success(
            f"Good repo list generated successfully. Total number: {len(good_repo_list)}"
        )
        return
    # 从good_repo_list_name中读取数据，生成类图和SRS文档
    # 确保 good_repo_list 在此作用域内可用
    if "good_repo_list" not in locals():
        logger.error(
            "good_repo_list is not defined. Cannot proceed to generate dataset."
        )
        return

    if args.repos_name is not None:
        args.repos_name = args.repos_name.split(",")
        good_repo_list = [repo for repo in good_repo_list if repo["repo_name"] in args.repos_name]
    else:
        good_repo_list = good_repo_list[:DATASET_REPO_NUM]
        
    dataset = generate_dataset(
        good_repo_list,
        repos_dir,
        output_dir,
        workers=args.workers,
    )
    # 按照stars数量排序
    dataset.sort(key=lambda x: x["stars"], reverse=True)

    # 保存数据集
    if SAVE_DATASET_TO_FILE:
        with open(dataset_name, "w", encoding="utf-8") as f:
            json.dump(dataset, f, ensure_ascii=False, indent=4)

    # 输出llm的token总用量
    llm = LLM()
    total_tokens = llm.total_tokens
    prompt_tokens = llm.prompt_tokens
    completion_tokens = llm.completion_tokens
    logger.success(f"Total tokens used by LLM: {total_tokens}")
    logger.success(f"Prompt tokens used by LLM: {prompt_tokens}")
    logger.success(f"Completion tokens used by LLM: {completion_tokens}")


if __name__ == "__main__":
    main()
