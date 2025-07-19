import docker
import os
from loguru import logger
import tarfile

# 设置日志记录
logger.add("docker_utils.log")


def copy_to_container(container, src_path, dest_path):
    """
    将文件或目录复制到 Docker 容器中。
    Args:
        container (docker.models.containers.Container): 目标容器对象。
        src_path (str): 要复制的源路径，可以是文件或目录。
        若src_path是目录，则将其内容复制到目标路径。
        若src_path是文件，则将其复制到目标路径。
        dest_path (str): 目标路径，在容器内的路径。
    Returns:
        bool: 如果复制成功，返回 True，否则返回 False。
    """
    # 检查源路径是否存在
    if not os.path.exists(src_path):
        logger.error(f"Source path does not exist: {src_path}")
        return False

    # 检查目标路径不为空
    if not dest_path:
        logger.error("Destination path cannot be empty")
        return False

    try:
        # 根据源路径是文件还是目录采用不同的处理方式
        if os.path.isfile(src_path):
            # 如果是文件，创建一个临时目录来存放文件
            import tempfile
            import shutil

            with tempfile.TemporaryDirectory() as temp_dir:
                # 复制文件到临时目录
                temp_file_path = os.path.join(temp_dir, os.path.basename(src_path))
                shutil.copy2(src_path, temp_file_path)

                # 创建 tar 文件
                tar_file = f"{temp_dir}/temp.tar"
                with tarfile.open(tar_file, "w") as tar:
                    # 添加文件到 tar，arcname 只使用文件名，不包含路径
                    tar.add(temp_file_path, arcname=os.path.basename(src_path))

                # 确保目标目录存在
                parent_dir = os.path.dirname(dest_path)
                if parent_dir:
                    container.exec_run(f"mkdir -p {parent_dir}")

                # 将 tar 文件复制到容器中并解压
                with open(tar_file, "rb") as f:
                    # 如果目标路径是目录，则把文件放在该目录下
                    # 如果目标路径是文件，则直接覆盖该文件
                    if dest_path.endswith("/"):
                        put_path = dest_path
                    else:
                        put_path = os.path.dirname(dest_path)
                        if not put_path:
                            put_path = "/"

                    container.put_archive(put_path, f.read())

                    # 如果目标路径指定了不同的文件名，则重命名
                    if not dest_path.endswith("/") and os.path.basename(
                        dest_path
                    ) != os.path.basename(src_path):
                        container.exec_run(
                            f"mv {os.path.join(put_path, os.path.basename(src_path))} {dest_path}"
                        )

        else:  # 目录复制
            # 在容器中创建目标路径
            container.exec_run(f"mkdir -p {dest_path}")

            # 构建 tar 文件
            tar_file = f"{src_path}.tar"
            with tarfile.open(tar_file, "w") as tar:
                for item in os.listdir(src_path):
                    item_path = os.path.join(src_path, item)
                    tar.add(item_path, arcname=item)

            # 将 tar 文件复制到容器中
            with open(tar_file, "rb") as f:
                container.put_archive(dest_path, f.read())

            # 删除临时 tar 文件
            os.remove(tar_file)

        logger.info(f"Successfully copied {src_path} to container at {dest_path}")
        return True

    except docker.errors.APIError as e:
        logger.error(
            f"Docker API error while copying {src_path} to container {container.id}: {e}"
        )
        return False
    except Exception as e:
        logger.error(
            f"Unexpected error copying {src_path} to container {container.id}: {e}",
            exc_info=True,
        )
        return False


def check_image_exists(image_tag):
    client = docker.from_env()
    try:
        client.images.get(image_tag)
        return True
    except docker.errors.ImageNotFound:
        return False


def build_image_from_dockerfile(
    path: str,
    tag: str,
    dockerfile_content: str,
    build_args: dict = None,
    nocache: bool = False,
    print_logs: bool = False,
    rebuild: bool = False,
):
    """
    根据给定的 Dockerfile 字符串内容和构建上下文路径构建 Docker 镜像。
    (会将字符串内容写入构建上下文中的临时 Dockerfile 文件进行构建)。
    如果存在同名镜像，会先尝试移除旧镜像。

    Args:
        path (str): 构建上下文的目录路径 (Dockerfile 中的 COPY/ADD 指令会相对于此路径)。
        tag (str): 要应用于构建镜像的标签 (例如, 'my-image:latest')。
        dockerfile_content (str): 包含 Dockerfile 指令的字符串。
        build_args (dict, optional): 构建参数字典。默认为 None。
        nocache (bool, optional): 构建时禁用缓存。默认为 False。
        print_logs (bool, optional): 是否打印构建日志。默认为 False。

    Returns:
        docker.models.images.Image or None: 如果成功，返回构建的镜像对象，否则返回 None。
    """
    client = docker.from_env()
    # Define a name for the temporary Dockerfile within the context
    temp_dockerfile_name = "Dockerfile"
    temp_dockerfile_path = os.path.join(path, temp_dockerfile_name)
    try:
        # 若rebuild为True，则先检查是否存在同名镜像，如果存在则尝试移除
        try:
            image = client.images.get(tag)
            if rebuild:
                logger.warning(
                    f"Image '{tag}' already exists. Attempting to remove it..."
                )
                removed = remove_image(tag, force=True)
                if removed:
                    logger.info(
                        f"Successfully removed or confirmed absence of existing image '{tag}'."
                    )
                else:
                    # If removal failed, log a warning but proceed with the build attempt.
                    # Docker build might handle overwriting depending on its configuration or if the image isn't actively used.
                    logger.warning(
                        f"Failed to remove existing image '{tag}'. Build might fail if tag is in use and cannot be overwritten."
                    )
            else:
                logger.info(f"Image '{tag}' already exists.")
                return image
        except docker.errors.ImageNotFound:
            logger.info(f"Image '{tag}' does not exist. Proceeding with build.")
        except docker.errors.APIError as e:
            logger.error(
                f"API error checking/removing image '{tag}': {e}. Proceeding with build attempt, but it might fail."
            )
            
        # 确保构建上下文路径存在
        if not os.path.isdir(path):
            logger.error(
                f"Build context path does not exist or is not a directory: {path}"
            )
            return None

        # 将 Dockerfile 字符串写入上下文中的临时文件
        try:
            with open(temp_dockerfile_path, "w", encoding="utf-8") as f:
                f.write(dockerfile_content)
            logger.debug(
                f"Successfully wrote dockerfile content to temporary file: {temp_dockerfile_path}"
            )
        except IOError as e:
            logger.error(
                f"Failed to write temporary Dockerfile to {temp_dockerfile_path}: {e}"
            )
            return None

        # 使用写入的临时文件的相对名称作为 dockerfile 参数
        image, build_log = client.images.build(
            path=path,
            dockerfile=temp_dockerfile_name,  # 使用临时文件的相对路径
            tag=tag,
            buildargs=build_args,
            nocache=nocache,
            rm=True,  # 成功构建后移除中间容器
            forcerm=True,  # 即使失败，也始终移除中间容器
        )

        if print_logs:
            # 记录构建输出
            for chunk in build_log:
                if "stream" in chunk:
                    line = chunk["stream"].strip()
                    if line:  # 避免打印空行
                        logger.info(line)
                elif "errorDetail" in chunk:
                    logger.error(f"Build error: {chunk['errorDetail']['message']}")
                    # 返回前仍需清理临时文件，所以使用 finally
                    return None

        # logger.info(f"Successfully built image '{tag}' with ID: {image.id}")
        return image

    except docker.errors.BuildError as e:
        logger.error(f"Docker build failed for tag '{tag}': {e}")
        # 如果异常中包含详细的构建错误，则记录它们
        if hasattr(e, "build_log"):  # Check if build_log exists
            for line in e.build_log:
                if "stream" in line:
                    log_line = line["stream"].strip()
                    if log_line:
                        logger.error(f"Build Log: {log_line}")
                elif "error" in line:
                    logger.error(f"Build Error: {line['error']}")
        return None
    except docker.errors.APIError as e:
        logger.error(f"Docker API error while building image '{tag}': {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred while building image '{tag}': {e}")
        return None


def build_container(
    image_tag: str,
    container_name: str,
    container_args: dict = None,
):
    """
    从参数中的dockerfile和脚本构建 Docker 镜像，然后从这个镜像创建并运行容器。
    如果存在同名容器，会先停止并移除旧容器。

    Args:
        path (str): 构建上下文的目录路径。
        tag (str): 要应用于构建镜像的标签。
        dockerfile_content (str): 包含 Dockerfile 指令的字符串。
        build_args (dict, optional): 构建参数字典。默认为 None。
        nocache (bool, optional): 构建时禁用缓存。默认为 False。
        container_args (dict, optional): 容器运行参数，例如：
            {
                'command': 'echo hello',  # 覆盖默认命令
                'environment': {'ENV_VAR': 'value'},  # 环境变量
                'ports': {'8080/tcp': 8080},  # 端口映射
                'volumes': {'/host/path': {'bind': '/container/path', 'mode': 'rw'}},  # 卷挂载
                'detach': False,  # 是否在后台运行
                'remove': True,  # 容器退出后是否自动删除
                'name': 'my-container'  # 容器名称
            }

    Returns:
        docker.models.containers.Container or None: 如果成功，返回容器对象，否则返回 None
    """
    client = docker.from_env()  # 将 client 初始化移到前面
    try:
        # 准备容器运行参数
        run_args = {
            "image": image_tag,
            "detach": True,  # 要返回容器对象，必须在后台运行
            "command": "tail -f /dev/null",  # 默认命令，保持容器运行
            "name": container_name,  # 使用标签作为容器名称
            "environment": {
                "http_proxy": "http://172.17.0.1:10809",
                "https_proxy": "http://172.17.0.1:10809",
            }
        }

        # 如果提供了容器参数，更新默认参数
        if container_args:
            run_args.update(container_args)

        # 检查是否存在同名容器并移除
        container_name = run_args.get("name")

        if container_name:
            # 移除同名容器
            try:
                existing_container = client.containers.get(container_name)
                logger.warning(
                    f"Container with name '{container_name}' already exists. Stopping and removing it."
                )
                success = stop_remove_container(existing_container, force=True)
                if not success:
                    logger.error(f"Failed to remove container {container_name}")
                    return None
            except docker.errors.NotFound:
                logger.info(
                    f"No existing container found with name '{container_name}'. Proceeding to create."
                )
            except Exception as e:
                logger.error(
                    f"Error checking existing container '{container_name}': {e}"
                )

        # 尝试运行容器
        logger.info(
            f"Starting container from image '{image_tag}' with name '{container_name}'..."
        )
        container = client.containers.run(**run_args)

        if run_args.get("detach", False):
            # logger.info(f"Container '{container_name}' started in detached mode with ID: {container.id}")
            pass
        else:
            # 如果在前台运行，输出容器日志
            if isinstance(container, bytes):
                logger.info(
                    f"Container '{container_name}' output: {container.decode().strip()}"
                )
            else:
                logger.info(
                    f"Container '{container_name}' started with ID: {container.id}"
                )

        return container

    except Exception as e:
        logger.error(f"An unexpected error occurred while running container: {e}")
        return None


def get_container_image_tag(container):
    # 尝试获取镜像标签，即使容器已停止也应该能获取到
    image_tag_to_remove = None
    try:
        container.reload()  # 确保属性是最新的
        image_tag_to_remove = (
            container.image.tags[0] if container.image.tags else container.image.id
        )
        logger.info(f"Container {container.id} uses image: {image_tag_to_remove}")
    except Exception as e:
        logger.warning(f"Could not get image tag for container {container.id}: {e}")
    return image_tag_to_remove


def stop_remove_container(container, force=False):
    """
    停止并删除指定的容器，并尝试删除对应的镜像。

    Args:
        container (docker.models.containers.Container): 要停止和删除的容器对象。
        force (bool, optional): 是否强制删除容器和镜像。默认为 False。

    Returns:
        bool: 如果容器和镜像（如果找到）都成功清理，返回 True，否则返回 False。
    """
    container_id = None
    container_removed = False
    try:
        if container is None:
            logger.warning("No container provided to stop and remove")
            return False

        container_id = container.id

        # 检查容器状态并停止/删除
        try:
            container.reload()  # 再次刷新容器状态
            if container.status == "running":
                logger.info(f"Stopping container {container_id}...")
                container.stop()

            if not container.attrs.get("HostConfig", {}).get("AutoRemove", False):
                logger.info(f"Removing container {container_id}...")
                container.remove(force=force)
            container_removed = True
            logger.info(f"Container {container_id} cleaned up successfully")

        except docker.errors.NotFound:
            logger.warning(
                f"Container {container_id} not found during stop/remove, might have been already removed"
            )
            container_removed = True
        except Exception as e:
            logger.error(f"Error cleaning up container {container_id}: {e}")
            return False

        if container_removed:
            return True
        else:
            return False

    except Exception as e:
        logger.error(
            f"Unexpected error while cleaning up container {container_id}: {e}"
        )
        return False


def stop_remove_container_remove_image(container, force=False):
    image_tag = get_container_image_tag(container)
    if image_tag:
        remove_image(image_tag, force=force)
    stop_remove_container(container, force=force)


def remove_image(image_tag, force=False):
    """
    删除指定的 Docker 镜像。

    Args:
        image_tag (str): 要删除的镜像标签。
        force (bool, optional): 是否强制删除。默认为 False。

    Returns:
        bool: 如果操作成功，返回 True，否则返回 False。
    """
    try:
        if not image_tag:
            logger.warning("No image tag provided to remove")
            return False

        client = docker.from_env()
        try:
            logger.info(f"Removing image {image_tag}...")
            client.images.remove(image_tag, force=force)
            logger.info(f"Image {image_tag} removed successfully")
            return True

        except docker.errors.ImageNotFound:
            logger.warning(
                f"Image {image_tag} not found, might have been already removed"
            )
            return True
        except Exception as e:
            logger.error(f"Error removing image {image_tag}: {e}")
            return False

    except Exception as e:
        logger.error(f"Unexpected error while removing image: {e}")
        return False


def save_container(container, tag):
    """
    保存容器为镜像。
    """
    tag = tag.replace(":", "_").replace("/", "_")  # 替换冒号以避免路径问题
    tag = tag.lower()  # 转换为小写以避免路径问题
    client = docker.from_env()
    # 添加 changes 参数来修改新镜像的 CMD 和 WORKDIR
    # 您可以将 "/app" 替换为您期望的 WORKDIR
    change_instructions = 'CMD ["/bin/bash"]\nWORKDIR /'
    client.containers.get(container.id).commit(
        repository=tag,
        changes=change_instructions
    )
    
    logger.info(f"Container {container.id} saved as image {tag} with changes: {change_instructions.replace("\n", "; ")}")
    return True