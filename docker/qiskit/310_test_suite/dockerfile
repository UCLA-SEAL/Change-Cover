FROM python:3.10-slim

ARG UID=1000
ARG GID=1000

# Install essential build tools and libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    curl \
    lcov \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Python packages needed for building and testing
RUN pip install --no-cache-dir \
    coverage==7.6.2 \
    cython \
    unidiff \
    click \
    rich \
    pytest \
    pytest-cov \
    stestr \
    ddt \
    lcov_cobertura==1.6

# Create a non-root user and prepare the /opt directory
RUN groupadd -g $GID regularuser && \
    useradd -m -u $UID -g $GID -s /bin/bash regularuser && \
    mkdir -p /opt && chown -R regularuser /opt

# Switch to non-root user for subsequent steps
USER regularuser

# Install Rust (required for parts of Qiskit)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
      | sh -s -- --default-toolchain stable -y && \
    echo 'export PATH="$HOME/.cargo/bin:$PATH"' >> ~/.bashrc && \
    echo 'export PATH="$HOME/.cargo/bin:$PATH"' >> ~/.profile && \
    /bin/bash -c "source ~/.cargo/env && rustup update stable" && \
    /bin/bash -c "source ~/.cargo/env && rustup component add llvm-tools-preview"

# Ensure Cargo’s bin directory is in PATH
ENV PATH="/home/regularuser/.cargo/bin:${PATH}"

# Install grcov
RUN cargo install grcov
RUN rm -rf /home/regularuser/.rustup/toolchains/stable-x86_64-unknown-linux-gnu/share/doc/rust/html && \
    rm -rf /home/regularuser/.rustup/toolchains/stable-x86_64-unknown-linux-gnu/share/doc/rust && \
    rm -rf /home/regularuser/.rustup/toolchains/stable-x86_64-unknown-linux-gnu/share/doc && \
    rm -rf /home/regularuser/.rustup/toolchains/stable-x86_64-unknown-linux-gnu/share && \
    rm -rf /home/regularuser/.rustup/toolchains/1.70-x86_64-unknown-linux-gnu/share/doc/rust/html && \
    rm -rf /home/regularuser/.rustup/toolchains/1.70-x86_64-unknown-linux-gnu/share/doc/rust && \
    rm -rf /home/regularuser/.rustup/toolchains/1.70-x86_64-unknown-linux-gnu/share && \
    rm -rf /home/regularuser/.cargo/registry


# Build and install qiskit-terra with coverage instrumentation
ENV CARGO_INCREMENTAL=0 \
    RUSTFLAGS="-Cinstrument-coverage" \
    LLVM_PROFILE_FILE="qiskit-%p-%m.profraw" \
    PYTHON="coverage run --source qiskit --parallel-mode" \
    QISKIT_TEST_CAPTURE_STREAMS=1 \
    QISKIT_PARALLEL=FALSE


# Clone the Qiskit repository
WORKDIR /opt
RUN git clone https://github.com/Qiskit/qiskit.git


# Checkout the desired pull request
WORKDIR /opt/qiskit
ARG PR_NUMBER
RUN git config --global alias.pr '!f() { git fetch -fu ${2:-origin} refs/pull/$1/head:pr/$1 && git checkout pr/$1; }; f' \
    && git pr $PR_NUMBER

# # Install Qiskit in editable mode. If constraints.txt exists, use it.
RUN if [ -f constraints.txt ]; then \
        pip install --no-cache-dir -c constraints.txt --upgrade pip setuptools wheel && \
        pip install --no-cache-dir -c constraints.txt -e . ; \
    else \
        pip install --no-cache-dir --upgrade pip setuptools wheel && \
        pip install --no-cache-dir -e . ; \
    fi


# # Run all tests
# RUN sed -i 's/coverage3 report/coverage3 xml/' /opt/qiskit/tox.ini
# RUN python3 -m pip install tox
# RUN python3 -m tox -epy310 -e coverage


# ALTERNATIVE

# Generate coverage reports
# This step combines the Python and Rust coverage reports

# Run the Python script to see numpy state
# Run the tests
RUN python3 tools/report_numpy_state.py && \
    python3 -m stestr run || true
# install required packages for grcov
RUN /bin/bash -c "source ~/.cargo/env && rustup component add llvm-tools-preview"
# Generate the Rust coverage report using grcov
RUN grcov . \
        --binary-path target/debug/ --source-dir . --output-type lcov \
        --output-path rust.info --llvm --branch --parallel \
        --keep-only 'crates/*'

# Combine the Python coverage reports
# Convert the Python coverage report to LCOV format
# Combine the Python and Rust LCOV reports
RUN coverage combine && \
    coverage lcov -o python.info && \
    lcov --add-tracefile python.info --add-tracefile rust.info --output-file coveralls.info && \
    python -m lcov_cobertura coveralls.info --output coverage_all.xml && \
    rm -rf /opt/qiskit/target/debug

# Setup working directory and adjust permissions
WORKDIR /workspace
RUN chown -R regularuser /workspace

# Verify installation by printing the Qiskit version
CMD ["/bin/bash", "-c", "du -ah / | sort -rh | head -n 20"]
# CMD ["python", "-c", "import qiskit; print(qiskit.__version__)"]
