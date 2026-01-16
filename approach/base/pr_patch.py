from __future__ import annotations
from pathlib import Path
import json
from typing import List, Optional, Iterator, Dict, Any, Tuple, TYPE_CHECKING
import requests
from rich.console import Console
import unidiff
import re
from bs4 import BeautifulSoup
from collections import defaultdict
import warnings

from approach.scoping.spot_code_difference import (
    create_headers,
    get_pr_commits,
    get_pr_title_and_labels,
    fetch_file_contents,
    is_code_changed
)

from approach.base.page_info import PageInfo
from approach.utils.time_logger import TimeLogger

if TYPE_CHECKING:
    from approach.base.isolated_environment import IsolatedEnvironment

"""### Task Description: Implement a Patch Management Class

**Objective:**
Create a Python class `Patch` to manage patches for a repository. The `Patch` class should store relevant information about the patch and provide methods to retrieve and store file contents as needed.

**Requirements:**

1. **Patch Class:**
   - Attributes:
     - `repo_owner`: Owner of the repository.
     - `repo_name`: Name of the repository.
     - `pr_number`: Pull request number.
     - `diff_location`: Location of the diff file.
     - `base_dir`: Base directory where patch information is stored.
     - `file_names_before`: List of file names before the patch.
     - `file_names_after`: List of file names after the patch.
   - Methods:
     - Initialization method to set up the attributes.
     - Method to retrieve the diff file using the URL `https://github.com/{repo_owner}/{repo_name}/pull/{pr_number}.diff` if not available locally.
     - Properties to get the file list and file contents, retrieving and storing them as needed using an external library (leave unimplemented).

2. **File Storage:**
   - Store file contents in the `base_dir` under `file_content/before` and `file_content/after`, mimicking the original folder structure.
   - Ensure that file contents are only retrieved when needed.

3. **Dependencies and Environment:**
   - Use standard Python libraries or specify any additional dependencies required.
   - Ensure compatibility with a Linux environment.

4. **Testing and Documentation:**
   - Include unit tests to verify the functionality of the `Patch` class.
   - Provide documentation and usage examples for the class.

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
"""

console = Console(color_system=None)


class PRPatch:
    def __init__(self, repo_owner: str, repo_name: str, pr_number: int,
                 base_dir: str, force_folder_name: bool = False,
                 MODEL_NAME: str = "openai/gpt-4o-mini"):
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.pr_number = pr_number
        self.base_dir = Path(base_dir)

        if not any(
                word in self.base_dir.name.lower()
                for word in [repo_owner, repo_name]):
            warning_message = (
                f"Base directory '{base_dir}' does not contain "
                f"repository owner '{repo_owner}' or repository name '{repo_name}'")
            warnings.warn(warning_message)
            if not force_folder_name:
                answer = input("Press Y to proceed anyway...")
                if answer.lower() != 'y':
                    raise ValueError(
                        "Base directory does not match the repository.")

        self.diff_dir = self.base_dir / 'diffs'
        self.coverage_dir = self.base_dir / 'coverage' / str(self.pr_number)
        self.patch_coverage_path = self.coverage_dir / f"current_relevance.json"
        self._uncovered_lines_summary = None
        self.diff_path = self.diff_dir / f"{pr_number}.diff"
        self.dev_discussion_dir = self.base_dir / 'dev_discussion'
        self.augmented_discussion_dir = self.base_dir / 'augmented_discussion'
        self.test_context_dir = self.base_dir / 'test_context'
        self.inclusion_dir = self.base_dir / 'inclusion'
        self.before_dir = self.base_dir / \
            'file_content' / str(pr_number) / 'before'
        self.after_dir = self.base_dir / \
            'file_content' / str(pr_number) / 'after'
        self.metadata_folder = self.base_dir / 'metadata' / str(pr_number)
        self.file_names_before: List[str] = []
        self.file_names_after: List[str] = []
        self.MODEL_NAME = MODEL_NAME
        self.time_logger = TimeLogger(
            logging_dir=self.base_dir / 'time' / str(pr_number))
        self._ensure_directories_exist()

    def _ensure_directories_exist(self) -> None:
        Path(self.base_dir).mkdir(parents=True, exist_ok=True)
        (self.diff_dir).mkdir(parents=True, exist_ok=True)
        (self.coverage_dir).mkdir(parents=True, exist_ok=True)
        (self.dev_discussion_dir).mkdir(parents=True, exist_ok=True)
        (self.augmented_discussion_dir).mkdir(parents=True, exist_ok=True)
        (self.before_dir).mkdir(parents=True, exist_ok=True)
        (self.after_dir).mkdir(parents=True, exist_ok=True)
        (self.metadata_folder).mkdir(parents=True, exist_ok=True)
        (self.test_context_dir).mkdir(parents=True, exist_ok=True)
        (self.inclusion_dir).mkdir(parents=True, exist_ok=True)

    def log_exclusion_reason(self, reason: str, level: int) -> None:
        """Log the reason for excluding the PR from further processing."""
        exclusion_path = self.inclusion_dir / f"{self.pr_number}.json"
        exclusion_data = {
            'status': 'excluded',
            'reason': reason,
            'level': level,
        }
        with open(exclusion_path, 'w') as f:
            json.dump(exclusion_data, f, indent=4)

    def is_excluded(self) -> bool:
        """Check if the PR is excluded from further processing."""
        exclusion_path = self.inclusion_dir / f"{self.pr_number}.json"
        if exclusion_path.exists():
            with open(exclusion_path, 'r') as f:
                exclusion_data = json.load(f)
            return exclusion_data.get('status') == 'excluded'
        return False

    def retrieve_diff_file(self) -> None:
        if not self.diff_path.exists():
            import os
            from approach.scoping.pr_selection import get_pull_diff_v3
            github_token = os.getenv("GITHUB_TOKEN")
            diff = get_pull_diff_v3(
                owner=self.repo_owner,
                repo=self.repo_name,
                pull_number=self.pr_number,
                token=github_token)
            self.diff_path.write_text(diff)
            console.log(
                f"Diff file retrieved and saved to {self.diff_path}")

    def retrieve_dev_discussion(self) -> None:
        discussion_path = Path(
            self.dev_discussion_dir) / f"{self.pr_number}.json"
        if not discussion_path.exists():
            url = f"https://github.com/{self.repo_owner}/{self.repo_name}/pull/{self.pr_number}"
            console.log(f"Retrieving dev discussion: {url}")
            page = PageInfo(url)
            page.to_json(discussion_path)

    @property
    def title(self) -> str:
        """Get the title of the PR."""
        metadata_path = self.metadata_folder / 'title_and_labels.json'
        if not metadata_path.exists():
            self.download_title_and_labels()
        with open(metadata_path, 'r') as f:
            metadata = json.load(f)
        return metadata['title']

    @property
    def labels(self) -> List[str]:
        """Get the labels of the PR."""
        metadata_path = self.metadata_folder / 'title_and_labels.json'
        if not metadata_path.exists():
            self.download_title_and_labels()
        with open(metadata_path, 'r') as f:
            metadata = json.load(f)
        return metadata['labels']

    @property
    def pr_state(self) -> str:
        """Get the state of the PR."""
        metadata_path = self.metadata_folder / 'title_and_labels.json'
        if not metadata_path.exists():
            self.download_title_and_labels()
        with open(metadata_path, 'r') as f:
            metadata = json.load(f)
        return metadata.get('state', 'unknown')

    @property
    def dev_discussion(self) -> Dict[str, Any]:
        discussion_path = Path(
            self.dev_discussion_dir) / f"{self.pr_number}.json"
        if not discussion_path.exists():
            self.retrieve_dev_discussion()
        return PageInfo.from_json(discussion_path)

    def retrieve_augmented_discussion(self) -> None:
        aug_discussion_path = Path(
            self.augmented_discussion_dir) / f"{self.pr_number}.json"
        if not aug_discussion_path.exists():
            self.time_logger.log_event(
                pr_number=self.pr_number,
                test_id=None,
                event_type="start",
                component="pr_context"
            )
            console.log(f"Starting to enrich the discussion: {self.pr_number}")
            starting_page = self.dev_discussion
            starting_page.enrich(max_iterations=3)
            starting_page.to_json(aug_discussion_path)
            self.time_logger.log_event(
                pr_number=self.pr_number,
                test_id=None,
                event_type="end",
                component="pr_context"
            )

    @property
    def augmented_discussion(self) -> Dict[str, Any]:
        aug_discussion_path = Path(
            self.augmented_discussion_dir) / f"{self.pr_number}.json"
        if not aug_discussion_path.exists():
            self.retrieve_augmented_discussion()
        return PageInfo.from_json(aug_discussion_path)

    def retrieve_test_context(self) -> None:
        from approach.base.test_context import TestContext
        test_context_path = Path(
            self.test_context_dir) / f"{self.pr_number}.json"
        if not test_context_path.exists():
            console.log(
                f"Starting to create the test context for: {self.pr_number}")
            text_context = TestContext(
                pr_patch=self, MODEL_NAME=self.MODEL_NAME, initialize=True)
            text_context.to_json(test_context_path)

    @property
    def test_context(self):
        from approach.base.test_context import TestContext
        test_context_path = Path(
            self.test_context_dir) / f"{self.pr_number}.json"
        if not test_context_path.exists():
            self.retrieve_test_context()
        return TestContext.from_json(test_context_path)

    @property
    def test_context_dynamic(self):
        from approach.base.test_context import TestContextDynamic
        test_context_path = Path(
            self.test_context_dir) / f"{self.pr_number}_dynamic.json"
        if not test_context_path.exists():
            raise ValueError(
                "Dynamic test context not found. Please generate it first.")
        return TestContextDynamic.from_json(test_context_path)

    @property
    def diff(self) -> str:
        if not self.diff_path.exists():
            self.retrieve_diff_file()
        return self.diff_path.read_text()

    @property
    def file_list_before(self) -> List[str]:
        if not self.file_names_before:
            self._parse_diff()
        return self.file_names_before

    @property
    def file_list_after(self) -> List[str]:
        if not self.file_names_after:
            self._parse_diff()
        return self.file_names_after

    @property
    def touched_files(self) -> List[str]:
        """Get the list of files touched by the PR."""
        if not self.file_names_before or not self.file_names_after:
            self._parse_diff()
        return list(set(self.file_names_before + self.file_names_after))

    @property
    def is_covered_by_testsuite(self) -> bool:
        return "# UNCOVERED" not in self.uncovered_lines_summary

    @property
    def uncovered_lines_summary(self) -> str:
        if not self._uncovered_lines_summary:
            filepath = (
                self.coverage_dir /
                "pr_uncovered_lines.txt")
            try:
                if not filepath.exists():
                    console.log(
                        "Use PatchCoverage to create the summary of uncovered lines.")
                self._uncovered_lines_summary = filepath.read_text()
            except FileNotFoundError:
                console.log(
                    f"Uncovered lines summary file not found at "
                    f"{filepath}. Create the summary first.")
        return self._uncovered_lines_summary

    @property
    def file_contents_before(self) -> Iterator[Dict[str, str]]:
        for file_path in self.before_dir.rglob('*'):
            if file_path.is_file():
                yield {
                    'file_path': str(file_path.relative_to(self.before_dir)),
                    'content': file_path.read_text()
                }

    @property
    def file_contents_after(self) -> Iterator[Dict[str, str]]:
        for file_path in self.after_dir.rglob('*'):
            if file_path.is_file():
                yield {
                    'file_path': str(file_path.relative_to(self.after_dir)),
                    'content': file_path.read_text()
                }

    @property
    def diff_file_contents(self) -> Dict[str, List[unidiff.patch.Hunk]]:
        """Parse the diff file and return a dictionary of file paths to their diff hunks."""
        diff_file2content = defaultdict(list)
        diff = unidiff.PatchSet(self.diff)
        for file in diff:
            if file.is_modified_file:
                for hunk in file:
                    diff_file2content[file.path].append(hunk)
        return diff_file2content

    def _parse_diff(self) -> None:
        def clean_path_in_diff(path: str) -> str:
            if path.startswith("a/"):
                path = path[2:]
            elif path.startswith("b/"):
                path = path[2:]
            return path

        diff = unidiff.PatchSet(self.diff)
        self.file_names_before = [
            file.path for file in diff if file.is_modified_file]
        self.file_names_after = [
            clean_path_in_diff(file.target_file) for file in diff
            if file.is_modified_file or file.is_added_file]

    def download_all_file_contents(self) -> None:
        # check to see if the file_changes.json file already exists
        if (self.metadata_folder / 'file_changes.json').exists():
            console.log(
                f"PR: {self.pr_number}'s file_changes.json already downloaded. Skipping download.",
                style="yellow")
            with open(self.metadata_folder / 'file_changes.json', 'r') as f:
                file_contents = json.load(f)
                console.log(
                    f"Loaded {len(file_contents)} file contents from file_changes.json")
        else:
            console.log("Starting to download all file contents.")
            headers = create_headers()
            base_commit, head_commit, changed_files = get_pr_commits(
                owner=self.repo_owner, name=self.repo_name,
                number=self.pr_number, headers=headers)
            console.log(
                f"Base commit: {base_commit}, Head commit: {head_commit}")
            file_contents = fetch_file_contents(
                owner=self.repo_owner, name=self.repo_name,
                base_commit=base_commit, head_commit=head_commit,
                changed_files=changed_files, headers=headers)
            console.log(f"Fetched contents for {len(file_contents)} files.")

            with open(self.metadata_folder / 'file_changes.json', 'w') as f:
                json.dump(file_contents, f)
                console.log("File changes saved to file_changes.json")

        for file_content in file_contents:
            file_path = file_content['path']
            base_content = file_content['base_content']
            head_content = file_content['head_content']
            console.log(f"Storing contents for file: {file_path}")
            self._store_file_content(file_path, base_content, head_content)
        console.log("Completed downloading and storing all file contents.")

    @property
    def file_changes(self) -> List[Dict[str, Any]]:
        """Get the list of file changes with their contents."""
        file_changes_path = self.metadata_folder / 'file_changes.json'
        if not file_changes_path.exists():
            self.download_all_file_contents()
        with open(file_changes_path, 'r') as f:
            return json.load(f)

    def has_only_documentation_changes(self) -> bool:
        """Check if the PR only contains documentation changes."""
        touched_files = self.touched_files
        non_test_python_files = [
            f for f in touched_files if f.endswith('.py') and
            'test_' not in f]
        file_changes = self.file_changes
        relevant_file_changes = [
            change for change in file_changes
            if change['path'] in non_test_python_files
        ]
        for file in relevant_file_changes:
            if file['base_content'] and file['head_content']:
                if is_code_changed(
                        file['base_content'],
                        file['head_content']):
                    return False
        return True

    def has_only_deletion_changes_on_these_files(
            self, files: List[str]) -> bool:
        """Check if the PR only contains deletion changes on specified files."""
        file_changes = self.file_changes
        relevant_file_changes = [
            change for change in file_changes
            if change['path'] in files
        ]
        # records are of the type:
        # {"path": "releasenotes/notes/fix-estimator-pub-coerce-5d13700e15126421.yaml", "change_type": "DELETED", "base_content": null, "head_content": null}
        all_deletions = all(
            change['change_type'] == 'DELETED'
            for change in relevant_file_changes
        )
        return all_deletions

    def _store_file_content(
            self, file_path: str, base_content: Optional[str],
            head_content: Optional[str]) -> None:
        if base_content:
            before_path = self.before_dir / f'{file_path}'
            before_path.parent.mkdir(parents=True, exist_ok=True)
            before_path.write_text(base_content)
        if head_content:
            after_path = self.after_dir / f'{file_path}'
            after_path.parent.mkdir(parents=True, exist_ok=True)
            after_path.write_text(head_content)

    def download_title_and_labels(self) -> None:
        """Download the PR title and labels and store them in the metadata folder."""
        title, labels = get_pr_title_and_labels(
            owner=self.repo_owner, name=self.repo_name,
            number=self.pr_number)
        metadata_path = self.metadata_folder / 'title_and_labels.json'
        metadata = {
            'title': title,
            'labels': labels
        }
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f)
        console.log(f"Title and labels saved to {metadata_path}")

    def __gt__(self, other: 'PRPatch') -> bool:
        """Compare PRPatch instances based on repo_owner, repo_name, and pr_number."""
        if not isinstance(other, PRPatch):
            return NotImplemented
        if self.repo_owner != other.repo_owner:
            return self.repo_owner > other.repo_owner
        if self.repo_name != other.repo_name:
            return self.repo_name > other.repo_name
        return self.pr_number > other.pr_number

    def __lt__(self, other: 'PRPatch') -> bool:
        """Compare PRPatch instances based on repo_owner, repo_name, and pr_number."""
        if not isinstance(other, PRPatch):
            return NotImplemented
        if self.repo_owner != other.repo_owner:
            return self.repo_owner < other.repo_owner
        if self.repo_name != other.repo_name:
            return self.repo_name < other.repo_name
        return self.pr_number < other.pr_number

    def __eq__(self, other: 'PRPatch') -> bool:
        """Compare PRPatch instances based on repo_owner, repo_name, and pr_number."""
        if not isinstance(other, PRPatch):
            return NotImplemented
        return (
            self.repo_owner == other.repo_owner and
            self.repo_name == other.repo_name and
            self.pr_number == other.pr_number
        )

    def __str__(self) -> str:
        return (
            f"PRPatch(repo_owner={self.repo_owner}, repo_name={self.repo_name}, "
            f"pr_number={self.pr_number}, base_dir={self.base_dir})")

    def __repr__(self) -> str:
        return str(self)
