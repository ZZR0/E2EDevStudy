import json
import os
import subprocess
import time
from loguru import logger
import shutil


def load_file(file_path):
    if file_path.endswith(".jsonl"):
        with open(file_path, "r") as f:
            return [json.loads(line) for line in f]
    elif file_path.endswith(".json"):
        with open(file_path, "r") as f:
            return json.load(f)
    else:
        file_ext = file_path.split(".")[-1]
        if not file_ext in ["md", "txt", "patch", "py", "sh"]:
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
        file_ext = file_path.split(".")[-1]
        if not file_ext in ["md", "txt", "patch", "py", "sh"]:
            logger.warning(f"Unknown file type save as text: {file_path}")
        with open(file_path, "w") as f:
            f.write(data)


def clone_repo(repo_url, repo_dir, retries=5, timeout=600):
    if os.path.exists(repo_dir):
        if use_cache:
            logger.info(f"Repo {repo_dir} already exists. Skipping clone.")
            return True
        else:
            # 删除已存在的目录
            shutil.rmtree(repo_dir)
            logger.info(f"Repo {repo_dir} already exists. Deleting and re-cloning.")

    for attempt in range(retries):
        try:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", repo_url, repo_dir],
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                timeout=timeout,
            )
            if result.returncode == 0:
                logger.info(f"Repo {repo_dir} cloned successfully.")
                return True
            logger.info(f"Cloning {repo_dir} attempt {attempt+1} failed. Retrying...")
            time.sleep(5 * (attempt + 1))  # 指数退避
        except Exception as e:
            print(f"Error: {str(e)}")

    print(f"Failed to clone after {retries} attempts")
    return False


class EvalReport:
    def __init__(self, repo_name):
        self.repo_name = repo_name
        self.test_case_result = {}  # {test_id: result}
        self.coverage_result = {}  # {test_id: {file_name: line}}
        self.success_count = 0
        self.failed_count = 0
        self.error_count = 0
        self.skipped_count = 0
        self.unknown_count = 0
        self.total_count = 0
        self.success_rate = 0.0
        self.finish_test = False
        self.coverage_report = {}
        self.detail = {}
        self.test_output = ''
        self.collection_log = ''

    def add_test_result(self, test_id, result):
        self.test_case_result[test_id] = result

    def set_detail(self, detail):
        self.detail = detail

    def add_coverage_result(self, file_name, file_cov):
        def add_test(_test, _file_name, key, value):
            if _test not in self.coverage_result:
                self.coverage_result[_test] = {}
            if _file_name not in self.coverage_result[_test]:
                self.coverage_result[_test][_file_name] = {
                    "lines": [],
                    "functions": [],
                    "classes": [],
                }
            self.coverage_result[_test][_file_name][key].append(value)

        for line, contexts in file_cov["contexts"].items():
            for test in contexts:
                if test == "":
                    continue
                add_test(test, file_name, "lines", line)

        if "functions" in file_cov:
            for func, func_cov in file_cov["functions"].items():
                if func == "":
                    continue
                for eline in func_cov["executed_lines"]:
                    eline = str(eline)
                    if eline not in func_cov["contexts"]:
                        continue
                    for test in func_cov["contexts"][eline]:
                        if test == "":
                            continue
                        add_test(test, file_name, "functions", func)

        if "classes" in file_cov:
            for cls_name, cls_cov in file_cov["classes"].items():
                if cls_name == "":
                    continue
                for eline in cls_cov["executed_lines"]:
                    eline = str(eline)
                    if eline not in cls_cov["contexts"]:
                        continue
                    for test in cls_cov["contexts"][eline]:
                        if test == "":
                            continue
                        add_test(test, file_name, "classes", cls_name)

    def add_coverage_report(self, coverage_report):
        self.coverage_report = coverage_report

    def finalize(self):
        self.success_count = sum(
            1 for r in self.test_case_result.values() if r == "passed"
        )
        self.failed_count = sum(
            1 for r in self.test_case_result.values() if r == "failed"
        ) + sum(1 for r in self.test_case_result.values() if r == "xfailed")
        self.error_count = sum(
            1 for r in self.test_case_result.values() if r == "error"
        )
        self.skipped_count = sum(
            1 for r in self.test_case_result.values() if r == "skipped"
        )
        self.unknown_count = sum(
            1 for r in self.test_case_result.values() if r == "unknown"
        )
        self.total_count = len(self.test_case_result)
        self.success_rate = (
            self.success_count / self.total_count if self.total_count else 0.0
        )
        self.finish_test = True

        for test in self.coverage_result:
            for file_name in self.coverage_result[test]:
                for key in self.coverage_result[test][file_name]:
                    self.coverage_result[test][file_name][key] = list(
                        set(self.coverage_result[test][file_name][key])
                    )

    def to_dict(self):
        return {
            "repo_name": self.repo_name,
            "finish_test": self.finish_test,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "error_count": self.error_count,
            "skipped_count": self.skipped_count,
            "unknown_count": self.unknown_count,
            "total_count": self.total_count,
            "success_rate": self.success_rate,
            "test_case_result": self.test_case_result,
            "coverage_report": self.coverage_report,
            "coverage_result": self.coverage_result,
            "detail": self.detail,
            "test_output": self.test_output,
            "collection_log": self.collection_log,
        }

    def set_error(self, error_type, error_message):
        """
        记录评估过程中的错误
        :param error_type: 错误类型
        :param error_message: 错误信息
        """
        self.error_type = error_type
        self.error_message = error_message
        self.finish_test = False
