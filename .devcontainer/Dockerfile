FROM ubuntu:latest
WORKDIR /scratch

# Environment variables
ENV TZ=Etc/UTC
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python
ENV UV_CACHE_DIR=/opt/uv/.cache/uv
ENV UV_LINK_MODE=symlink
ENV XDG_BIN_HOME=/root/.local/bin
ENV PATH=${XDG_BIN_HOME}:.codeguide/tasks:${PATH}

# Directories for mounting volumes
RUN mkdir -p /opt/uv /root/.vscode-server/extensions

# base-deps
RUN --mount=type=bind,source=.devcontainer/installers/apt-get.sh,target=./apt-get.sh \
  ./apt-get.sh

# uv
RUN --mount=type=bind,source=.devcontainer/installers/uv.sh,target=./uv.sh \
  ./uv.sh

# python
RUN --mount=type=bind,source=.devcontainer/installers/python.sh,target=./python.sh \
  ./python.sh

# yq
RUN --mount=type=bind,source=.devcontainer/installers/yq.sh,target=./yq.sh \
  ./yq.sh

# python-tools
RUN --mount=type=bind,source=.devcontainer/installers/python-tools.sh,target=./python-tools.sh \
  ./python-tools.sh

# ohmybash
RUN --mount=type=bind,source=.devcontainer/installers/ohmybash.sh,target=./ohmybash.sh \
  ./ohmybash.sh

# setup bashrc
RUN echo ". .devcontainer/home/bashrc.sh" >>/root/.bashrc
