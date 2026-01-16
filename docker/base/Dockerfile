FROM ubuntu:22.04

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# ===========================================
# System dependencies (Python, git, Make, etc.)
# ===========================================

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    wget \
    python3 \
    python3-pip \
    python3-venv \
    python3-setuptools \
    build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# put the python3 on the path and call it as python
RUN ln -s /usr/bin/python3 /usr/bin/python

# Install Python packages needed for building and testing
RUN python -m pip install --no-cache-dir \
    coverage==7.6.2 \
    cython \
    unidiff \
    click \
    rich \
    pytest \
    pytest-cov \
    stestr \
    ddt \
    lcov_cobertura==1.6 \
    tox \
    pytest-xdist \
    pytest-timeout && \
    python -m pip install --upgrade pip setuptools wheel

WORKDIR /opt/

# ===========================================
# User and permissions
# ===========================================

ARG UID=1000
ARG GID=1000
# Change the root password to "root"
RUN echo "root:root" | chpasswd
# Create a non-root user and prepare the /opt directory
RUN groupadd -g $GID regularuser && \
    useradd -m -u $UID -g $GID -s /bin/bash regularuser && \
    mkdir -p /opt && chown -R regularuser /opt

# Switch to non-root user for subsequent steps
USER regularuser

# Set the entrypoint
ENTRYPOINT ["/bin/bash"]
