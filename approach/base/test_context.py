import requests
import json
import dspy
import re
import time
import ast
import random
from collections import defaultdict, Counter
from pathlib import Path
from typing import List, Dict, Any, Iterator, Tuple, Optional

from rich.console import Console
from dspy import ChainOfThought
from litellm import ContextWindowExceededError
from approach.base.pr_patch import PRPatch
from approach.coverage.formatter import shrink_context_size_no_marker
from approach.coverage.patch_coverage import PatchCoverage
from approach.utils.test_extractor import extract_test_context
from approach.utils.token_logger import LLMTokenLogger
from approach.utils.time_logger import TimeLogger
from approach.utils.test_extractor import ExtractedFunction
import os

console = Console(color_system=None)


class PickRelevantTestFiles(dspy.Signature):
    """
    Pick relevant test files for a specific PR from a shortlist of
    test files in the repository.
    """

    pr_diff: str = dspy.InputField(desc="Diff of the PR")
    candidate_test_files: str = dspy.InputField(
        desc="List of candidate test files that may be relevant to the PR"
    )

    relevant_test_files: str = dspy.OutputField(
        desc="List of relevant test files for the PR, comma separated"
    )


class PickRelevantTestClassAndTest(dspy.Signature):
    """
    The target function is a function modified in the PR that missed some test coverage.
    From Test Content, Pick:
        1) The test class that is most relevant to the target function
                we want to test (this can be None if 2) is a top level test function).
        2) The test method that is the most relevant to the target function.
        This will be used to construct the test context of the target function.
        The test context will be used to generate new tests for the target function,
        to improve its test coverage.
    For example, if the target function is `Foo.bar()` the most relevant
    test class and method possibly could be: `TestFoo.test_bar()`.
    Make sure your pick is actually in the supplied test content. Do not make it up.
    """

    pr_diff: str = dspy.InputField(desc="Diff of the PR")
    test_path = dspy.InputField(desc="Test file path")
    test_content: str = dspy.InputField(desc="The content of the Test file")
    target_func: str = dspy.InputField(
        desc="The target function that needs to be tested")
    test_class: str = dspy.OutputField(
        desc="The Name of Test Class that is the most relevant to the target function in the PR")
    test_method: str = dspy.OutputField(
        desc="The Name of Test Method that is the most relevant to the target function in the PR")


class TestContext:
    """
    Manages test-context resolution for a PR:
     1) If the PR modifies any test files, we choose those directly.
     2) Otherwise, we retrieve all test files from the repo, filter for Python
        tests, sort them by lexical relevance to the PR's modified files, then
        ask an LLM to pick which ones are most relevant.
    """

    def __init__(self, pr_patch: PRPatch,
                 keep_k_test_files: int = 3,
                 MODEL_NAME: str = "openai/gpt-4o-mini",
                 initialize=True):

        self.pr_patch = pr_patch
        self.candidate_test_files: List[str] = []
        self.relevant_test_files: List[str] = []
        self._target_funcs2test_context: defaultdict[str,
                                                     Dict[str, List[Tuple[str, str, str]]]] = defaultdict(list)
        self._test_context: Dict[str, Any] = {}
        self.keep_k_test_files = keep_k_test_files
        self.pr_has_tests = False
        self.MODEL_NAME = MODEL_NAME
        self._changed_tests: List[str] = []
        self._testfile2lines_of_interest: Dict[str, List[int]] = defaultdict(
            list)
        self.token_logger = LLMTokenLogger()
        self.time_logger = TimeLogger(
            logging_dir=self.pr_patch.base_dir / 'time' / str(pr_patch.pr_number))

        if initialize:
            self.time_logger.log_event(
                pr_number=self.pr_patch.pr_number,
                test_id=None,
                event_type="start",
                component="test_context_resolution"
            )
            self.target_funcs = PatchCoverage(self.pr_patch).target_funcs
            # make sure that the PR patch is downloaded
            self.pr_patch.download_all_file_contents()

            lm = dspy.LM(model=self.MODEL_NAME, cache=False)
            dspy.settings.configure(lm=lm)

            self._select_relevant_tests()
            if self.relevant_test_files:
                test_contents = {t: self._get_tests(
                    t) for t in self.relevant_test_files}

                # summarize the test contents
                # TODO
                test_contents_summarized = [shrink_context_size_no_marker(
                    file_content_str=test_content,
                    lines_of_interest=self._testfile2lines_of_interest[test_file],
                    file_extension='py',
                    context_size=50
                )
                    for test_file, test_content in test_contents.items()]

                self._get_test_classes_and_methods(test_contents,
                                                   test_contents_summarized)
                # check if _target_funcs2test_context is empty
                if not self._target_funcs2test_context:
                    console.log(
                        f"No test context is found for any target function in the PR {self.pr_patch.pr_number}. "
                    )
                    raise Exception(
                        f"No test context is found for any target function in the PR {self.pr_patch.pr_number}. "
                    )
            else:
                console.log(
                    f"No relevant test files found in the PR {self.pr_patch.pr_number}. " "Skipping test context resolution.")
                self.time_logger.log_event(
                    pr_number=self.pr_patch.pr_number,
                    test_id=None,
                    event_type="end",
                    component="test_context_resolution",
                    is_error=True
                )
                raise Exception(
                    f"No relevant test files found in the PR. {self.pr_patch.pr_number} ")

            # Save token logs to test context dir
            log_path = os.path.join(
                self.pr_patch.test_context_dir,
                f"{self.pr_patch.pr_number}_token_usage.json")
            with open(log_path, "w") as f:
                json.dump(self.token_logger.get_logs_as_list(), f, indent=4)
            self.time_logger.log_event(
                pr_number=self.pr_patch.pr_number,
                test_id=None,
                event_type="end",
                component="test_context_resolution"
            )

    def _select_relevant_tests(self) -> None:
        """
        1) If the diff modifies any test files, take them directly.
        2) Otherwise, get all test files from the repo, filter/sort them,
           and pick the relevant ones via LLM.
        """
        self._changed_tests = self._changed_test_files_in_diff()

        if self._changed_tests:
            console.log("Using test files found in the diff.")
            self.pr_has_tests = True
            self.relevant_test_files = self._changed_tests

            # get the lines of interest in the test files
            diff_contents = self.pr_patch.diff_file_contents
            for test_file, test_diff_hunks in diff_contents.items():
                if test_file in self._changed_tests:
                    self._testfile2lines_of_interest[test_file] = list(
                        map(lambda h: h.target_start, test_diff_hunks))
            return
        self._get_repo_test_files()
        if self.candidate_test_files:
            self.candidate_test_files = self.candidate_test_files[:self.keep_k_test_files]
        self._pick_relevant_tests_with_llm()

    def _changed_test_files_in_diff(self) -> List[str]:
        """Return a list of *python* test files changed/added in the PR.
        This method processes the list of files changed in a pull request and returns
        those that are related to tests (containing 'test' or 'tests' in their path).
        The paths are cleaned by removing 'a/' or 'b/' prefixes that are typically
        present in git diff outputs.
        Returns:
            List[str]: A list of cleaned file paths for test files that were modified
                      in the pull request.
        """
        """Return a list of *python* test files changed in the PR."""

        changed_files = self.pr_patch.file_list_after
        return [
            f for f in changed_files if 
            (
                "test" in f.lower()
                or "tests" in f.lower()
            )
            and not f.endswith("__init__.py")
            and f.endswith(".py")]

    def _get_repo_test_files(self) -> None:
        """
        Populate candidate_test_files by querying GitHub for all files
        in the repo, then filtering and sorting them.
        1) Only keep Python test files (ending with .py).
        2) Sort by lexical similarity to the PR's modified file paths.
        """
        branch = self._get_default_branch()
        all_paths = self._fetch_github_tree(branch=branch)

        # Keep only those that appear to be test files + .py
        test_paths = [
            path for path in all_paths
            if ("test" in path.lower() or "tests" in path.lower())
            and path.lower().endswith(".py")
        ]
        if not test_paths:
            console.log("No Python test files found in the repository tree.")
            self.candidate_test_files = []
            return

        # Sort them by lexical similarity
        changed_files = self.pr_patch.file_list_after
        test_paths = self._sort_by_lexical_similarity(
            paths=test_paths,
            changed_files=changed_files
        )

        self.candidate_test_files = test_paths

    def _sort_by_lexical_similarity(
        self, paths: List[str], changed_files: List[str]
    ) -> List[str]:
        """
        For each test path, compute a lexical similarity score
        against the PR's changed files, then sort descending.
        We'll keep the highest score for each test path (i.e.,
        if it matches multiple changed files, we use the best match).
        """
        def best_score_for_path(test_path: str) -> float:
            return max(
                self._compute_lexical_similarity(test_path, cf)
                for cf in changed_files
            ) if changed_files else 0.0

        sorted_paths = sorted(
            paths,
            key=lambda p: best_score_for_path(p),
            reverse=True
        )
        return sorted_paths

    def _compute_lexical_similarity(self, file_a: str, file_b: str) -> float:
        """
        Example of a pure lexical approach: break file paths into tokens,
        take Jaccard similarity (intersection / union) of those token sets.
        """
        tokens_a = set(re.split(r'[/\\._-]+', file_a.lower()))
        tokens_b = set(re.split(r'[/\\._-]+', file_b.lower()))
        if not tokens_a or not tokens_b:
            return 0.0
        return float(
            len(tokens_a.intersection(tokens_b))) / float(
            len(tokens_a.union(tokens_b)))

    def _get_default_branch(self) -> str:
        """Return the repo's default branch or 'main' if not found."""
        url = (
            f"https://api.github.com/repos/"
            f"{self.pr_patch.repo_owner}/{self.pr_patch.repo_name}"
        )
        resp = requests.get(url=url)
        if resp.status_code != 200:
            console.log(
                f"Unable to retrieve default branch. "
                f"Status code: {resp.status_code}"
            )
            return "main"
        data = resp.json()
        return data.get("default_branch", "main")

    def _fetch_github_tree(self, branch: str) -> List[str]:
        """Return all file paths in the repo at the given branch."""
        url = (
            f"https://api.github.com/repos/"
            f"{self.pr_patch.repo_owner}/{self.pr_patch.repo_name}"
            f"/git/trees/{branch}?recursive=1"
        )
        resp = requests.get(url=url)
        if resp.status_code != 200:
            console.log(
                f"Unable to fetch tree for branch {branch}. "
                f"Status code: {resp.status_code}"
            )
            return []
        items = resp.json().get("tree", [])
        return [
            item["path"] for item in items
            if item.get("type") == "blob"
        ]

    def _pick_relevant_tests_with_llm(self) -> None:
        """
        Call the LLM prompt to pick relevant test files
        from self.candidate_test_files.
        """
        diff_text = self.pr_patch.diff
        test_files_str = "\n".join(self.candidate_test_files)

        # TODO: add the test files summary/metadata to the prompt
        chain = ChainOfThought(PickRelevantTestFiles)
        response = chain(
            pr_diff=diff_text,
            candidate_test_files=test_files_str
        )
        # Log PickRelevantTestFiles right after ChainOfThought call
        lm = dspy.settings.get("lm", None)
        self.token_logger.log(lm=lm, stage=PickRelevantTestFiles)
        raw_string = response.relevant_test_files.strip()
        if not raw_string:
            self.relevant_test_files = []
        else:
            # For example, if the LLM returns "test_a.py\ntest_b.py"
            self.relevant_test_files = [
                line.strip()
                for line in raw_string.split(',')
                if line.strip()
            ]

    def _get_test_classes_and_methods(
            self,
            test_contents: dict,
            test_contents_summarized: List[str]) -> None:
        """
        For each test file, call the LLM to pick the relevant
        test class and methods
        """

        chain = ChainOfThought(PickRelevantTestClassAndTest)

        for target_func, _ in self.target_funcs.most_common(3):
            func2context = defaultdict(list)
            for test_path, test_content, test_content_summarized in zip(
                    self.relevant_test_files,
                    test_contents.values(),
                    test_contents_summarized):
                try:
                    response = chain(
                        pr_diff=self.pr_patch.diff,
                        target_func=target_func.full_str,
                        test_path=test_path,
                        test_content=test_content_summarized
                    )
                except ContextWindowExceededError as e:
                    console.log(
                        f"Context window exceeded when generating LLM test context using \
                            PickRelevantTestClassAndTest for target function {target_func}, skipped. {e}")
                    continue
                # Log PickRelevantTestClassAndTest right after ChainOfThought
                # call
                lm = dspy.settings.get("lm", None)
                self.token_logger.log(
                    lm=lm, stage=PickRelevantTestClassAndTest)
                try:
                    test_class = response.test_class
                    test_method_name = response.test_method
                    test_method_full = extract_test_context(
                        test_content,
                        test_class, test_method_name)
                except ValueError as e:
                    console.log(
                        f"LLM picked test class {test_class} and method {test_method_name} can not be extracted from the test content.")
                    console.log(f"Using empty test context for target function {str(target_func)}.")
                    # set the test class and method to None
                    # aka. no test context
                    test_class = None
                    test_method_name = None
                    test_method_full = ""
                if (test_class, test_method_name,
                        test_method_full) not in func2context[test_path]:
                    func2context[test_path].append(
                        (test_class, test_method_name, test_method_full)
                    )
            # Store the test context for this target function
            if func2context:
                self._target_funcs2test_context[str(target_func)] = func2context

    def _get_tests(self, test_file: str) -> str:
        """
        Get the content of the test file.
        """
        if test_file in self._changed_tests:
            for file in self.pr_patch.file_contents_after:
                file_path = file["file_path"]
                file_content = file["content"]
                if file_path == test_file:
                    return file_content
        else:
            return self._download_tests(test_file)

    def _download_tests(self, test_file: str) -> str:
        """
        Download the given test file from the repo.
        """
        url = (
            f"https://raw.githubusercontent.com/"
            f"{self.pr_patch.repo_owner}/{self.pr_patch.repo_name}/"
            f"{self._get_default_branch()}/{test_file}"
        )
        # Try a few more times
        for _ in range(3):
            resp = requests.get(url=url)
            if resp.status_code == 200:
                return resp.text
            # sleep
            time.sleep(3)
        console.log(
            f"Unable to download {test_file}. "
            f"Status code: {resp.status_code}"
        )
        return ""

    def _retrieve_full_test_method(self, test_file: str, test_class: str,
                                   test_method_name: str) -> str:
        """
        Retrieve the full test method definition from the test file.
        """
        def _trunc_test_file_path(test_file: str) -> str:
            """
            Truncate the test file path to remove
            /opt/{REPO_NAME}/ AND anything before site-packages/.
            """
            # First, remove '/opt/{REPO_NAME}/' pattern
            path = re.sub(r"^/opt/[^/]+/", "", test_file)

            # Then remove anything before 'site-packages/'
            path = re.sub(r"^.*site-packages/", "", path)

            return path

        # Read the test file
        for file_path, file_content in self.test_contents.items():
            if _trunc_test_file_path(test_file) in file_path:
                # Parse the test file content
                tree = ast.parse(file_content)
                # Find the class definition
                for node in ast.iter_child_nodes(tree):
                    if isinstance(
                            node, ast.ClassDef) and node.name == test_class:
                        # Find the method definition
                        for method in node.body:
                            if isinstance(
                                    method, ast.FunctionDef) and method.name == test_method_name:
                                # Convert the AST back to source code
                                return ast.unparse(method)

    def most_common_test_context(
            self, target_func: ExtractedFunction) -> Tuple[str, str, str, str]:
        """
        Get the most common test file, class and method for the given target function.
        """

        func_test_context = self.test_context.get(
            "target_funcs2test_context", {}).get(
            str(target_func), {})

        if not func_test_context:
            raise ValueError(
                f"No test context found for the target function {target_func}")

        # pick a random test file
        test_file = random.choice(list(func_test_context.keys()))

        # pick the most common test class and method
        test_class, test_method_name, test_content = func_test_context[test_file][0]

        return test_file, test_class, test_method_name, test_content

    @property
    def test_context(self) -> Dict[str, Any]:
        """
        Example property with overall info about chosen tests.
        """
        if not self._test_context:
            self._test_context = {
                "pr_number": self.pr_patch.pr_number,
                "keep_k_test_files": self.keep_k_test_files,
                "candidate_test_files": self.candidate_test_files,
                "relevant_test_files": self.relevant_test_files,
                "target_funcs2test_context": self._target_funcs2test_context,
                "pr_has_tests": self.pr_has_tests,
                "model_name": self.MODEL_NAME
            }
        return self._test_context

    def __repr__(self) -> str:
        return f"TestContext({self.test_context})"

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the test context to a dictionary.
        """
        return self.test_context

    def to_json(self, file_path: str):
        with open(file_path, 'w') as f:
            json.dump(self.test_context, f, indent=4)

    @property
    def is_empty(self) -> bool:
        return self._test_context == {}

    @classmethod
    def from_json(cls, file_path: str):
        with open(file_path, 'r') as f:
            data = json.load(f)
        # filepath PosixPath('data/test_augmentation/010_gemini/qiskit/test_context/13214_dynamic.json')
        # repo name > qiskit
        # base dir > data/test_augmentation/010_gemini/qiskit
        repo_name = str(file_path).split('/')[-3]
        base_dir = str(Path(file_path).parent.parent)
        obj = cls(
            pr_patch=PRPatch(
                repo_owner=repo_name,
                repo_name=repo_name,
                pr_number=data['pr_number'],
                base_dir=base_dir,
            ),
            initialize=False
        )
        obj._test_context = data
        return obj


class TestContextDynamic(TestContext):
    """
    Manages test-context resolution for a PR:
     1) If the PR modifies any test files, we choose those directly.
     2) Otherwise, we retrieve all test files from the repo, filter for Python
        tests, sort them by lexical relevance to the PR's modified files, then
        ask an LLM to pick which ones are most relevant.

    Dynamic:

        For each test file, instead of prompting LLM,
        run Viztracer (inside the docker container) to obtain function call trace.

        Parse the trace to obtain a caller stack of the target (uncovered) function.
        The relevant test case should be an ancestor in the call stack.
    """

    def __init__(self,
                 pr_patch: PRPatch,
                 keep_k_test_files: int = 3,
                 MODEL_NAME: str = "openai/gpt-4o-mini",
                 initialize=True):
        # create attributes using the parent class, do not initialize them
        super().__init__(pr_patch,
                         keep_k_test_files,
                         MODEL_NAME,
                         initialize=False)

        if initialize:
            # Initialize the LLM
            lm = dspy.LM(model=self.MODEL_NAME, cache=False)
            dspy.settings.configure(lm=lm)

            self._select_relevant_tests()
            if self.relevant_test_files:

                # TestContextDynamic exposes the test_contents property for
                # Generator to use
                self.test_contents = {t: self._get_tests(
                    t) for t in self.relevant_test_files}
            else:
                raise Exception(
                    f"Failed to initialize Dynamic Test Context: No relevant test files found in the PR {self.pr_patch.pr_number}. ")

    def _parse_call_chain(
            self, call_chain_data: dict) -> Dict[str, List[Tuple[str, str, str]]]:
        """
        Parse the call chain file of a single target function
        """
        func2chain = defaultdict(list)

        files = call_chain_data.get("files", None)

        # Check invocations
        if call_chain_data["total_invocations"] == 0:
            console.log(
                f"No invocations found for {call_chain_data['target_pattern']}")

        # Iterate over call chains and find the relevant test files, test class
        # and test method
        call_chains = call_chain_data.get("call_chains", [])
        # sort call_chains by # occurences
        call_chains.sort(key=lambda x: x["occurrences"], reverse=True)

        for call_chain in call_chains:
            callers = call_chain["callers"]
            # Get the last caller that is a test
            for caller in reversed(callers):
                if viztracer_frame_is_testfunc(caller["name"]):
                    try:
                        test_file = caller["file"]
                        test_class = caller["name"].split(
                            ".")[0] if "." in caller["name"] else None
                        test_method_name = caller["name"].split(".")[-1]
                        # Retrieve the full test method definition
                        # test_method = self._retrieve_full_test_method(test_file, test_class, test_method_name)
                        test_content = extract_test_context(
                            files[test_file],
                            test_class, test_method_name)
                        # Store the relevant test file, class and method
                        if (test_class, test_method_name,
                                test_content) not in func2chain[test_file]:
                            func2chain[test_file].append(
                                (test_class, test_method_name, test_content))

                        break
                    except Exception as e:
                        raise Exception(
                            f"Error retrieving test method for {call_chain_data['target_pattern']}: {e}")
        return func2chain

    def parse_call_chain_target_funcs(self,
                                      target_funcs: Counter[ExtractedFunction],
                                      call_chain_file_pattern: Path) -> None:
        """
        For k most common target functions, parse its call chain file:
        Parse the call chain file containing all the function call stacks of the target function.
        The JSON format is:

        testfile2classmethod:
        {
            "target_pattern": "_VectorHessWrapper._fd_hess",
            "total_invocations": 9,
            "call_chains": [
            {
            "callers": [
                {
                "name": "TestCase.run",
                "file": "/usr/local/lib/python3.11/unittest/case.py",
                "line": 589
                },
                ...
                {
                "name": "TestVectorialFunction.test_finite_difference_hess_linear_operator",
                "file": "/opt/scipy/build-install/lib/python3.11/site-packages/scipy/optimize/tests/test_differentiable_functions.py",
                "line": 655
                },
                ...
                {
                "name": "_VectorHessWrapper.__call__",
                "file": "/opt/scipy/build-install/lib/python3.11/site-packages/scipy/optimize/_differentiable_functions.py",
                "line": 480
                }
            ],
            "occurrences": 1,
            "percentage": 0.1111111111111111
            },
            {
                # another call chain
            }
        }

        testfile2classmethod[test_file] = [
            (test_class, test_method_name, test_content)
        ] sorted by the number of invocations

        Store the {target func: test context} into this field
        self.target_funcs2test_context: Dict[ExtractedFunction, Tuple[List[Tuple[str, str, str]], bool]]
        """

        top_k_target_funcs = target_funcs.most_common(3)
        call_chain_files_list = list(
            self.pr_patch.test_context_dir.glob(call_chain_file_pattern.name))

        # Load all call chain files as JSON
        call_chain_data = {}
        for call_chain_file in call_chain_files_list:
            with open(call_chain_file, 'r') as f:
                data = json.load(f)
                call_chain_data[data.get("target_pattern", "N/A")] = data

        for target_func, _ in top_k_target_funcs:
            func_str = str(target_func)
            # Find the call chain file for this target function
            for target_pattern, data in call_chain_data.items():
                if target_pattern == func_str:
                    # Parse the call chain file for this target function
                    func2chain = self._parse_call_chain(call_chain_data=data)
                    # Store the test context for this target function
                    self._target_funcs2test_context[str(
                        target_func)] = func2chain
                    console.log(
                        f"Parsed call chain for {target_func}")
                    break


def viztracer_frame_is_testfunc(name: str) -> bool:
    """
    Heuristic to determine if a stack frame name in Viztracer is a test function
    e.g.
    call_and_report.<locals>.<lambda> ------------------------> No
    _multicall -----------------------------------------------> No
    pytest_pyfunc_call ---------------------------------------> No
    test_VectorFunctionNoReferenceCycle.<locals>.<lambda> ----> We skip anonymous and inner functions for now
    test_VectorFunctionNoReferenceCycle ----------------------> Yes, top-level test function
    TestVectorialFunction.test_x_storage_overlap -------------> Yes, class test method
    """
    return (
        "test_" in name.lower() and
        "<locals>" not in name.lower() and
        "<lambda>" not in name.lower() and
        "pytest" not in name.lower()
    )
