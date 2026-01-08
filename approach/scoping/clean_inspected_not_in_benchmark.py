import json
import os
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional
import click
from rich.console import Console

"""
### Task Description

**Objective**: Implement a command-line interface (CLI) script that processes a benchmark file and a project folder to identify and remove specific Docker images.

**Requirements**:

1. **Input Parameters**:
    - `--repo`: The repository name (e.g., `Qiskit/qiskit`).
    - `--data_folder`: The path to the project folder containing `pr_inspected.txt`.
    - `--benchmark_file`: The path to the benchmark file (e.g.,

v001.json

).
    - `--dry_run`: A flag to indicate whether to only print the actions without executing them.

2. **Functionality**:
    - Read the benchmark file (e.g.,

v001.json

).
    - Extract the list of PR numbers for the given repository.
    - Read the `pr_inspected.txt` file from the specified project folder.
    - Identify PR numbers that are in `pr_inspected.txt` but not in the benchmark file.
    - Print the identified PR numbers.
    - Print messages for missing PRs.
    - Remove Docker images with the format `repo_name-pr-PR_NUMBER` and `repo_name-pr-PR_NUMBER-custom` for the identified PR numbers.
    - If `--dry_run` is specified, print whether the given PR is kept because it is in the benchmark or removed.

3. **Output**:
    - In normal mode, print the identified PR numbers and the Docker images being removed.
    - In dry run mode, print the identified PR numbers and whether the Docker images would be kept or removed.

4. **Error Handling**:
    - Handle missing or invalid PR numbers in `pr_inspected.txt`.
    - Handle missing files or directories gracefully.
    - Handle Docker image removal errors and print appropriate error messages.

**Example Usage**:
```sh
python -m approach.scoping.clean_inspected_not_in_benchmark --repo Qiskit/qiskit --data_folder /home/MYID/projects/PROJECT_PARENT/compiler-pr-analysis/data/test_augmentation/005/qiskit --benchmark_file /home/MYID/projects/PROJECT_PARENT/compiler-pr-analysis/config/benchmark/v001.json --dry_run
```

**Implementation Notes**:
- Use Python for the script.
- Use the `json` module to parse the benchmark file.
- Use the `os` and `subprocess` modules to handle file operations and Docker commands.
- Ensure the script is well-documented and includes error handling.


# Style
- use subfunctions appropriately
- each function has at maximum 7 lines of code of content, break them to smaller functions otherwise
- avoid function with a single line which is a function call
- always use named arguments when calling a function
    (except for standard library functions)
- keep the style consistent to pep8 (max 80 char)
- to print the logs it uses the console from Rich library
- make sure to have docstring for each subfunction and keep it brief to the point
(also avoid comments on top of the functions)
- it uses pathlib every time that paths are checked, created or composed.
- use type annotations with typing List, Dict, Any, Tuple, Optional as appropriate
- make sure that any output folder exists before storing file in it, otherwise create it.


Convert the function above into a click v8 interface in Python.
- map all the arguments to a corresponding option (in click) which is required
- add all the default values of the arguments as default of the click options
- use only underscores
- add a main with the command
- add the required imports
Make sure to add a function and call that function only in the main cli command.
The goal is to be able to import that function also from other files.

# Example usage:
# python -m approach.scoping.clean_inspected_not_in_benchmark --repo Qiskit/qiskit --data_folder data/test_augmentation/005/qiskit --benchmark_file config/benchmark/v001.json --dry_run

"""
console = Console(color_system=None)


def read_json_file(file_path: Path) -> Dict[str, Any]:
    """Read and parse a JSON file."""
    with file_path.open('r') as file:
        return json.load(file)


def read_pr_inspected(file_path: Path) -> List[int]:
    """Read PR numbers from pr_inspected.txt."""
    with file_path.open('r') as file:
        return [int(line.strip()) for line in file if line.strip()]


def get_pr_numbers_from_benchmark(
        benchmark_data: Dict[str, Any],
        repo: str) -> List[int]:
    """Extract PR numbers for the given repository from the benchmark data."""
    projects_data = benchmark_data.get('projects', {})
    current_porject = projects_data.get(repo, {})
    pr_numbers = current_porject.get("pr_numbers", [])
    if not pr_numbers:
        console.print(f"No PR numbers found for repository {repo}")
        raise ValueError(
            f"No PR numbers found for repository {repo} in the benchmark file: {benchmark_data}")
    return [int(pr) for pr in pr_numbers]


def identify_missing_prs(
        inspected_prs: List[int],
        benchmark_prs: List[int]) -> List[int]:
    """Identify PR numbers that are in pr_inspected.txt but not in the benchmark file."""
    print("inspected_prs", inspected_prs)
    print("benchmark_prs", benchmark_prs)
    return [pr for pr in inspected_prs if pr not in benchmark_prs]


def image_exists(image_name: str) -> bool:
    """Check if a Docker image exists."""
    result = subprocess.run(
        ['docker', 'images', '-q', image_name],
        capture_output=True, text=True)
    return bool(result.stdout.strip())


def remove_docker_images(
        repo: str, pr_numbers: List[str],
        dry_run: bool) -> None:
    """Remove Docker images for the identified PR numbers."""
    repo_name = repo.split('/')[1]
    for pr in pr_numbers:
        for suffix in ['', '-custom']:
            image_name = f"{repo_name}-pr-{pr}{suffix}"
            if dry_run:
                console.print(f"Would remove Docker image: {image_name}")
            else:
                if image_exists(image_name):
                    try:
                        subprocess.run(
                            ['docker', 'rmi', image_name],
                            check=True)
                        console.print(f"Removed Docker image: {image_name}")
                    except subprocess.CalledProcessError as e:
                        console.print(
                            f"Error removing Docker image {image_name}: {e}")
                else:
                    console.print(f"Docker image {image_name} does not exist")


@click.command()
@click.option('--repo', required=True,
              help='The repository name (e.g., Qiskit/qiskit).')
@click.option(
    '--data_folder', required=True, type=click.Path(exists=True),
    help='The path to the project folder containing pr_inspected.txt.')
@click.option(
    '--benchmark_file', required=True, type=click.Path(exists=True),
    help='The path to the benchmark file (e.g., v001.json).')
@click.option('--dry_run', is_flag=True,
              help='Flag to indicate whether to only print the actions without executing them.')
def main(
        repo: str,
        data_folder: str,
        benchmark_file: str,
        dry_run: bool) -> None:
    """Main function to process the benchmark file and project folder."""
    data_folder_path = Path(data_folder)
    benchmark_file_path = Path(benchmark_file)

    benchmark_data = read_json_file(benchmark_file_path)
    inspected_prs = read_pr_inspected(data_folder_path / 'pr_inspected.txt')
    benchmark_prs = get_pr_numbers_from_benchmark(benchmark_data, repo)
    missing_prs = identify_missing_prs(inspected_prs, benchmark_prs)

    console.print(f"Identified PRs not in benchmark: {missing_prs}")
    remove_docker_images(repo, missing_prs, dry_run)


if __name__ == '__main__':
    main()
