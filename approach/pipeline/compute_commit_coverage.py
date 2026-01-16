import os
import subprocess
from pathlib import Path
from typing import List

def build_docker_image(commit_hash: str, output_dir: str) -> None:
    """
    Build a Docker image for the given commit hash and compute coverage.
    """
    image_name = f"qiskit-commit-{commit_hash}"
    dockerfile_path = "docker/qiskit/by_commit/dockerfile"
    subprocess.run([
        "docker", "build",
        "--build-arg", f"COMMIT_HASH={commit_hash}",
        "--build-arg", f"UID={os.getuid()}",
        "--build-arg", f"GID={os.getgid()}",
        "-t", image_name,
        "-f", dockerfile_path,
        "."
    ], check=True)

    path_local_folder = Path(output_dir) / f"{commit_hash}_coverage"
    path_local_folder.mkdir(parents=True, exist_ok=True)

    # Run the container to compute coverage
    container_name = f"{image_name}-container"
    subprocess.run([
        "docker", "run", "-d", "--rm",
        "--name", container_name,
        image_name,
        "tail", "-f", "/dev/null"
    ], check=True)

    # Copy coverage files from the container to the output directory
    subprocess.run([
        "docker", "cp",
        f"{container_name}:/workspace/coverage",
        f"{str(path_local_folder)}"
    ], check=True)

    # Stop the container
    subprocess.run(["docker", "stop", container_name], check=True)

def compute_commit_coverage(commit_list_file: str, output_dir: str) -> None:
    """
    Compute coverage for a list of commit hashes.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    with open(commit_list_file, "r") as f:
        commit_hashes = [line.strip() for line in f.readlines()]

    for commit_hash in commit_hashes:
        print(f"Processing commit: {commit_hash}")
        build_docker_image(commit_hash, output_dir)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Compute coverage for a list of commit hashes.")
    parser.add_argument("--commit_list", required=True, help="Path to the file containing commit hashes.")
    parser.add_argument("--output_dir", required=True, help="Directory to store coverage reports.")
    args = parser.parse_args()
    output_dir = args.output_dir
    abs_output_dir = os.path.abspath(output_dir)
    compute_commit_coverage(args.commit_list, abs_output_dir)
