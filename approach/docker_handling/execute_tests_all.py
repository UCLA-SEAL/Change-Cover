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
from ..coverage.compare_coverage import get_coverage_json
from concurrent.futures import ThreadPoolExecutor, as_completed
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

def parse_command(command: str):
    """
    read the command file and parse it into a list of strings
    """
    with open(command, "r") as f:
        return [line.strip() for line in f if line.strip()]

def store_pr_result(prefix: str, host_path: str, proj: str, pr: str, covered_json: dict):
    """

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
            results = {}
    else:
        results = {}
    
    # Update results[pr][prefix]
    if pr in results:
        results[pr][prefix] = covered_json
    else:
        results[pr] = {
            prefix: covered_json
        }

    # Write back to the results file
    try:
        with open(results_file, "w") as f:
            json.dump(results, f, indent=4)
        print(f"Results for PR {pr} written to {results_file}")
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


def run_all_tests(image_name: str, proj: str, diff: str, commands: str, volume_list=None, regression=False):
    """
    Run a container for a given image and execute a combined command that runs:
      1. pytest with coverage (output suppressed)

    After the container finishes, the coverage xml is copied from the container to the host

    Args:
        image_name (str): The Docker image name (e.g., 'pandas-pr-60628')
        proj (str): The project name (used for building default volume paths if not provided)
        diff_name (str): path to the diff file
        volume_list (list[str], optional): A list of volume mapping strings.
        regression (bool): Run regression test suite, default to false.
    """
    client = docker.from_env()
    host_path = os.getcwd()
    pr_number = image_name.split("-")[-1]

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
            }
        }
    
    os.makedirs(f"{host_path}/data/test_augmentation/{proj}/pr/", exist_ok=True)

    # Build the combined command.
    concrete_commands = " && ".join([command.format(**locals()) for command in commands])

    command = ["/bin/bash", "-c", concrete_commands]
    print(f"Running image {image_name} with command: {concrete_commands}")

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

        # Define paths and json prefix
        if regression:
            container_cov_path = "/workspace/regression_cov.xml"
            host_cov_path = f"/tmp/regression_cov_{pr_number}.xml"
            prefix = "regression"
        else:
            container_cov_path = "/workspace/pr_cov.xml"
            host_cov_path = f"/tmp/pr_cov_{pr_number}.xml"
            prefix = "pr"

        # Copy from inside the container to the host
        copy_file_from_container(container, container_cov_path, host_cov_path)

        # Compute coverage difference
        covered_json = get_coverage_json(diff, host_cov_path)

        # Parse the coverage dictionary
        if os.path.exists(host_cov_path):
            try:
                store_pr_result(prefix, host_path, proj, pr_number, covered_json)
            except Exception as e:
                # print(f"Failed to read or parse the coverage file {host_cov_path}: {e}", file=sys.stderr)
                # print out the backtrace
                raise e
        else:
            print(f"Results file {host_cov_path} does not exist.", file=sys.stderr)

    except (APIError, NotFound) as e:
        print(f"Docker API error occurred for image {image_name}: {e}", file=sys.stderr)
    finally:
        if container:
            try:
                container.remove(force=True)
            except Exception as e:
                print(f"Failed to remove container {container.id}: {e}", file=sys.stderr)

# def run_all_prs(proj: str, txt_pr_list: str, diff: str, command: str, volume_list=None, regression=False):
#     """
#     Run tests for all PRs for one project.

#     Args:
#         proj (str): Name of the project.
#         txt_pr_list (str): Path to the text file containing the list of PRs.
#         volume_list (list[str], optional): A list of volume mapping strings (e.g., "host_path:container_path[:mode]").
#         regression (bool): Run regression test suite, default to false.
#     """
#     pr_list = read_pr_list(txt_pr_list)
#     commands = parse_command(command)
#     for pr in tqdm(pr_list, desc="Processing PRs"):
#         image_name = f"{proj}-pr-{pr}"
#         diff_path = f"{diff}/{pr}.diff"
#         run_all_tests(image_name, proj, diff_path, commands, volume_list=volume_list, regression=regression)


import docker
from concurrent.futures import ThreadPoolExecutor, as_completed

def run_all_prs(
    proj: str,
    txt_pr_list: str,
    diff: str,
    command: str,
    volume_list=None,
    regression=False,
    num_workers=4
):
    """
    Run tests for all PRs for one project, in parallel, with simple prints for progress.
    Stops all threads/futures if the user presses Ctrl+C, and ensures containers are stopped
    for *all* matching images.
    """
    pr_list = read_pr_list(txt_pr_list)
    commands = parse_command(command)

    executor = ThreadPoolExecutor(max_workers=num_workers)

    futures = {}
    image_names = []

    # Submit jobs
    for pr in pr_list:
        image_name = f"{proj}-pr-{pr}"
        image_names.append(image_name)
        diff_path = f"{diff}/{pr}.diff"

        future = executor.submit(
            run_all_tests,
            image_name,
            proj,
            diff_path,
            commands,
            volume_list=volume_list,
            regression=regression
        )
        futures[future] = pr

    print(f"Submitted {len(futures)} tasks...")

    completed_count = 0
    total = len(futures)

    try:
        for future in as_completed(futures):
            pr = futures[future]
            completed_count += 1
            try:
                future.result()
                print(f"[{completed_count}/{total}] PR {pr} completed successfully.")
            except Exception as e:
                print(f"[{completed_count}/{total}] PR {pr} failed: {e}")

    except KeyboardInterrupt:
        print("KeyboardInterrupt received! Cancelling running tasks...")
        executor.shutdown(wait=False, cancel_futures=True)

        # Build a set of image prefixes for quick membership testing
        image_prefixes = set(image_names)

        try:
            client = docker.from_env()
            # If you only care about *running* containers, remove `all=True`.
            for container in client.containers.list(all=True):
                # Check if any tag matches one of our built image prefixes
                # (split off the ":some-tag" suffix for each tag).
                if any(
                    tag.split(":")[0] in image_prefixes
                    for tag in container.image.tags
                ):
                    if container.status == "running":
                        container.stop()
                        print(f"Stopped container {container.name} ({container.image.tags})")
                    container.remove()
                    print(f"Removed container {container.name} ({container.image.tags})")

        except Exception as e:
            print(f"Failed to stop/remove some containers: {e}")

        # Re-raise to exit the program
        raise

    else:
        executor.shutdown(wait=True)

    print("All PRs have been processed (or cancelled).")





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
    "--diff", "-d",
    required=True,
    help="Path to the directory containing the diff files."
)
@click.option(
    "--volume", "-v",
    multiple=True,
    help=(
        "Volume to mount in the format host_path:container_path[:mode]. "
        "Use multiple --volume options for multiple mounts."
    )
)
@click.option(
    "--command", "-c",
    required=True,
    help="Command script to run inside the container."
)
@click.option(
    "--regression", "-R",
    is_flag=True,
    default=False,
    help="Run regression test suite, default to false."
)
@click.option(
    "--num-workers", "-w",
    default=4,
    help="Number of workers to use in the pool.",
    show_default=True
)
def main(proj, pr_list, diff, command, volume, regression, num_workers):
    """
    Entry point for the Docker-based test execution script.
    Runs tests for each PR defined in the provided PR list.
    """
    run_all_prs(proj, pr_list, diff, command, volume_list=volume, regression=regression, num_workers=num_workers)

if __name__ == "__main__":
    main()
