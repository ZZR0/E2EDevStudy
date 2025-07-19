# 获取满足一定条件的python仓库

from github import Github
import utils.utils
from loguru import logger

g = Github("")


def get_top_repo(language, stars_num, update_time, repo_num=100, size_limit=10000):
    """
    获取满足一定条件的python仓库的链接
    参数：
    language (str): 语言
    stars_num (int): stars数量
    update_time (str): 更新时间
    repo_num (int): 仓库数量
    return: 仓库列表
    """
    query = "language:{} stars:>{} pushed:>={} size:<{}".format(
        language, stars_num, update_time, size_limit
    )
    logger.info("searching for repositories with query: %s", query)
    repos = g.search_repositories(query=query, sort="stars", order="desc")
    logger.info("search completed")
    repo_list = []
    for repo in repos[:repo_num]:
        repo_list.append(utils.utils.repo_to_dict(repo))
        logger.info(f"repo {repo.full_name} added")
    return repo_list


if __name__ == "__main__":
    repo_list = get_top_repo(
        language="java", stars_num=10000, update_time="2017-01-01", size_limit=20000
    )
    for repo in repo_list:
        logger.info(repo["repo_name"])
        logger.info("stars: %s", repo["stars"])
        logger.info("size: %s", repo["size"])
        logger.info("url: %s", repo["url"])
