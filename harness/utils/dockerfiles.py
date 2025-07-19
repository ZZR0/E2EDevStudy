DOCKERFILE = """
# 指定基础镜像和平台架构
FROM --platform=linux/amd64 ubuntu:24.04

# 设置环境变量避免交互式提示
ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC

ENV http_proxy=http://172.17.0.1:10809
ENV https_proxy=http://172.17.0.1:10809

# 安装系统依赖
RUN apt-get update -y && \
    apt-get install -y --no-install-recommends \
    ca-certificates \
    wget \
    git \
    build-essential \
    libffi-dev \
    libssl-dev \
    python3 \
    python3-pip \
    python-is-python3 \
    python3-venv \
    python3-dev \
    pipx \
    && rm -rf /var/lib/apt/lists/*
    
RUN pipx install swe-rex


# 设置工作目录（可根据需要修改路径）
WORKDIR {workdir}

# 复制环境配置脚本到容器中
COPY setup_env.sh /tmp/setup_env.sh

# 处理Windows换行符问题（如果脚本来自Windows系统）
RUN sed -i 's/\r$//' /tmp/setup_env.sh && chmod +x /tmp/setup_env.sh

# 创建Python虚拟环境
RUN python3 -m venv /opt/venv

# 激活虚拟环境并安装Python依赖
ENV PATH="/opt/venv/bin:/root/.local/bin:${{PATH}}"

# 执行环境配置脚本
RUN /tmp/setup_env.sh

# 设置容器默认工作目录
WORKDIR {workdir}

ENV http_proxy=
ENV https_proxy=

# 容器启动时默认执行的命令（可根据需要修改）
CMD ["/bin/bash"]
"""
