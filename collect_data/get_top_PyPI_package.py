import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.exceptions import RequestException
from loguru import logger

os.environ["LIBRARIES_API_KEY"] = "e9c73df2b65533a3c13fc4fc5bab729a"

from pybraries.search import Search
from tqdm import tqdm
from github import Github
from github import Auth
from urllib.parse import urlparse


def package_to_dict(pkg):
    return {
        "repo_name": pkg["name"].replace("/", "_"),
        "url": pkg["repository_url"],
        "description": pkg["description"],
        "stars": pkg["stars"],
        "forks": pkg["forks"],
        "language": pkg["language"].lower(),
    }


def get_top_PyPI_package(repo_num=1000, repo_size=100000):
    search = Search()
    auth = Auth.Token("")
    g = Github(auth=auth)
    package_list = []
    if repo_num % 100 == 0:
        pagenum = repo_num // 100 + 1
    else:
        pagenum = repo_num // 100 + 2

    for page in tqdm(range(1, pagenum)):
        retries = 3  # 最大重试次数
        retry_delay = 5  # 重试间隔（秒）

        for attempt in range(retries):
            try:
                info = search.project_search(
                    keywords="",
                    languages="Python",
                    sort="dependent_repos_count",
                    platform="pypi",
                    page=page,
                    per_page=min(100, repo_num - 100 * (page - 1)),
                )
                package_list += info
                logger.info(f"package_list: {len(package_list)} (page {page}/{pagenum-1})")
                break  # 成功获取数据，跳出重试循环

            except (RequestException, Exception) as e:
                if attempt < retries - 1:  # 如果不是最后一次尝试
                    logger.warning(
                        f"Error fetching page {page}: {str(e)}. Retrying in {retry_delay}s... (attempt {attempt+1}/{retries})"
                    )
                    time.sleep(retry_delay)
                    retry_delay *= 2  # 指数退避策略
                else:
                    logger.error(
                        f"Failed to fetch page {page} after {retries} attempts: {str(e)}"
                    )

    url_list = []
    repo_list = []
    for item in tqdm(package_list):
        # 有些包没有github链接
        if item["repository_url"] is None:
            continue
        if item["repository_url"].find("github") == -1:
            continue
        # 处理github链接
        repo_url = item["repository_url"].rstrip("/")
        if item["repository_url"].endswith(".git"):
            item["repository_url"] = item["repository_url"][:-4]
        # 解析出github仓库的owner/repo
        parsed_url = urlparse(item["repository_url"])
        path_parts = parsed_url.path.strip("/").split("/")
        if len(path_parts) == 2:
            item["name"] = path_parts[0] + "/" + path_parts[1]
        else:
            continue
        # 去重
        duplication = False
        for repo in repo_list:
            if item["repository_url"] == repo["repository_url"]:
                duplication = True
                break
        if not duplication:
            repo_list.append(item)

    # 筛选掉大小超过限制的仓库
    def check_repo_size(item):
        try:
            repo = g.get_repo(item["name"])
            if repo.size <= repo_size:
                return item
        except Exception as e:
            logger.error(f"Error checking {item['name']}: {str(e)}")
        return None

    new_repo_list = []
    with ThreadPoolExecutor(max_workers=8) as executor:  # 减少workers避免API限流
        futures = [executor.submit(check_repo_size, item) for item in repo_list]
        for future in tqdm(
            as_completed(futures), total=len(repo_list), desc="Checking repo sizes"
        ):
            if result := future.result():
                new_repo_list.append(package_to_dict(result))

    # 按stars排序
    new_repo_list.sort(key=lambda x: x["stars"], reverse=True)
    logger.info(f"repo_list count: {len(new_repo_list)}")
    return new_repo_list


if __name__ == "__main__":
    list = get_top_PyPI_package(repo_num=3000, repo_size=100000)
    # auth = Auth.Token("")
    # g = Github(auth=auth)
    # repo = g.get_repo("jd/tenacity")
    # logger.info(repo.size)
