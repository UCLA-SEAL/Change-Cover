from approach.scoping.pr_selection import process_pull_requests
import pytest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, mock_open


@pytest.fixture
def github_token_str():
    token = os.getenv("GITHUB_TOKEN")
    if token is None:
        with open("secrets/github_token.txt", "r") as file:
            token = file.read().strip()
    return token


def test_process_pull_requests(
        github_token_str):
    """
    Test that process_pull_requests correctly orchestrates the steps to process PRs.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        github_token_path = Path(temp_dir) / "github_token.txt"
        github_token_path.write_text(github_token_str)

        repository = "All-Hands-AI/OpenHands"
        project_name = "OpenHands"
        # USE FIXED FOLDER FOR DEBUGGING
        # output_folder = "data/tests_artifacts"
        output_folder = Path(temp_dir) / "tests_artifacts"
        output_folder.mkdir(parents=True, exist_ok=True)
        num_prs = 5

        process_pull_requests(
            repository=repository, project_name=project_name,
            github_token_path=github_token_path, output_folder=output_folder,
            num_prs=num_prs)

        # check that the output folder was created
        # with pr_list_filtered.txt and diffs folder
        assert os.path.exists(output_folder), "Output folder was not created"
        assert os.path.exists(os.path.join(output_folder, project_name,
                                           "pr_list_filtered.txt")), "pr_list_filtered.txt was not created"
        assert os.path.exists(os.path.join(
            output_folder, project_name, "diffs")), "diffs folder was not created"
