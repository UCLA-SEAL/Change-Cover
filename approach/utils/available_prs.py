import os
import re
import numpy as np
from rich.console import Console
from typing import List, Dict, Any
from pathlib import Path
import requests

from concurrent.futures import ThreadPoolExecutor, as_completed
from rich.progress import track

from approach.base.pr_patch import PRPatch

from approach.coverage.patch_coverage import (
    PatchCoverage,
    flatten_coverage_datapoint
)

console = Console(color_system=None)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
if GITHUB_TOKEN is None:
    console.log("GITHUB_TOKEN not set. Please set it in your environment.")
    response = console.input(
        "Would you like to look for the token in 'secrets/github_token.txt'? (yes/no): ")
    if response.strip().lower() == "yes":
        token_path = Path("secrets/github_token.txt")
        if token_path.exists():
            GITHUB_TOKEN = token_path.read_text().strip()
            if GITHUB_TOKEN:
                console.log(
                    "Loaded GITHUB_TOKEN from secrets/github_token.txt.")
                os.environ["GITHUB_TOKEN"] = GITHUB_TOKEN
            else:
                console.log("secrets/github_token.txt is empty.")
                exit(1)
        else:
            console.log("secrets/github_token.txt not found.")
            exit(1)
    else:
        console.log("GITHUB_TOKEN is required to proceed.")
        exit(1)

# Query github on the state of the PR


def query_github_pr(repo_name: str, pr_number: int) -> Dict[str, Any]:
    """Query github for the PR."""
    url = f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error: {response.status_code}")
        return {}


def query_github_pr_is_merged(repo_name: str, pr_number: int) -> bool:
    """Check if the PR is merged."""
    pr_data = query_github_pr(repo_name, pr_number)
    return pr_data.get('merged', False)


def filter_available_prs(
    repo_owner,
    repo_name,
    base_dir,
    pr_list
):
    records = []

    prs: List[PRPatch] = [
        PRPatch(
            repo_owner=repo_owner,
            repo_name=repo_name,
            pr_number=int(pr_number),
            base_dir=Path(base_dir) / repo_name
        )
        for pr_number in pr_list
    ]

    pc_list: List[PatchCoverage] = [
        PatchCoverage(pr_patch=pr) for pr in prs]

    # filter out PRs that are OPEN or CLOSED
    # We should only keep docker images of PRs that are MERGED,
    # but just in case we filter again here
    pc_merged = [pc for pc in pc_list if query_github_pr_is_merged(
        f"{repo_owner}/{repo_name}", pc.pr_patch.pr_number)]
    console.log(f"Number of PRs merged: {len(pc_merged)}")

    pc_with_images = []
    with ThreadPoolExecutor(max_workers=32) as tp:
        future_to_pc = {tp.submit(pc._is_execution_environment_ready): pc
                        for pc in pc_merged}
        for fut in track(as_completed(future_to_pc),
                         total=len(future_to_pc),
                         description="Checking each PR has docker image…"):
            if fut.result():
                pc_with_images.append(future_to_pc[fut])

    console.log(f"PRs with execution environment: {len(pc_with_images)}")

    pc_not_100 = []
    for pc in pc_with_images:
        try:
            coverage = pc.patch_coverage_percentage
            if coverage != 100 and not np.isnan(coverage):
                pc_not_100.append(pc)
        except Exception as e:
            console.log(
                f"Error getting coverage for PR {pc.pr_patch.pr_number}: {e}")
            continue
    console.log(
        f"PRs with NOT full patch coverage (!= 100%): {len(pc_not_100)}")

    for pc in pc_not_100:
        cov_data = pc.patch_coverage_data
        flat_cov_data = flatten_coverage_datapoint(cov_data)
        uncovered_lines = [line for line in flat_cov_data
                           if line.endswith(":m")]
        # filter out uncovered lines in test files
        uncovered_lines = [
            line for line in uncovered_lines
            if not re.search(r"test", line)]

        patch_coverage_value = pc.patch_coverage_percentage
        # this ensures that we have the summaries
        summary = pc.pr_patch.uncovered_lines_summary

        records.append({
            "repo": repo_name,
            "pr_number": pc.pr_patch.pr_number,
            "patch_coverage": patch_coverage_value,
            "uncovered_lines": uncovered_lines,
            "n_uncovered_lines": len(uncovered_lines),
            "summary": summary
        })

    return pc_not_100


def available_prs(repo_owner: str, repo_name: str, base_dir: str) -> None:

    PATH_PR_LIST = Path(base_dir, repo_name, "pr_list_filtered.txt")

    if not os.path.exists(PATH_PR_LIST):
        console.log(f"PR list not found for {repo_owner}/{repo_name}.")
        exit(1)

    pr_list = PATH_PR_LIST.read_text().strip().split("\n")
    console.log(f"Reading PRs from {PATH_PR_LIST}, found {len(pr_list)} PRs")

    pr_patches = filter_available_prs(
        repo_owner=repo_owner,
        repo_name=repo_name,
        base_dir=base_dir,
        pr_list=pr_list
    )

    return [pr_patch.pr_patch.pr_number for pr_patch in pr_patches]
