"""
This script implements a command-line interface (CLI) tool that performs the following tasks:

1. Input Parameters:
    - `--repository`: The GitHub repository in the format `owner/repo` (e.g., `Qiskit/qiskit`).
    - `--project_name`: The project name (e.g., `qiskit`).
    - `--github_token_path`: The path to the file containing the GitHub API token for authentication.
    - `--output_folder`: The folder where the results will be stored.
    - `--num_prs`: The number of latest pull requests to retrieve (default: 100).

2. Query GitHub API:
    - Use the GitHub GraphQL API to retrieve the latest 100 pull requests (PRs) from the specified repository.
    - Extract the PR number, title, and status for each PR.

3. Create Output Directory:
    - Create a directory structure based on the project name (e.g., `output_folder/qiskit/diffs`).

4. Download PR Diffs:
    - For each PR, download the diff file from the URL `https://github.com/<repository>/pull/<pr_number>.diff`.
    - Save each downloaded diff file in the `diffs` folder with the filename `<pr_number>.diff`.

5. Filter PRs:
    - Iterate over the downloaded diff files using the `unidiff` library.
    - Keep only those PRs that:
        - Modify a maximum of 3 files.
        - Modify only Python files (files with the `.py` extension).
        - Include at least one `.py` file.

6. Output:
    - Save the filtered list of PR numbers to a text file in the output folder with the name `pr_list_filtered.txt`, one PR number per line.

Additional Requirements:
    - Retry if API limit is reached, wait 30 seconds before retrying, with a maximum of 3 retries.
    - Log the tool's actions and any errors encountered during execution.

    Example Usage:
        To use this script via the command line, you can run the following command:

        ```bash
        python -m approach.scoping.pr_selection --repository Qiskit/qiskit --project_name qiskit --github_token_path /path/to/github_token.txt --output_folder /path/to/output_folder
        ```
"""
import os
import time
import requests
import click
import yaml
from pathlib import Path
from typing import List, Dict, Any
from rich.console import Console
from unidiff import PatchSet
from approach.scoping.spot_code_difference import (
    has_only_documentation_changes
)
from approach.base.pr_patch import PRPatch

console = Console(color_system=None)


@click.command()
@click.option('--config', required=True,
              help='Path to the YAML configuration file.')
@click.option('--benchmark_projects', default=None,
              help='Comma-separated list of projects to override the benchmark_projects in the config file.')
def main(config: str, benchmark_projects: str) -> None:
    with open(config, 'r') as file:
        config_data = yaml.safe_load(file)

    # Override benchmark_projects if provided via CLI
    if benchmark_projects:
        config_data['benchmark_projects'] = benchmark_projects.split(',')

    benchmark_projects = config_data.get('benchmark_projects', [])
    github_token_path = config_data['github_token_path']
    output_folder = config_data['output_folder']
    projects_config = config_data['projects_config']

    for project in benchmark_projects:
        project_config = projects_config.get(project, {})
        if not project_config:
            console.log(f"Skipping unknown project: {project}")
            continue

        process_pull_requests(
            repository=project, project_name=project_config['project_name'],
            github_token_path=github_token_path, output_folder=output_folder,
            num_prs=project_config['num_prs'],
            target_pr_state=project_config.get('pr_state', 'all'),
            exclude_title_keywords=project_config.get(
                'exclude_title_keywords', []),
            exclude_paths=project_config.get('exclude_paths', []),
            exclude_labels=project_config.get('exclude_labels', [])
        )


def process_pull_requests(
        repository: str, project_name: str, github_token_path: str,
        output_folder: str, num_prs: int, target_pr_state: str,
        exclude_title_keywords: List[str],
        exclude_paths: List[str],
        exclude_labels: List[str]) -> None:
    github_token = read_github_token(github_token_path=github_token_path)
    print(f"Using GitHub token from {github_token_path}: {github_token[:6]}")
    pull_requests = get_latest_prs(
        token=github_token, repo=repository, num_prs=num_prs)

    diffs_folder = create_output_directory(
        output_folder=output_folder, project_name=project_name)
    base_dir = Path(output_folder) / project_name

    failed_to_download = download_pr_diffs(
        pull_requests=pull_requests, repository=repository,
        diffs_folder=diffs_folder, token=github_token)

    lowercase_exclude_labels = [
        label.lower() for label in exclude_labels] if exclude_labels else []

    for pr in pull_requests:
        pr_number = pr['node']['number']
        pr_patch = PRPatch(
            repo_owner=repository.split('/')[0],
            repo_name=repository.split('/')[1],
            pr_number=pr_number,
            base_dir=str(base_dir)
        )
        # FILTER BASED ON DIFF DOWNLOAD SUCCESS
        if pr_number in failed_to_download:
            console.log(
                f"Failed to download diff for PR {pr_number}, skipping further processing.")
            pr_patch.log_exclusion_reason(
                "Failed to download diff file.", level=0)
            continue
        # FILTER BASED ON PR STATE
        pr_status = pr['node']['state'].lower()
        if target_pr_state.lower() != 'all' and \
                pr_status != target_pr_state.lower():
            console.log(
                f"Skipping PR {pr_number} with state {pr_status}, "
                f"target state is {target_pr_state}.")
            pr_patch.log_exclusion_reason(
                f"PR state is {pr_status}, not {target_pr_state}.", level=1)
            continue
        # FILTER BASED ON TITLE KEYWORDS
        pr_title = pr['node']['title'].lower()
        if any(
                keyword.lower() in pr_title
                for keyword in exclude_title_keywords):
            console.log(
                f"Skipping PR {pr_number}, title contains excluded keywords.")
            all_forbidden_keywords_present = [
                keyword for keyword in exclude_title_keywords
                if keyword.lower() in pr_title]
            forbidden_keywords_serialized = ', '.join(
                sorted(all_forbidden_keywords_present))
            pr_patch.log_exclusion_reason(
                f"PR title contains excluded keywords. {forbidden_keywords_serialized}", level=2)
            continue
        # FILTER BASED ON LABELS
        pr_labels = [label['name'] for label in pr['node']['labels']['nodes']]
        lowercase_pr_labels = [label.lower() for label in pr_labels]
        overlapping_labels = set(
            lowercase_exclude_labels).intersection(set(lowercase_pr_labels))
        if len(overlapping_labels) > 0:
            console.log(
                f"Skipping PR {pr_number}, it has excluded labels.")
            forbidden_labels_serialized = ', '.join(
                sorted(overlapping_labels))
            pr_patch.log_exclusion_reason(
                f"PR has excluded labels: {forbidden_labels_serialized}",
                level=3)
            continue

    filtered_pr_numbers = filter_prs_based_on_content(
        diffs_folder=diffs_folder,
        repository=repository,
        exclude_paths=exclude_paths
    )
    save_filtered_pr_numbers(
        filtered_pr_numbers=filtered_pr_numbers,
        project_name=project_name,
        output_folder=output_folder)


def read_github_token(github_token_path: str) -> str:
    with open(github_token_path, 'r') as file:
        return file.read().strip()


def filter_prs_by_state_and_title(
        pr_edges: List[Dict[str, Any]],
        pr_state: str, exclude_title_keywords: List[str]) -> List[
        Dict[str, Any]]:
    """
    Filters PRs based on their state and title keywords.
    If pr_state is 'all', no filtering is done on state.
    """
    # Filter by state if pr_state is not 'all'
    if pr_state.lower() != 'all':
        prs_by_state = [
            pr for pr in pr_edges
            if pr['node']['state'].lower() == pr_state.lower()
        ]
    else:
        prs_by_state = pr_edges

    # Filter out PRs whose title contains any of the exclude keywords
    prs_filtered = [
        pr for pr in prs_by_state
        if not any(
            keyword.lower() in pr['node']['title'].lower()
            for keyword in exclude_title_keywords
        )
    ]
    return prs_filtered


def filter_prs_by_paths(
        modified_files: List[str],
        exclude_paths: List[str]) -> bool:
    """
    Checks if any of the modified files match the exclude paths.
    """
    for file in modified_files:
        if any(exclude_path in file for exclude_path in exclude_paths):
            return True
    return False


def get_latest_prs(
        token: str, repo: str, num_prs: int = 100
) -> List[Dict[str, Any]]:
    """
    Fetch up to `num_prs` of the most recent pull requests from GitHub using
    cursor-based pagination. Returns a list of edges, each containing a 'node'
    with PR information (number, title, state).
    """
    url = "https://api.github.com/graphql"
    headers = {"Authorization": f"Bearer {token}"}

    repo_owner, repo_name = repo.split("/")
    pr_edges: List[Dict[str, Any]] = []
    has_next_page = True
    end_cursor = None
    remaining = num_prs

    console.log(
        f"Fetching {num_prs} PRs from {repo}...")

    while has_next_page and remaining > 0:
        page_size = min(100, remaining)

        query = """
        query ($owner: String!, $name: String!, $pageSize: Int!, $after: String) {
          repository(owner: $owner, name: $name) {
            pullRequests(
              first: $pageSize,
              orderBy: { field: CREATED_AT, direction: DESC },
              after: $after
            ) {
              edges {
                node {
                  number
                  title
                  state
                  labels(first: 10) {
                    nodes {
                    name
                    }
                  }
                }
              }
              pageInfo {
                endCursor
                hasNextPage
              }
            }
          }
        }
        """

        variables = {
            "owner": repo_owner,
            "name": repo_name,
            "pageSize": page_size,
            "after": end_cursor
        }

        response = requests.post(
            url, json={"query": query, "variables": variables},
            headers=headers)
        if response.status_code != 200:
            raise Exception(
                f"Query failed with code {response.status_code}: {response.text}")

        data = response.json()["data"]["repository"]["pullRequests"]
        edges = data["edges"]

        pr_edges.extend(edges)
        remaining -= len(edges)
        has_next_page = data["pageInfo"]["hasNextPage"]
        end_cursor = data["pageInfo"]["endCursor"]

    console.log(f"Fetched {len(pr_edges)} PRs from {repo}.")
    return pr_edges


def create_output_directory(output_folder: str, project_name: str) -> Path:
    diffs_folder = Path(output_folder) / project_name / 'diffs'
    diffs_folder.mkdir(parents=True, exist_ok=True)
    return diffs_folder


def get_pull_diff_v3(owner, repo, pull_number, token):
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pull_number}"
    headers = {
        "Accept": "application/vnd.github.v3.diff",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",        # optional but future-proof
    }

    while True:
        response = requests.get(url, headers=headers)
        response_header = response.headers.get('X-RateLimit-Remaining', 0)
        print(f"Rate limit remaining: {response_header}")

        if response.status_code == 200:
            return response.text
        elif response.status_code == 403 and 'Retry-After' in response.headers:
            retry_after = int(response.headers['Retry-After'])
            print(f"Rate limited. Waiting for {retry_after} seconds...")
            time.sleep(retry_after)
        elif response.status_code == 406 and "the diff exceeded the maximum number of lines" in response.text:
            print(f"Diff too large for PR {pull_number}. Skipping...")
            response.raise_for_status()
        else:
            response.raise_for_status()


def download_pr_diffs(
        pull_requests: List[Dict[str, Any]],
        repository: str, diffs_folder: Path, token: str) -> List[int]:

    failed_to_download = []
    for pr in pull_requests:
        pr_number = pr['node']['number']
        diff_file_path = diffs_folder / f'{pr_number}.diff'
        if diff_file_path.exists():
            console.log(f"Skipping PR {pr_number}, diff file already exists.")
            continue
        try:
            diff_content = get_pull_diff_v3(
                owner=repository.split('/')[0],
                repo=repository.split('/')[1],
                pull_number=pr_number,
                token=token
            )
        except Exception as e:
            console.log(
                f"Failed to download diff for PR {pr_number}: {e}")
            failed_to_download.append(pr_number)
            continue
        with open(diff_file_path, 'w') as diff_file:
            diff_file.write(diff_content)
        console.log(f"Downloaded diff for PR {pr_number} to {diff_file_path}")

    return failed_to_download


def filter_prs_based_on_content(
        diffs_folder: Path,
        repository: str,
        exclude_paths: List[str]
) -> List[int]:
    """
    Filters PRs based on multiple criteria to select suitable candidates for analysis.

    Filtering criteria applied in order:
        1. Skip PRs with unparseable diff files
        2. Skip PRs that modify excluded paths (from config)
        3. Skip PRs with no Python files
        4. Limit to PRs modifying a maximum of 5 Python files
        5. Ensure at least one non-test Python file exists
        6. Skip PRs with only documentation changes
        7. Final validation - ensure PRPatch can be created and file contents downloaded
        Args:
            diffs_folder (Path): Directory containing .diff files for PRs
            repository (str): Repository name in format "owner/repo"
            exclude_paths (List[str]): List of file paths to exclude from analysis
        Returns:
            List[int]: List of PR numbers that pass all filtering criteria
        Raises:
            Exception: Logs errors for individual PRs but continues processing others
    """
    filtered_pr_numbers = []
    for diff_file_path in diffs_folder.glob('*.diff'):
        pr_number = int(diff_file_path.stem)
        base_dir = Path(diffs_folder).parent
        console.log(
            f"Checking content PR {pr_number} from {diff_file_path}")
        try:
            pr_patch = PRPatch(
                repo_owner=repository.split('/')[0],
                repo_name=repository.split('/')[1],
                pr_number=pr_number,
                base_dir=str(base_dir)
            )
            pr_patch_touched_files = pr_patch.touched_files
            pr_file_list_after_patch = pr_patch.file_list_after
        except Exception as e:
            # Filter: Skip PRs with unparseable diff files
            console.log(f"Error parsing diff file {diff_file_path}: {e}")
            pr_patch.log_exclusion_reason(
                "Failure while parsing diff and "
                "getting list of touched files.",
                level=10)
            continue

        # Filter: Skip PRs that modify excluded paths (from config)
        if filter_prs_by_paths(pr_patch_touched_files, exclude_paths):
            console.log(
                f"Skipping PR {pr_number}, it touches excluded paths.")
            pr_patch.log_exclusion_reason(
                "PR touches files in excluded paths.",
                level=11)
            continue

        # Categorize modified files by type
        modified_python_files = [
            file for file in pr_file_list_after_patch
            if file.endswith('.py')]
        # Filter out test files - 'file' is the full path, check if "test" is
        # anywhere in path
        not_test_python_files = [
            file for file in modified_python_files
            if 'test_' not in file]

        if len(modified_python_files) == 0:
            console.log(
                f"Skipping PR {pr_number}, it has no Python files.")
            pr_patch.log_exclusion_reason(
                "PR has no Python files.", level=12)
            continue

        # Filter: Limit to PRs modifying a maximum of 5 files
        if len(modified_python_files) > 5:
            console.log(
                f"Skipping PR {pr_number}, it modifies more than 5 files.")
            pr_patch.log_exclusion_reason(
                "PR modifies more than 5 files python files.", level=13)
            continue

        # Filter: Ensure at least one non-test Python file exists
        if len(not_test_python_files) == 0:
            console.log(
                f"Skipping PR {pr_number}, it has no non-test Python files.")
            pr_patch.log_exclusion_reason(
                "PR has only testing Python files.", level=14)
            continue

        # Filter: Ensure that there is some modified or added content
        if pr_patch.has_only_deletion_changes_on_these_files(
                not_test_python_files):
            console.log(
                f"Skipping PR {pr_number}, it has only deletion changes on non-test Python files.")
            pr_patch.log_exclusion_reason(
                "PR has only deletion changes on non-test Python files.",
                level=15)

        # Filter: content requirements
        try:
            if pr_patch.has_only_documentation_changes():
                # If the PR has only documentation changes, we skip it
                console.log(
                    f"Skipping PR {pr_number}, it has only documentation changes.")
                pr_patch.log_exclusion_reason(
                    "PR has only documentation changes.", level=16)
                continue
        except Exception as e:
            console.log(
                f"Error checking documentation changes for PR {pr_number}: {e}")
            pr_patch.log_exclusion_reason(
                "Failure while checking documentation changes (likely AST parsing problem).",
                level=16)
            continue

        try:
            # Filter 6: Final validation - ensure we can download content
            pr_patch.download_all_file_contents()
            # PR passes all filters - add to final list
            filtered_pr_numbers.append(pr_number)
            console.log(
                f"PR {pr_number} passed all filters and is included for further analysis.")
        except Exception as e:
            console.log(
                f"Failed to create PRPatch or download content for PR {pr_number}: {e}")
            pr_patch.log_exclusion_reason(
                "Failure while creating PRPatch or downloading file contents.",
                level=17)
            continue

    return filtered_pr_numbers


def save_filtered_pr_numbers(
        filtered_pr_numbers: List[int],
        project_name: str,
        output_folder: str) -> None:
    filtered_pr_list_path = Path(
        output_folder) / project_name / 'pr_list_filtered.txt'
    with open(filtered_pr_list_path, 'w') as file:
        for pr_number in sorted(filtered_pr_numbers):
            file.write(f'{pr_number}\n')


if __name__ == '__main__':
    main()
