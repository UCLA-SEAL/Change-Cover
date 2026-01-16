#!/usr/bin/env python
# coding: utf-8

"""
Test Review Report Generator

This script generates test review reports for pull requests by:
1. Loading PR information and test data
2. Filtering tests that pass and add coverage
3. Clustering and ranking tests by coverage
4. Selecting the best test from each cluster using LLM
5. Generating review reports with PR context and test summaries
"""

import click
import yaml
import json
import os
import re
import sys
import glob
import time
import requests
from pathlib import Path
from collections import defaultdict
from typing import List, Tuple, Dict, Any, Optional

import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
from tqdm.auto import tqdm
from pandarallel import pandarallel
from rich.console import Console
import dspy

from approach.coverage.formatter import concatenate_files
from approach.base.pr_patch import PRPatch
from approach.utils.token_logger import LLMTokenLogger
from approach.utils.time_logger import TimeLogger

console = Console(color_system=None)


# Configuration and Setup Functions
def load_config(config_path: str) -> dict:
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    # Set up the environment based on the config
    setup_environment(config)
    # Flatten/normalize config for easy access
    config_flat = {}
    bench_projects = config.get('benchmark_projects', [None])
    if bench_projects:
        config_flat['repo_name'] = bench_projects[0]
    else:
        config_flat['repo_name'] = config.get('repository')
    if config_flat['repo_name']:
        config_flat['project_name'] = config_flat['repo_name'].split('/')[-1]
    else:
        config_flat['project_name'] = None
    config_flat['artifact_folder'] = config.get('base_dir')
    config_flat['generator'] = config.get('test_folder_name')
    config_flat['review_version'] = '004'  # or from config if present
    test_gen = config.get('test_generator', {})
    config_flat['model_name'] = test_gen.get('model_name')
    kwargs = test_gen.get('kwargs', {})
    config_flat['temperature'] = kwargs.get('temperature', 0.0)
    config_flat['exclude_prs'] = []  # can be extended if needed
    rv = config_flat['review_version']
    pn = config_flat['project_name']
    config_flat['review_folder'] = (
        f"../../../reviews/reviews/{rv}/{pn}"
    )
    return config_flat


def setup_environment(config):
    import os
    from pathlib import Path
    # Set up API keys if present
    api_keys = config.get('api_keys', {})
    if 'GEMINI_API_KEY' in api_keys:
        gemini_token = Path(api_keys['GEMINI_API_KEY']).read_text().strip()
        os.environ['GEMINI_API_KEY'] = gemini_token
    if 'OPENAI_API_KEY' in api_keys:
        openai_token = Path(api_keys['OPENAI_API_KEY']).read_text().strip()
        os.environ['OPENAI_API_KEY'] = openai_token
    # ...any other env setup...


# Data Loading Functions
def load_pr_information(pr_list: List[str], repo_name: str,
                        artifact_folder: str) -> List[PRPatch]:
    """Load PR information for the given PR list."""
    prs: List[PRPatch] = [
        PRPatch(
            repo_owner=repo_name.split("/")[0],
            repo_name=repo_name.split("/")[1],
            pr_number=int(pr_number),
            base_dir=artifact_folder
        )
        for pr_number in pr_list
    ]
    return prs


def load_test_data(folder: str, pr_list: List[int],
                   pattern: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Reads test files, runtime logs, and coverage increments into a nested dictionary.
    TEST_DATA[pr_number] = list of test records (dict).

    Each test record contains:
        - test_name: str
        - test_content: str
        - runtime_log: str or None
        - coverage_increment: dict or None
    """
    test_data = {}

    for pr in pr_list:
        pr_dir = Path(folder) / str(pr)
        if not pr_dir.exists():
            console.log(
                f"WARNING: PR dir {pr_dir} does not exist, skipping...")
            continue

        test_data.setdefault(str(pr), [])
        test_paths = sorted(pr_dir.glob("test_*.py"))

        if pattern:
            test_paths = [p for p in test_paths if re.search(pattern, p.name)]

        for test_path in test_paths:
            test_name = test_path.stem
            is_integrated_test: bool = re.search(r"_integrated", test_name)

            # Skip if test_path is not a regular file
            if not test_path.is_file():
                console.log(
                    f"WARNING: {test_path} is not a file, skipping...")
                continue

            with open(test_path, "r") as f:
                test_content = f.read()

            runtime_log_path = pr_dir / f"{test_name}_runtime.log"
            if runtime_log_path.exists():
                with open(runtime_log_path, "r") as f:
                    runtime_log_content = f.read()
            else:
                runtime_log_content = None

            coverage_inc_path = pr_dir / f"{test_name}_coverage_increment.json"
            if coverage_inc_path.exists():
                with open(coverage_inc_path, "r") as f:
                    coverage_inc_data = json.load(f)
            else:
                coverage_inc_data = None

            patch_path = pr_dir / \
                f"{test_name.replace('_integrated', '.patch')}"
            if patch_path.exists():
                patch = patch_path.read_text()
            else:
                patch = None
                console.log(f"WARNING: Patch file {patch_path} does not exist")

            test_data[str(pr)].append({
                "test_name": test_name,
                "integrated": bool(is_integrated_test),
                "test_content": test_content,
                "runtime_log": runtime_log_content,
                "coverage_increment": coverage_inc_data,
                "test_patch": patch
            })

    return test_data


# Test Filtering Functions
def split_coverage_line(line: str) -> Tuple[str, int]:
    """
    Split a coverage line into its components.
    e.g.,
    "scipy/signal/_spline_filters.py:594:c" -> ("scipy/signal/_spline_filters.py", 594)
    """
    line_parts = line.split(":")
    if len(line_parts) == 3:
        return (line_parts[0], int(line_parts[1]))
    else:
        console.log(f"WARNING: Unexpected line format: {line}")
        sys.exit(1)


def filter_tests(
        test_data: Dict[str, List[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Filters the tests that are 1) passing, 2) added coverage

    Return a test_data dictionary of the same structure,
    but only with the tests that are passing and added coverage.
    """
    TEST_DATA_FILTERED = {}
    gen_total_tests = 0
    gen_passed = 0
    gen_failed = 0
    gen_skipped = 0
    gen_errored = 0

    gen_all_unique_lines = set()
    gen_all_unique_lines_passing_tests = set()
    coverage_added_pr_count = 0
    coverage_added_pr_count_passing_tests = 0
    total_prs_for_generator = len(test_data)

    for pr_number, test_records in test_data.items():
        pr_covered_lines = set()
        pr_covered_lines_passing_tests = set()
        pr_passed = 0
        pr_failed = 0
        pr_skipped = 0
        pr_errored = 0

        for test_record in test_records:
            lines_increment = set()
            gen_total_tests += 1
            passed_flag = False

            runtime_log = test_record["runtime_log"] or ""
            if "failed" in runtime_log:
                gen_failed += 1
                pr_failed += 1
            elif "skipped" in runtime_log:
                gen_skipped += 1
                pr_skipped += 1
            elif "error" in runtime_log:
                gen_errored += 1
                pr_errored += 1
            elif "passed" in runtime_log:
                gen_passed += 1
                pr_passed += 1
                passed_flag = True
            else:
                console.log(
                    f"WARNING: Unrecognized log for PR={pr_number}, test={test_record['test_name']}")

            coverage_data = test_record.get("coverage_increment", {})
            if coverage_data:
                lines_this_test = coverage_data.get("unique_lines_covered", [])
                lines_this_test = [(split_coverage_line(line)[0],
                                   split_coverage_line(line)[1])
                                   for line in lines_this_test]

                line_missed_by_dev = coverage_data.get(
                    "line_missed_by_dev", [])
                line_missed_by_dev = [
                    (split_coverage_line(line)[0],
                     split_coverage_line(line)[1])
                    for line in line_missed_by_dev]

                lines_increment = set(lines_this_test) & set(
                    line_missed_by_dev)
                lines_increment = {
                    (fp, lineno) for fp, lineno in lines_increment
                    if not re.search(r"test", fp)}

                pr_covered_lines.update(lines_increment)
                if passed_flag:
                    pr_covered_lines_passing_tests.update(lines_increment)

            if passed_flag and len(lines_increment) > 0:
                test_record['lines_increment'] = lines_increment
                TEST_DATA_FILTERED.setdefault(
                    pr_number, []).append(test_record)

        if len(pr_covered_lines) > 0:
            coverage_added_pr_count += 1
        if len(pr_covered_lines_passing_tests) > 0:
            coverage_added_pr_count_passing_tests += 1

        gen_all_unique_lines.update(pr_covered_lines)
        gen_all_unique_lines_passing_tests.update(
            pr_covered_lines_passing_tests)

    generator_pass_rate = (
        gen_passed / gen_total_tests) * 100 if gen_total_tests else 0.0
    generator_unique_lines_covered = len(gen_all_unique_lines)
    generator_unique_lines_passing_tests = len(
        gen_all_unique_lines_passing_tests)

    console.log(f"  - Total tests across all PRs: {gen_total_tests}")
    console.log(
        f"  - Passed: {gen_passed}, Failed: {gen_failed}, Skipped: {gen_skipped}, Errored: {gen_errored}")
    console.log(f"  - Pass Rate (overall): {generator_pass_rate:.1f}%")
    console.log(
        f"  - Total unique lines covered: {generator_unique_lines_covered}")
    console.log(
        f"  - Total unique lines covered by passing tests: {generator_unique_lines_passing_tests}")
    console.log(
        f"  - PRs with coverage added / total PRs: {coverage_added_pr_count}/{total_prs_for_generator}")
    console.log(
        f"  - PRs with coverage added by passing tests / total PRs: {coverage_added_pr_count_passing_tests}/{total_prs_for_generator}")

    return TEST_DATA_FILTERED


# Test Clustering Functions
def cluster_and_rank_tests(
        test_data: Dict[str, List[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
    """For each PR,
    1. Cluster the tests based on their coverage lines.
    2. Rank the clusters based on the number of unique lines covered.

    Return a dictionary:

    {
        "PR_NUMBER": [
            {
                "lines_increment": [
                    ("scipy/signal/_spline_filters.py", 594),
                    ("scipy/signal/_spline_filters.py", 595),
                ],
                "tests": [
                    {test_record_1},
                    {test_record_2},
                    ...
                ]
            }, # Cluster 1
            {
            }, # Cluster 2
        ],
        "PR_NUMBER_2": [],...
    }
    """
    TEST_DATA_CLUSTER = {}

    for pr_number, test_records in test_data.items():
        TEST_DATA_CLUSTER[pr_number] = []
        clusters = {}

        for test_record in test_records:
            coverage_lines = set(test_record["lines_increment"])
            cluster_key = frozenset(coverage_lines)

            if cluster_key not in clusters:
                clusters[cluster_key] = {
                    "lines_increment": list(coverage_lines),
                    "tests": []
                }

            clusters[cluster_key]["tests"].append(test_record)

        sorted_clusters = sorted(
            clusters.values(),
            key=lambda x: len(x["lines_increment"]),
            reverse=True)

        TEST_DATA_CLUSTER[pr_number] = sorted_clusters

    return TEST_DATA_CLUSTER


def remove_cluster_subsets(clustered_test_data:
                           Dict[str, List[Dict[str, Any]]]) -> Dict[str,
                                                                    List[Dict[str, Any]]]:
    """
    Remove clusters that are subsets of other clusters.
    """
    for pr_number, clusters in clustered_test_data.items():
        unique_lines = [set(cluster["lines_increment"])
                        for cluster in clusters]
        to_remove = []

        for i in range(len(unique_lines)):
            for j in range(len(unique_lines)):
                if i != j and unique_lines[i].issubset(unique_lines[j]):
                    to_remove.append(i)

        clustered_test_data[pr_number] = [clusters[i]
                                          for i in range(len(clusters)) if i not in to_remove]

    return clustered_test_data


def sort_clusters_by_lines_covered(
    clustered_test_data:
    Dict[str, List[Dict[str, Any]]]) -> Dict[str,
                                             List[Dict[str, Any]]]:
    """
    Sort the clusters in each PR by the number of unique lines covered.
    """
    for pr_number, clusters in clustered_test_data.items():
        clustered_test_data[pr_number] = sorted(
            clusters, key=lambda x: len(x["lines_increment"]), reverse=True)
    return clustered_test_data


def remove_non_disjoint_clusters(
    clustered_test_data:
    Dict[str, List[Dict[str, Any]]]) -> Dict[str,
                                             List[Dict[str, Any]]]:
    """
    Remove clusters that are not disjoint with any previously seen clusters.
    """
    for pr_number, clusters in clustered_test_data.items():
        seen_lines = set()
        new_clusters = []
        for cluster in clusters:
            lines_increment = set(cluster["lines_increment"])
            if lines_increment.isdisjoint(seen_lines):
                new_clusters.append(cluster)
                seen_lines.update(lines_increment)
        clustered_test_data[pr_number] = new_clusters
    return clustered_test_data


def print_clusters_info(
        clustered_test_data: Dict[str, List[Dict[str, Any]]]) -> None:
    """
    Print the number of clusters per PR and the number of unique lines covered by each cluster.
    """
    for pr_number, clusters in clustered_test_data.items():
        console.log(f"PR {pr_number}: {len(clusters)} clusters")
        for i, cluster in enumerate(clusters):
            console.log(
                f"  Cluster {i + 1}: {len(cluster['lines_increment'])} unique lines covered")
    console.log("")


# LLM Signature Classes
class PickTheBestTest(dspy.Signature):
    """
    Pick the best test from a cluster of tests.
    They are intended to add coverage to the pull request of a specific open-source project.
    The tests haven all been verified to pass and add the same lines of patch coverage.
    Pick the test that is the best, to be submitted to the project.
    Use the following criteria:
    1. The extra test coverage is **worthwhile** to add.
        - Positive Example: a test for a corner case, a developmental feature, which are error-prone. This means the additional tests have a higher chance of catching some regression bugs eventually.
        - Negative Example: a test that adds coverage to a 1-line getter which is unlikely to be buggy
    2. The test is **well integrated** into the existing test suite.
        - Positive Example: the test uses existing fixtures to set up the environment, ensuring consistency and reducing redundancy.
        - Negative Example: the test hardcoded parameters, while other test functions in the context are property-based tests that are parameterized.
    3. The test is **related to** the PR.
        - Positive Example: the PR adds corner case handling in a scipy optimization function. But forgets to test the corner case. The new test is for the corner case.
        - Negative Example: the uncovered lines are formatting changes by the PR. In this case we may need to trace back to the PR that modified or introduced the uncovered line in a meaningful way.`
    """

    pr_context: str = dspy.InputField(desc="Context of the PR")
    pr_diff: str = dspy.InputField(desc="Diff of the PR")
    pr_uncovered_lines: str = dspy.InputField(desc="Uncovered lines in the PR")
    tests: List[Tuple[str, str]] = dspy.InputField(
        desc="List of test names and test content as pairs")
    best_test: str = dspy.OutputField(
        desc="The name of the best test, e.g. test_3")


class TestAdditionPullRequest(dspy.Signature):
    """
    Write a pull request to add a test to a repository (e.g. scipy, pandas).

    The repository had a merged pull request (original PR) that had imperfect patch coverage,
    i.e. some changes were not covered by tests.
    We produced a new test that adds some coverage to the original PR.
    Now we are submitting a new pull request to add this test to the repository.
    Write the title and description of the new pull request. Be concise, 100 words max.
    """

    original_pr_desc: str = dspy.InputField(
        desc="The description of the original PR")
    original_pr_uncovered_lines: str = dspy.InputField(
        desc="The uncovered lines in the original PR")
    new_test: str = dspy.InputField(
        desc="The new test that adds coverage to the original PR")
    new_test_lines_covered: str = dspy.InputField(
        desc="The lines covered by the new test")

    title: str = dspy.OutputField(desc="Title of the pull request")
    description: str = dspy.OutputField(desc="Description of the pull request")


# Test Selection Functions
def configure_dspy_model(model_name: str, temperature: float) -> None:
    """Initialize DSPy model for ranking."""
    lm = dspy.LM(model_name, temperature=temperature, cache=False)
    dspy.settings.configure(lm=lm)


def pick_best_test_from_cluster(pr_number: str, cluster: Dict[str, Any],
                                pr_info_list: List[PRPatch]) -> Dict[str, Any]:
    """
    Use the LLM ranker to pick the best test from a cluster.

    Args:
        pr_number: The PR number
        cluster: The cluster of tests
        pr_info_list: List of PR information objects

    Returns:
        The best test record
    """
    pr_info = None
    for patch in pr_info_list:
        if str(patch.pr_number) == str(pr_number):
            pr_info = patch
            break

    if not pr_info:
        raise ValueError(f"PR {pr_number} not found in PR_INFO")

    tests = []
    for test_record in cluster['tests']:
        test_name = test_record['test_name']
        tests.append((test_name, test_record['test_patch']))

    try:
        predictor = dspy.Predict(PickTheBestTest)
        result = predictor(
            pr_context=pr_info.augmented_discussion.summary,
            pr_diff=pr_info.diff,
            pr_uncovered_lines=pr_info.uncovered_lines_summary,
            tests=tests
        )

        best_test_name = result.best_test
        for test_record in cluster['tests']:
            if test_record['test_name'] == best_test_name:
                return test_record

        return cluster['tests'][0]
    except Exception as e:
        raise e


def pick_best_tests(test_data_cluster: Dict[str, List[Dict[str, Any]]],
                    pr_info_list: List[PRPatch],
                    base_dir: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    For each PR and each cluster, pick the best test.

    Args:
        test_data_cluster: The clustered test data
        pr_info_list: List of PR information objects

    Returns:
        A dictionary mapping PR numbers to the best test for each cluster
    """
    best_tests = {}
    pr_numbers = list(test_data_cluster.keys())

    with tqdm(total=len(pr_numbers), desc="Processing PRs") as pbar:
        for pr_number in pr_numbers:
            time_logger = TimeLogger(
                logging_dir=Path(base_dir) / "time" / str(pr_number))
            time_logger.log_event(
                pr_number=pr_number,
                test_id=None,
                event_type="start",
                component="pick_best_tests",
            )
            best_tests[pr_number] = []

            for cluster_idx, cluster in enumerate(
                    test_data_cluster[pr_number]):
                pbar.set_description(
                    f"PR {pr_number}, cluster {cluster_idx + 1}/{len(test_data_cluster[pr_number])}")

                if len(cluster['tests']) == 1:
                    best_test = cluster['tests'][0]
                    token_usage = []
                else:
                    best_test = pick_best_test_from_cluster(
                        pr_number, cluster, pr_info_list)
                    token_logger = LLMTokenLogger()
                    lm = dspy.settings.lm
                    token_logger.log(lm=lm, stage=PickTheBestTest)
                    token_usage = token_logger.get_logs_as_list()

                best_tests[pr_number].append({
                    'cluster_idx': cluster_idx,
                    'lines_increment': cluster['lines_increment'],
                    'best_test': best_test,
                    'token_usage': token_usage
                })

            pbar.update(1)
            time_logger.log_event(
                pr_number=pr_number,
                test_id=None,
                event_type="end",
                component="pick_best_tests",
            )

    return best_tests


# Report Generation Functions
def generate_pr_title_and_description(
        pr_info: PRPatch, test_record: Dict[str, Any]) -> Tuple[str, str]:
    """Invoke the LLM to generate a PR title and description."""
    try:
        predictor = dspy.Predict(TestAdditionPullRequest)
        result = predictor(
            original_pr_desc=pr_info.augmented_discussion.summary,
            original_pr_uncovered_lines=pr_info.uncovered_lines_summary,
            new_test=test_record['test_patch'],
            new_test_lines_covered="\n".join(
                [f"{fp}:{ln}" for fp, ln in test_record['lines_increment']]))
        pr_title = result.title
        pr_description = result.description
    except Exception as e:
        console.log(
            f"Error generating PR title and description for PR {pr_info.pr_number}: {e}")
        raise e
    return pr_title, pr_description


def group_contiguous_lines(lines: List[int]) -> List[Tuple[int, int]]:
    """Group contiguous line numbers into ranges."""
    if not lines:
        return []
    lines = sorted(lines)
    blocks = []
    start = prev = lines[0]
    for line in lines[1:]:
        if line == prev + 1:
            prev = line
        else:
            blocks.append((start, prev))
            start = prev = line
    blocks.append((start, prev))
    return blocks


def get_pr_head_info(owner: str, repo: str,
                     pr_number: str) -> Tuple[str, str, str]:
    """Get PR head information from GitHub API."""
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
    headers = {}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    head_sha = data['head']['sha']
    head_repo_owner = data['head']['repo']['owner']['login']
    head_repo_name = data['head']['repo']['name']
    return head_sha, head_repo_owner, head_repo_name


def make_github_permalinks(owner: str,
                           repo: str,
                           pr_number: str,
                           lines_increment: List[Tuple[str,
                                                       int]]) -> List[Tuple[str,
                                                                            str,
                                                                            str]]:
    """
    Returns: List of (file, block, permalink), sorted by file then block.
    block is 'start-end' or 'start'
    """
    file_lines: Dict[str, List[int]] = defaultdict(list)
    for file_path, line in lines_increment:
        file_lines[file_path].append(line)

    sha, head_owner, head_repo = get_pr_head_info(owner, repo, pr_number)
    permalinks = []

    for file_path, lines in file_lines.items():
        blocks = group_contiguous_lines(lines)
        for start, end in blocks:
            block_str = f"{start}" if start == end else f"{start}-{end}"
            url = (
                f"https://github.com/{head_owner}/{head_repo}/blob/{sha}/{file_path}#L{start}"
                if start == end else
                f"https://github.com/{head_owner}/{head_repo}/blob/{sha}/{file_path}#L{start}-L{end}")
            permalinks.append((file_path, block_str, url))

    permalinks.sort(key=lambda x: (x[0], int(x[1].split('-')[0])))
    return permalinks


def make_github_single_permalink_for_test(
        owner: str, repo: str, pr_number: str, file_path: str) -> str:
    """Create a single permalink for a test file."""
    sha, head_owner, head_repo = get_pr_head_info(owner, repo, pr_number)
    return f"https://github.com/{head_owner}/{head_repo}/blob/{sha}/{file_path}"


def retrieve_pr_info(pr_number: str, pr_info_list: List[PRPatch]) -> PRPatch:
    """Get PR information from the list."""
    pr_info: PRPatch = None
    for patch in pr_info_list:
        if str(patch.pr_number) == str(pr_number):
            pr_info = patch
            break

    if not pr_info:
        raise ValueError(f"PR {pr_number} not found in PR_INFO")

    return pr_info


def format_lines_increment(pr_patch: PRPatch,
                           lines_increment: List[Tuple[str, int]]) -> str:
    """Format lines increment for display."""
    files_lines_increment_dict = {}
    for f, lineno in lines_increment:
        if f not in files_lines_increment_dict:
            files_lines_increment_dict[f] = {}

        if "covered" not in files_lines_increment_dict[f]:
            files_lines_increment_dict[f]["covered"] = [lineno]
        else:
            files_lines_increment_dict[f]["covered"].append(lineno)

    fmt_files = concatenate_files(
        data=files_lines_increment_dict,
        source_dir=pr_patch.after_dir,
        custom_string='#✅ NOW COVERED',
        missed=False,
        context_size=50,
        include_class_definition=False,
        include_function_signature=False,
    )
    return fmt_files


def construct_test_summary_markdown(pr_info: PRPatch, pr_dir: str,
                                    test_record: Dict[str, Any],
                                    cluster_idx: int) -> None:
    """
    Constructs a Markdown summary for each test/cluster
    The markdown should contain:
    - Test summary, what it does, what missing coverage it addresses
    - List of lines incremented by this test
    - Visualization of the lines increment (Link to the file in the PR)
    - Link to file where we add the new test
    """
    cluster_dir = os.path.join(pr_dir, f"test_{cluster_idx}")
    os.makedirs(cluster_dir, exist_ok=True)

    test_patch = test_record['test_patch']
    test_name = test_record['test_name']
    test_patch_path = os.path.join(cluster_dir, f"{test_name}.patch")
    with open(test_patch_path, "w") as f:
        f.write(test_patch)

    test_content_path = os.path.join(cluster_dir, f"{test_name}.py")
    with open(test_content_path, "w") as f:
        f.write(test_record['test_content'])

    try:
        pr_title, pr_desc = generate_pr_title_and_description(
            pr_info, test_record)
        token_logger = LLMTokenLogger()
        lm = dspy.settings.lm
        token_logger.log(lm=lm, stage=TestAdditionPullRequest)
        token_usage = token_logger.get_logs_as_list()
    except Exception as e:
        console.log(
            f"Error generating PR title and description for PR {pr_info.pr_number}: {e}")
        sys.exit(1)

    test_md_lines = [f"## PR Title: {pr_title}",
                     "", f"## PR Description: \n{pr_desc}", ""]

    test_md_lines.append("## Lines Incremented by this Test")

    lines_increment = test_record['lines_increment']
    blk2permalink = make_github_permalinks(
        owner=pr_info.repo_owner,
        repo=pr_info.repo_name,
        pr_number=str(pr_info.pr_number),
        lines_increment=lines_increment
    )
    test_md_lines.append("| File | Block | Permalink |")
    test_md_lines.append("| ---- | ----- | --------- |")
    for fp, blk, link in blk2permalink:
        test_md_lines.append(f"| {fp} | {blk} | [Here]({link}) |")

    content = format_lines_increment(pr_info, lines_increment)
    test_md_lines.append("## Lines Increment Visualization")
    test_md_lines.append("```python")
    test_md_lines.append(content)
    test_md_lines.append("```")

    integrated_test_rel_path = "/".join(test_record["test_content"].splitlines()[
                                        1].strip("# ").split("/")[3:])
    test_file_online_url = make_github_single_permalink_for_test(
        owner=pr_info.repo_owner,
        repo=pr_info.repo_name,
        pr_number=str(pr_info.pr_number),
        file_path=integrated_test_rel_path
    )
    test_md_lines.append("## Test Patch")
    test_md_lines.append("```diff")
    test_md_lines.append(test_record['test_patch'])
    test_md_lines.append("```")

    test_md_lines.append(f"## Fully Integrated Test")
    test_md_lines.append(
        f"The new test is fully integrated into test file `{integrated_test_rel_path}`.")
    test_md_lines.append(f"\nTo view the test file, navigate to `test.py`")
    test_md_lines.append(
        f"\nTo view the test file before new test is added on Github, click [here]({test_file_online_url})")

    if 'runtime_log' in test_record:
        test_md_lines.append("## Test Runtime Log")
        test_md_lines.append("```log")
        test_md_lines.append(test_record['runtime_log'])
        test_md_lines.append("```")

    test_summary_path = os.path.join(cluster_dir, "test_summary.md")
    with open(test_summary_path, "w") as f:
        f.write("\n".join(test_md_lines))

    with open(os.path.join(cluster_dir, "token_usage.json"), "w") as f:
        all_token_usage = []
        all_token_usage.extend(token_usage)
        all_token_usage.extend(test_record.get('token_usage', []))
        data = {
            "token_usage": all_token_usage,
            "pr_number": pr_info.pr_number,
        }
        json.dump(data, f, indent=4)


def save_test_review(test_record: Dict[str, Any], pr_number: str,
                     cluster_idx: int, pr_info_list: List[PRPatch],
                     review_folder: str) -> None:
    """Save test review report."""
    pr_dir = os.path.join(review_folder, str(pr_number))
    os.makedirs(pr_dir, exist_ok=True)

    pr_info: PRPatch = retrieve_pr_info(pr_number, pr_info_list)
    pr_url = f"https://github.com/{pr_info.repo_owner}/{pr_info.repo_name}/pull/{pr_number}"

    md_lines = [f"## [PR {pr_number}]({pr_url})", ""]

    pr_discussion_summary = pr_info.augmented_discussion.summary
    md_lines += ["## PR Summary", "", pr_discussion_summary, ""]

    pr_uncovered_lines = re.sub(
        r"# UNCOVERED",
        r"#❗UNCOVERED: NEED TEST",
        pr_info.uncovered_lines_summary)
    md_lines += ["## Uncovered Lines", "",
                 "```python", pr_uncovered_lines, "```", ""]

    md_lines += ["## PR Diff", "", "```diff", pr_info.diff, "```", ""]

    pr_markdown_path = os.path.join(pr_dir, f"{pr_number}.md")
    with open(pr_markdown_path, "w") as f:
        f.write("\n".join(md_lines))

    construct_test_summary_markdown(pr_info, pr_dir, test_record, cluster_idx)


# Main Processing Function
def generate_reports(config: Dict[str, Any]) -> None:
    """Main function to generate test review reports."""

    # Configuration parameters
    repo_name = config['repo_name']
    artifact_folder = Path(config['artifact_folder'])
    generator = config['generator']
    model_name = config['model_name']
    temperature = config.get('temperature', 0.0)
    exclude_prs = config.get('exclude_prs', [])

    # Set up paths
    review_folder = Path(config['review_folder'])
    review_folder.mkdir(parents=True, exist_ok=True)

    project_name = repo_name.split('/')[-1]
    generator_path = artifact_folder / project_name / "test_cases" / generator

    console.log(f"Review folder: {review_folder}")
    console.log(f"Artifacts folder: {artifact_folder}")
    console.log(f"Repo name: {repo_name}")
    console.log(f"Generator path: {generator_path}")

    # Configure DSPy model
    configure_dspy_model(model_name, temperature)

    # Get PR list
    pr_dirs = glob.glob(os.path.join(generator_path, "[0-9]*"))
    pr_list = [int(os.path.basename(pr_dir)) for pr_dir in pr_dirs]
    pr_list = [pr for pr in pr_list if pr not in exclude_prs]
    pr_list.sort()

    console.log(f"Found {len(pr_list)} PRs in the generator path.")
    console.log(f"After filtering, #PRs: {len(pr_list)}")
    console.log(f"Filtered PRs: {pr_list}")

    # Load PR information
    pr_info = load_pr_information(
        pr_list, repo_name, str(artifact_folder / project_name))

    # Load and process test data
    integrated_test_data = load_test_data(
        str(generator_path), pr_list, pattern=r"test_[0-9]+_integrated.py")

    console.log(
        f"Loaded integrated test data for {len(integrated_test_data)} PRs")

    # Filter tests
    test_data_filtered = filter_tests(integrated_test_data)
    console.log(f"Number of PRs after Filtering: {len(test_data_filtered)}")
    console.log(f"The PRs after filtering: {list(test_data_filtered.keys())}")

    # Cluster and rank tests
    test_data_cluster = cluster_and_rank_tests(test_data_filtered)
    test_data_cluster = sort_clusters_by_lines_covered(test_data_cluster)
    test_data_cluster = remove_non_disjoint_clusters(test_data_cluster)

    print_clusters_info(test_data_cluster)

    # Pick best tests
    console.log("Starting the process of picking the best tests")
    base_dir = Path(artifact_folder) / project_name
    best_tests = pick_best_tests(test_data_cluster, pr_info, base_dir=base_dir)

    console.log(f"Processed {len(best_tests)} PRs")
    for pr_number, clusters in best_tests.items():
        console.log(f"PR {pr_number}: Selected {len(clusters)} tests")

    # Generate reports
    os.makedirs(review_folder, exist_ok=True)
    total_clusters = sum(len(clusters) for clusters in best_tests.values())
    with tqdm(total=total_clusters, desc="Saving test reviews") as pbar:
        for pr_number, clusters in best_tests.items():
            pr_dir = review_folder / str(pr_number)
            if pr_dir.exists():
                console.log(
                    f"Skipping PR {pr_number}: Already exists in {review_folder}")
                pbar.update(len(clusters))
                continue

            for cluster in clusters:
                test_record = cluster['best_test']
                cluster_idx = cluster['cluster_idx']
                save_test_review(
                    test_record=test_record,
                    pr_number=pr_number,
                    cluster_idx=cluster_idx,
                    pr_info_list=pr_info,
                    review_folder=str(review_folder)
                )
                pbar.update(1)

    console.log("Report generation completed!")


# Click Interface
@click.command()
@click.option(
    '--config', required=True, type=str,
    help='Path to the configuration file')
@click.option(
    '--repository', required=True, type=str,
    help='Name of the repository (e.g., Qiskit/qiskit).')
@click.option(
    '--review_version', required=True, type=str,
    help='Version of the review (e.g., 004).')
def main(config: str, repository: str, review_version: str) -> None:
    """CLI to generate test review reports."""
    config_dict = load_config(config)
    # Override repo/project/version from CLI
    config_dict['repo_name'] = repository
    project_name = repository.split('/')[-1]
    config_dict['review_version'] = review_version
    config_dict['review_folder'] = (
        f"reviews/reviews/{review_version}/{project_name}"
    )
    generate_reports(config_dict)


if __name__ == '__main__':
    main()

# Example usage:
# python -m approach.pipeline.generate_reports --config
# config/mt/v008.yaml --repository Qiskit/qiskit --review_version 005

# GEMINI
# python -m approach.pipeline.generate_reports --config
# config/mt/v009.yaml --repository Qiskit/qiskit --review_version 006
