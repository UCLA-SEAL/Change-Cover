import subprocess
import click
import os
from concurrent.futures import ThreadPoolExecutor
from approach.base.pr_patch import PRPatch
from approach.coverage.patch_coverage import PatchCoverage
from rich.console import Console
from rich.progress import Progress

from typing import Optional
import numpy as np

"""## Task Description: Compute Coverage for Pull Requests

### Objective:
Create a command-line interface (CLI) tool that processes a list of pull request (PR) numbers from a given text file, computes the coverage for each PR, and stores the results in a structured output directory. The tool should utilize the

PRPatch

 class for managing patches and be inspired by the provided `compute_patch_coverage.py` and `compute_initial_coverage.sh` files.

### Requirements:

#### Input:
1. **PR List File:**
   - A text file containing PR numbers, one per line.
   - The path to this file will be provided as the first argument to the script.

2. **Repository Information:**
   - A string in the format

owner/repo

 specifying the GitHub repository.
   - This will be provided as the second argument to the script.

3. **Output Directory:**
   - The path to the directory where the output files will be stored.
   - This will be provided as the third argument to the script.

#### Output:
1. **Structured Output Directory:**
   - Each PR will have its own subdirectory within the output directory.
   - The coverage results and any relevant metadata will be stored in these subdirectories.
   - The output directory will contain `coverage` and `diffs` folders.

#### Docker Build and Run:
1. **Dockerfile:**
   - Use the Dockerfile located at `docker/$PROJ/full_test_suite/`.
   - Build the Docker image with the following command:
     ```bash
     docker build --build-arg UID=$(id -u) --build-arg GID=$(id -g) --build-arg PR_NUMBER="$PR_NUMBER" -t "$PROJ-pr-$PR_NUMBER" "$DOCKERFILE_PATH"
     ```

2. **Docker Run:**
   - Run the Docker container to copy the file `coverage_all.xml` from the container to the host:
     ```bash
     docker run --rm -v "$ABS_PATH_PR_OUTPUT_COVERAGE_DIR:/mnt" "$PROJ-pr-$PR_NUMBER" /bin/bash -c "cp /opt/$PROJ/coverage_all.xml /mnt/coverage_all.xml"
     ```

3. **Script Execution in Docker:**
   - Pass a local path to a shell script that will be mounted and executed in the Docker container.

4. **Cleanup:**
   - Optionally remove the Docker image after processing each PR to reclaim space:
     ```bash
     docker rmi "$PROJ-pr-$PR_NUMBER"
     ```

#### Coverage Computation:
1. **Integration with `compute_patch_coverage.py`:**
   - Import and use relevant functions or classes from `compute_patch_coverage.py` to compute the coverage.

#### Error Handling and Logging:
1. **Error Logging:**
   - Log any errors encountered during the build, run, or cleanup steps.
   - Continue processing the next PR even if an error occurs.

2. **Progress Logging:**
   - Create a log file to record the progress and any errors encountered.
   - Include a summary report at the end of the script execution.

#### Parallel Execution:
1. **Parallel Workers:**
   - Support parallel execution of tasks with a configurable number of workers.
   - The number of workers will be provided as an optional argument to the script.

### Implementation Steps:
1. **Parse Input Arguments:**
   - Parse the input arguments for the PR list file, repository information, output directory, and number of workers.

2. **Setup Output Directory:**
   - Create the output directory and necessary subdirectories if they do not exist.

3. **Process Each PR:**
   - For each PR number in the PR list file:
     - Create a

PRPatch

 object to manage the patch.
     - Build the Docker image.
     - Run the Docker container to copy the coverage file.
     - Compute the coverage using `compute_patch_coverage.py`.
     - Log the progress and any errors encountered.
     - Optionally remove the Docker image to reclaim space.

4. **Handle Errors and Logging:**
   - Implement error handling and logging as specified.

5. **Support Parallel Execution:**
   - Implement parallel execution of tasks with the specified number of workers using Python's `concurrent.futures` module.

### Example Usage:
```bash
python compute_coverage.py --pr_list path/to/pr_list.txt --repo_owner/repo_name --output_dir path/to/output --workers 4
```

### Additional Notes:
- Ensure that the script is robust and can handle edge cases gracefully.
- Provide clear and detailed documentation for the CLI tool, including usage examples and troubleshooting tips.


Convert the function above into a click v8 interface in Python.
- map all the arguments to a corresponding option (in click) which is required
- add all the default values of the arguments as default of the click options
- use only underscores
- add a main with the command
- add the required imports
Make sure to add a function and call that function only in the main cli command.
The goal is to be able to import that function also from other files.


"""
console = Console(file=open("patch_coverage.log", "w"), color_system=None)


def get_available_space_fs(filesystem: str = "/dev/sda2") -> Optional[float]:
    """
    Get the available space on the specified filesystem.

    Parameters:
    filesystem (str): The filesystem to check. Default is "/dev/sda2".

    Returns:
    Optional[float]: The available space in GB if successful, None otherwise.
    """
    try:
        result = subprocess.run(
            ['df', '-h'],
            stdout=subprocess.PIPE, text=True, check=True)
        lines = result.stdout.splitlines()

        for line in lines:
            if line.startswith(filesystem):
                parts = line.split()
                if len(parts) >= 4:
                    # The 4th column is the available space
                    available_space_str = parts[3]
                    if available_space_str.endswith('G'):
                        available_space = float(available_space_str[:-1])
                    elif available_space_str.endswith('M'):
                        available_space = float(
                            available_space_str[: -1]) / 1024
                    elif available_space_str.endswith('K'):
                        available_space = float(
                            available_space_str[:-1]) / (1024 * 1024)
                    else:
                        available_space = float(
                            available_space_str) / (1024 * 1024 * 1024)
                    return available_space
        raise ValueError(f"'{filesystem}' not found in df output")
    except subprocess.CalledProcessError as e:
        print(f"Error executing df command: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")
    return None


def prune_docker_builder(keep_storage_gb: int = 20):
    """
    Prune Docker builder cache to keep the specified amount of storage.

    Parameters:
    keep_storage_gb (int): The amount of storage to keep in GB. Default is 100GB.
    """
    keep_storage = f"{keep_storage_gb}GB"
    try:
        result = os.system(
            f'docker builder prune --keep-storage {keep_storage} -f')
        if result != 0:
            print(f"Error executing docker builder prune command: {result}")
    except Exception as e:
        print(f"An error occurred: {e}")


def compute_regression_patch_coverage(
        pr_number, repo, base_dir, guarantee_root_gb: int = 70):
    try:
        available_space = get_available_space_fs()
        if available_space is not None and available_space < guarantee_root_gb:
            console.print(
                f"Available space is below {guarantee_root_gb}GB ({available_space}GB). Pruning Docker builder cache...")
            prune_docker_builder()

        console.print(f"Processing PR {pr_number}...")

        repo_owner = repo.split('/')[0]
        repo_name = repo.split('/')[1]
        pr_patch = PRPatch(
            repo_owner=repo_owner,
            repo_name=repo_name,
            pr_number=pr_number,
            base_dir=base_dir)
        pr_patch.retrieve_diff_file()
        pr_patch._ensure_directories_exist()

        if repo_name.lower() in ["pandas", "scipy"]:
            dockerfile_path = f"docker/{repo_name}/full_test_suite/dockerfile"
        elif repo_name.lower() == "qiskit":
            dockerfile_path = f"docker/{repo_name}/only_python/dockerfile"
        else:
            dockerfile_path = f"docker/{repo_name}/Dockerfile"
        assert os.path.exists(
            dockerfile_path), f"Dockerfile not found at {dockerfile_path}"
        patch_coverage = PatchCoverage(
            pr_patch=pr_patch,
            abs_custom_dockerfile_path=dockerfile_path
        )

        if patch_coverage.pr_patch.patch_coverage_path.exists():
            console.print(f"Coverage already computed for PR {pr_number}.")
            console.print(f"Skipping PR {pr_number}.")
            return
        else:
            console.print(f"Computing coverage for PR {pr_number}...")
            patch_coverage.compute_patch_coverage()

        console.print(
            f"Patch Coverage (%): {patch_coverage.patch_coverage_percentage}")

        if patch_coverage.patch_coverage_percentage is not None and \
            not np.isnan(patch_coverage.patch_coverage_percentage) and \
                int(patch_coverage.patch_coverage_percentage) == 100:
            # remove the image
            console.print(f"Removing Docker image for PR {pr_number}...")
            patch_coverage.remove_image()

        assert patch_coverage.pr_patch.patch_coverage_path.exists(
        ), "Patch coverage file was not created (no .json file in the folder coverage for this PR)."

        console.print(f"Processed PR {pr_number} successfully.")

    except Exception as e:
        console.print(f"Error processing PR {pr_number}: {e}")


def compute_coverage_main(pr_list, repo, output_dir, workers, max_prs):
    console.print(f"Starting coverage computation for repository {repo}")

    with open(pr_list, 'r') as file:
        pr_numbers = sorted([line.strip() for line in file.readlines()])

    # reverse the order of PR numbers
    pr_numbers.reverse()

    if max_prs is not None:
        pr_numbers = pr_numbers[:max_prs]

    if workers == 1:
        console.print("Running in single-threaded mode...")
        for pr_number in pr_numbers:
            compute_regression_patch_coverage(pr_number, repo, output_dir)
    else:
        console.print(
            f"Running in multi-threaded mode with {workers} workers...")
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(
                    compute_regression_patch_coverage,
                    pr_number, repo, output_dir)
                for pr_number in pr_numbers]
            for future in futures:
                future.result()

    console.print(f"Coverage computation completed for repository {repo}")


@click.command()
@click.option('--pr_list', required=True, type=click.Path(exists=True),
              help='Path to the PR list file.')
@click.option('--repo', required=True, type=str,
              help='Repository information in the format owner/repo.')
@click.option('--output_dir', required=True, type=click.Path(),
              help='Path to the output directory.')
@click.option('--workers', default=1, type=int,
              help='Number of parallel workers.')
@click.option('--max_prs', default=None, type=int,
              help='Maximum number of PRs to process.')
def compute_coverage(pr_list, repo, output_dir, workers, max_prs):
    repo_name = repo.split('/')[1]
    output_dir = os.path.join(output_dir, repo_name)
    compute_coverage_main(pr_list, repo, output_dir, workers, max_prs)


if __name__ == '__main__':
    compute_coverage()
