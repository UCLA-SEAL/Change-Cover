#!/usr/bin/env python3
"""
execute_tests_module.py

This module runs tests for all PRs for a given project by using the Docker SDK.
It reads a list of PR numbers from a provided text file and, for each PR,
launches a container with the image named "<proj>-pr-<PR number>" and runs
a combined bash command which:
  - Changes directory to /workspace
  - Runs Pytest with coverage (with its output suppressed)
  - Then runs the test relevance script (writing output to covdict.json)

After the container completes, the generated covdict.json is copied from the container
to the host's /tmp directory, parsed, and its coverage ratio is stored in a cumulative
results file:
  {host_path}/data/test_augmentation/{proj}/pr/results/prs_results.json

Usage (via Click):
  python -m execute_tests_module --proj <project_name> --pr-list <path_to_pr_list> [-v <volume> ...]
"""

import os
import sys
import json
import docker
import click
from tqdm.auto import tqdm
from docker.errors import APIError, NotFound
import tarfile
import io

def read_pr_list(txt_pr_list: str):
    """
    Reads a text file containing PR numbers (one per line) and returns a list of strings.
    """
    with open(txt_pr_list, "r") as f:
        return [line.strip() for line in f if line.strip()]

def ensure_directory(path: str):
    """Ensure that a directory exists; if not, create it."""
    if not os.path.exists(path):
        os.makedirs(path)

def store_pr_result(host_path: str, proj: str, pr: str, coverage_ratio: float, covered_lines: int, missed_lines: int):
    """
    Append the coverage ratio for a given PR into a cumulative JSON file.

    The cumulative results file is located at:
      {host_path}/data/test_augmentation/{proj}/pr/results/prs_results.json

    The JSON file stores a list of dictionaries, each with:
      { "pr": <pr_number>, "coverage_ratio": <coverage_ratio> }
    """
    results_dir = os.path.join(host_path, "data", "test_augmentation", proj, "pr", "results")
    ensure_directory(results_dir)
    results_file = os.path.join(results_dir, "prs_results.json")

    # Load existing results
    if os.path.exists(results_file):
        try:
            with open(results_file, "r") as f:
                results = json.load(f)
        except Exception:
            print(f"Failed to read existing results from {results_file}. Overwriting.", file=sys.stderr)
            results = []
    else:
        results = []

    # Check if PR already exists in results
    for entry in results:
        if entry.get("pr") == pr:
            entry["coverage_ratio"] = coverage_ratio
            entry["covered_lines"] = covered_lines
            entry["missed_lines"] = missed_lines
            break
    else:
        # Append new entry if PR not found
        results.append({"pr": pr, "coverage_ratio": coverage_ratio, "covered_lines": covered_lines, "missed_lines": missed_lines})

    # Write back to the results file
    try:
        with open(results_file, "w") as f:
            json.dump(results, f, indent=4)
        print(f"Coverage ratio for PR {pr} stored in {results_file}")
    except Exception as e:
        print(f"Failed to write results to {results_file}: {e}", file=sys.stderr)

def copy_file_from_container(container, container_path: str, host_path: str):
    """
    Copies a file from the container to the host.

    Args:
        container: Docker SDK container object
        container_path (str): Path to the file inside the container
        host_path (str): Path on the host to save the file
    """
    try:
        bits, stat = container.get_archive(container_path)
        file_data = b''.join(bits)
        tar = tarfile.open(fileobj=io.BytesIO(file_data))
        member = tar.getmember(os.path.basename(container_path))
        file_content = tar.extractfile(member).read()
        with open(host_path, 'wb') as f:
            f.write(file_content)
        print(f"Copied {container_path} to {host_path}")
    except Exception as e:
        print(f"Failed to copy {container_path} to {host_path}: {e}", file=sys.stderr)

def run_all_tests(image_name: str, proj: str, diff_name: str, volume_list=None):
    """
    Run a container for a given image and execute a combined command that runs:
      1. pytest with coverage (output suppressed)
      2. python util/test_relevance.py <diff_name> coverage.xml > covdict.json

    After the container finishes, covdict.json is copied to /tmp, parsed,
    and the coverage ratio is stored in the cumulative results file.

    Args:
        image_name (str): The Docker image name (e.g., 'pandas-pr-60628')
        proj (str): The project name (used for building default volume paths if not provided)
        diff_name (str): The diff file to pass to test_relevance.py (e.g., 'diffs/60628.diff')
        volume_list (list[str], optional): A list of volume mapping strings.
    """
    client = docker.from_env()
    host_path = os.getcwd()

    # Define default volumes if not provided
    if volume_list:
        volumes = {}
        for vol in volume_list:
            parts = vol.split(":")
            if len(parts) >= 2:
                host_vol = parts[0]
                container_vol = parts[1]
                mode = parts[2] if len(parts) == 3 else "rw"
                volumes[host_vol] = {"bind": container_vol, "mode": mode}
            else:
                print(f"Invalid volume format: {vol}. Skipping.", file=sys.stderr)
    else:
        volumes = {
            f"{host_path}/data/test_augmentation/{proj}/pr/test_cases": {
                "bind": "/workspace/test",
                "mode": "rw"
            },
            f"{host_path}/data/test_augmentation/{proj}/pr/diffs": {
                "bind": "/workspace/diffs",
                "mode": "rw"
            },
            f"{host_path}/docker/{proj}/util": {
                "bind": "/workspace/util",
                "mode": "rw"
            }
            # No volume mount for /workspace/results
        }

    # Build the combined command.
    combined_command = (
        "cd /workspace && "
        f"pytest --cov={proj} --cov-report=xml test > /dev/null 2>&1 ; "
        f"python util/test_relevance.py {diff_name} coverage.xml > covdict.json"
    )
    command = ["/bin/bash", "-c", combined_command]

    container = None
    try:
        # Start the container without auto-removal
        container = client.containers.run(
            image=image_name,
            command=command,
            volumes=volumes,
            tty=True,
            stdin_open=True,
            detach=True,
            remove=False,  # Do not auto-remove to allow file copying
            working_dir="/workspace",
            # Uncomment and set the user if required:
            # user="regularuser",
        )

        # Stream logs from the container
        logs = container.logs(stream=True)
        for line in logs:
            print(line.decode(), end="")

        # Wait for the container to finish
        exit_status = container.wait()
        status_code = exit_status.get("StatusCode", 1)
        if status_code != 0:
            print(f"Container for image {image_name} exited with code {status_code}", file=sys.stderr)
        else:
            print(f"Container for image {image_name} executed successfully.")

        # Define paths
        container_covdict_path = "/workspace/covdict.json"
        host_covdict_path = f"/tmp/covdict_{image_name.split('-')[-1]}.json"

        # Copy covdict.json from container to /tmp
        copy_file_from_container(container, container_covdict_path, host_covdict_path)

        # Parse the coverage dictionary
        if os.path.exists(host_covdict_path):
            try:
                with open(host_covdict_path, "r") as f:
                    cov_data = json.load(f)
                coverage_ratio = cov_data.get("coverage_ratio")
                covered_lines = cov_data.get("covered_lines")
                missed_lines = cov_data.get("missed_lines")
                if coverage_ratio is not None:
                    pr_number = image_name.split('-')[-1]
                    store_pr_result(host_path, proj, pr_number, coverage_ratio, covered_lines, missed_lines)
                else:
                    print(f"'coverage_ratio' not found in {host_covdict_path}", file=sys.stderr)
            except Exception as e:
                print(f"Failed to read or parse the coverage file {host_covdict_path}: {e}", file=sys.stderr)
        else:
            print(f"Results file {host_covdict_path} does not exist.", file=sys.stderr)

    except (APIError, NotFound) as e:
        print(f"Docker API error occurred for image {image_name}: {e}", file=sys.stderr)
    finally:
        if container:
            try:
                container.remove(force=True)
            except Exception as e:
                print(f"Failed to remove container {container.id}: {e}", file=sys.stderr)

def run_all_prs(proj: str, txt_pr_list: str, volume_list=None):
    """
    Run tests for all PRs for one project.

    Args:
        proj (str): Name of the project.
        txt_pr_list (str): Path to the text file containing the list of PRs.
        volume_list (list[str], optional): A list of volume mapping strings (e.g., "host_path:container_path[:mode]").
    """
    pr_list = read_pr_list(txt_pr_list)
    for pr in tqdm(pr_list, desc="Processing PRs"):
        image_name = f"{proj}-pr-{pr}"
        diff_name = f"diffs/{pr}.diff"
        run_all_tests(image_name, proj, diff_name, volume_list=volume_list)

@click.command()
@click.option(
    "--proj", "-p",
    required=True,
    help="Name of the project."
)
@click.option(
    "--pr-list", "-l",
    required=True,
    help="Path to the text file containing the list of PRs."
)
@click.option(
    "--volume", "-v",
    multiple=True,
    help=(
        "Volume to mount in the format host_path:container_path[:mode]. "
        "Use multiple --volume options for multiple mounts."
    )
)
def main(proj, pr_list, volume):
    """
    Entry point for the Docker-based test execution script.
    Runs tests for each PR defined in the provided PR list.
    """
    run_all_prs(proj, pr_list, volume_list=volume)

if __name__ == "__main__":
    main()
