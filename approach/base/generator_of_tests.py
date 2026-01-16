import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple, Set, Optional
from rich.console import Console
from unidiff import PatchSet
from dataclasses import dataclass
import click
import dspy
import docker
import json
import time
import ast
import re
import traceback
import yaml

from approach.docker_handling.docker_utils import (
    execute_command,
    read_from_container_file,
    write_to_container_file
)

from approach.base.pr_patch import PRPatch
from approach.base.isolated_environment import IsolatedEnvironment
from approach.base.test_context import TestContext
from approach.coverage.patch_coverage import (
    flatten_coverage_datapoint,
    PatchCoverage
)
from approach.utils.merge_tests import merge_tests
from approach.utils.test_extractor import ExtractedFunction
from approach.coverage.formatter import (
    shrink_context_size_no_marker,
    truncate,
    add_trailing_newline)
from approach.utils.token_logger import LLMTokenLogger
from approach.utils.time_logger import TimeLogger


"""
### Task Description: Implement a `TestGenerator` Class

**Objective:**
Implement a `TestGenerator` class that takes a `PRPatch` object as input and generates a test file using an LLM. The test file should be stored in a specific directory structure and follow a specific naming convention.

**Requirements:**

1. **Input:**
   - The PR input will be provided as a `PRPatch` object.
   - The `TestGenerator` will decide which fields of the `PRPatch` object to use for test generation.

2. **Test Generation:**
   - The generated test should include a placeholder for the LLM-generated content.
   - Use the `unittest` framework for the tests.
   - Follow PEP 8 coding standards for the test code.

3. **File Structure:**
   - The `base_dir` will be provided and is assumed to be available.
   - The `TestGenerator` should ensure the `test_cases` subfolder and the PR number subfolder exist, creating them if necessary.

4. **File Naming:**
   - Generate a UUID using the `uuid` library.
   - The filename should be in the format `test_<uuid>_yy_mm_dd__hh_mm.py` using the local time.

5. **Error Handling:**
   - Handle invalid PR input and file creation issues gracefully.
   - Log errors to a file named `test_generator_errors.log` in the `base_dir`.

6. **Execution:**
   - The `TestGenerator` should be initialized with a `PRPatch` object and then call `.generate()` to create the test.
   - The `TestGenerator` should be executable from the command line.
   - Support the following command line arguments:
     - `--pr` (required): Path to the PR input file.
     - `--base-dir` (required): Path to the base directory.

7. **Dependencies:**
   - Include a `requirements.txt` file with necessary dependencies.

8. **Documentation:**
   - Include comments within the code for clarity.
   - Provide a README file with usage instructions and examples.

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


class GenerateTestCases(dspy.Signature):
    """Generate test cases for the changes made in the PR.

    Make sure to include all the relevant imports.
    Prefer import forms that you can see already done in the code.
    Prefer key focus test cases rather than many test cases.
    Include at max 3 test cases.
    """

    diff_content: str = dspy.InputField(desc="Content of the diff file")
    pr_context: str = dspy.InputField(desc="Context of the PR")
    test_cases: str = dspy.OutputField(
        desc="Generated test cases (only python code output - no tags)")


class MergeTestsDecision(dspy.Signature):
    """Merge the test cases into the existing test file.
    Find the proper way to merge a good new test case into the existing test file.

    Choose between
    1) Add new test methods (newTestClass.newTestMethod) directly into the file as it is. \
       If newTestClass.newTestMethod does not exist, it will be created. (ADD)\
    2) Append the test method body to existing test methods, do not add new test methods \
       There must be an existing test method with the exact same parameters, and performs similar test, \
       in order to be appended (APPEND)\

    """

    new_test_case: str = dspy.InputField(desc="New test case to be merged")
    existing_test_file: str = dspy.InputField(
        desc="Summary of the existing test file to merge into")
    merge_decision: str = dspy.OutputField(
        desc="Decision on how to merge the test cases (ADD, APPEND)")
    test_method_mapping: Dict[str, str] = dspy.OutputField(
        desc="Mapping of new test methods to existing test methods for APPEND mode. \
            For example, to append new test method tm_new in class tc_new to existing \
            test method tm_old in test class tm_old, produce a dict \" \
            { 'tc_new.tm_new': 'tc_old.tm_old' } \
            If the test method is not in a class, use the name of the test method.",
        default_factory=dict)


@dataclass
class TestContent:
    content: str
    metadata: Dict[str, Any]
    target_func: Optional[ExtractedFunction] = None
    test_context: Optional[TestContext] = None

    def to_json(self) -> Dict[str, Any]:
        """Serialize TestContent to JSON-compatible dictionary."""
        return {
            "content": self.content,
            "metadata": self.metadata,
            "target_func": self.target_func.to_dict() if self.target_func else None,
            "test_context": self.test_context.to_dict() if self.test_context else None}

    @classmethod
    def from_json(cls, file_path: str) -> 'TestContent':
        """Deserialize TestContent from JSON-compatible dictionary."""
        with open(file_path, "r") as f:
            data = json.load(f)

        return cls(
            content=data["content"],
            metadata=data["metadata"],
            target_func=ExtractedFunction.from_dict(
                data["target_func"]) if data.get("target_func") else None,
            test_context=TestContext.from_dict(
                data["test_context"]) if data.get("test_context") else None)


class GeneratorOfTests(IsolatedEnvironment):
    def __init__(
            self,
            pr_patch: PRPatch,
            base_dir: str,
            MODEL_NAME: str = "groq/llama-3.3-70b-versatile",
            temperature: float = 1.0,
            abs_custom_dockerfile_path: str = None,
            min_time_between_tests_sec: int = 0,
            test_folder_name: str = None,
            helper_dir: str = None,
            *args,
            **kwargs):
        super().__init__(pr_patch, abs_custom_dockerfile_path)
        self.base_dir = Path(base_dir)
        if test_folder_name is None:
            test_folder_name = datetime.now().strftime("%Y_%m_%d__%H_%M")
        self.test_dir = self.base_dir / "test_cases" / \
            test_folder_name / str(self.pr_patch.pr_number)
        self.helper_dir = Path(helper_dir) if helper_dir else None
        self.MODEL_NAME = MODEL_NAME
        self.min_time_between_tests_sec = min_time_between_tests_sec
        self.temperature = temperature
        self._ensure_directories()
        self.token_logger = LLMTokenLogger()
        self.time_logger = TimeLogger(
            logging_dir=self.base_dir / "time" / str(self.pr_patch.pr_number))

    def _ensure_directories(self) -> None:
        try:
            self.test_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            console.log(f"Error creating test directory: {e}")

    def _generate_test_filename(self) -> str:
        next_number = self._get_next_progressive_number()
        return f"test_{next_number}.py"

    def _get_next_progressive_number(self) -> int:
        test_files = [
            f
            for f in self.test_dir.glob('test_*.py')
            if re.fullmatch(r'test_\d+\.py', f.name)
        ]
        test_numbers = [
            int(file.stem.split('_')[1]) for file in test_files
            if file.stem.split('_')[1].isdigit()
        ]
        return max(test_numbers, default=0) + 1

    def _generate_test_content(self) -> TestContent:
        lm = dspy.LM(self.MODEL_NAME,
                     temperature=self.temperature, cache=False)
        dspy.settings.configure(lm=lm)
        generate_tests = dspy.ChainOfThought(GenerateTestCases)
        response = generate_tests(
            diff_content=self.pr_patch.diff,
            pr_context=self.pr_patch.augmented_discussion.summary)
        test_case = response.test_cases
        test_case = self.remove_lines_with_prefix(test_case, "```")
        metadata = {
            "diff_content": self.pr_patch.diff,
            "pr_context": self.pr_patch.augmented_discussion.summary,
            "test_case": test_case
        }
        return TestContent(
            content=test_case,
            metadata=metadata,
        )

    def remove_lines_with_prefix(self, text: str, prefix: str) -> str:
        return "\n".join([line for line in text.split("\n")
                          if not line.startswith(prefix)])

    def generate(self, n: int = 1, force_new: bool = False) -> List[str]:
        """Generate test cases for the PR and returns their names."""
        test_files = []
        for _ in range(n):
            start_time = time.time()
            if not force_new and self._get_next_progressive_number() > n:
                print("Test cases already exist.")
                test_files = test_files = [
                    f.name
                    for f in self.test_dir.glob('test_*.py')
                    if re.fullmatch(r'test_\d+\.py', f.name)
                ]
                return test_files
            try:
                self.token_logger.clear()
                test_filename = self._generate_test_filename()
                log_filename = test_filename.replace('.py', '_errors.log')
                test_result_filename = test_filename.replace(
                    '.py', '_result.json')
                test_result_path = self.test_dir / test_result_filename
                test_content_filepath = self.test_dir / test_filename
                test: TestContent = self._generate_test_content()
                test.content = add_trailing_newline(test.content)
                with open(test_content_filepath, 'w') as f:
                    # add the name of this class to the test file (as comment)
                    f.write(f"# {self.__class__.__name__}\n")
                    f.write(test.content)
                with open(test_result_path, 'w') as f:
                    json.dump(test.to_json(), f, indent=4)

                token_usage = self.token_logger.get_logs_as_list()
                test.metadata['token_usage'] = token_usage
                metadata_filepath = self.test_dir / \
                    f"{test_filename.replace('.py', '_origin.json')}"
                with open(metadata_filepath, 'w') as f:
                    json.dump(test.metadata, f, indent=4)
                test_files.append(test_filename)
                elapsed_time = time.time() - start_time
                sleep_time = max(
                    0, self.min_time_between_tests_sec - elapsed_time)
                time.sleep(sleep_time)
            except Exception as e:
                log_path = self.test_dir / log_filename
                console = Console(file=open(log_path, 'w'), color_system=None)
                console.print(f"Error generating test: {e}")
        return test_files

    def generate_and_integrate(
            self, n: int = 1, force_new: bool = False) -> List[str]:
        """Generate test cases for the PR and returns their names."""
        test_files = []
        for test_id in range(n):
            start_time = time.time()
            if not force_new and self._get_next_progressive_number() > n:
                print("Test cases already exist.")
                test_files = [
                    f.name
                    for f in self.test_dir.glob('test_*.py')
                    if re.fullmatch(r'test_\d+\.py', f.name)
                ]
                test_result_files = [
                    f.name
                    for f in self.test_dir.glob('test_*.py')
                    if re.fullmatch(r'test_\d+_result\.json', f.name)
                ]
                for t, tresult in zip(test_files, test_result_files):
                    # if test exists but not integrated, do it here
                    if not (
                        self.test_dir /
                        t.replace(
                            '.py',
                            '_integrated.py')).exists():
                        test_content = (self.test_dir / t).read_text()
                        test_target_funcs = json.load(
                            (self.test_dir / tresult)).get('target_func', None)
                        test_context = json.load(
                            (self.test_dir /
                             tresult)).get(
                            'test_context',
                            None)
                        self._integrate(
                            force_new,
                            t,
                            test_content,
                            test_target_funcs,
                            test_context)
                return test_files
            try:
                self.token_logger.clear()
                test_filename = self._generate_test_filename()
                log_filename = test_filename.replace('.py', '_errors.log')
                log_path = self.test_dir / log_filename
                test_result_filename = test_filename.replace(
                    '.py', '_result.json')
                test_result_path = self.test_dir / test_result_filename
                test_content_filepath = self.test_dir / test_filename
                test: TestContent = self._generate_test_content()
                test.content = add_trailing_newline(test.content)
                with open(test_content_filepath, 'w') as f:
                    # add the name of this class to the test file (as comment)
                    f.write(f"# {self.__class__.__name__}\n")
                    f.write(test.content)
                with open(test_result_path, 'w') as f:
                    json.dump(test.to_json(), f, indent=4)

                # Replace token_usage with logger output
                token_usage = self.token_logger.get_logs_as_list()
                test.metadata['token_usage'] = token_usage
                metadata_filepath = self.test_dir / \
                    f"{test_filename.replace('.py', '_origin.json')}"
                with open(metadata_filepath, 'w') as f:
                    json.dump(test.metadata, f, indent=4)

                test_files.append(test_filename)

                self.time_logger.log_event(
                    pr_number=self.pr_patch.pr_number,
                    test_id=test_id,
                    event_type="start",
                    component="test_integration",
                )

                # === Integrate the test file back into the regression test suite ===
                self._integrate(
                    force_new,
                    test_filename,
                    test.content,
                    test.target_func,
                    test.test_context)
                # === End of integration ===
                self.time_logger.log_event(
                    pr_number=self.pr_patch.pr_number,
                    test_id=test_id,
                    event_type="end",
                    component="test_integration",
                )

                elapsed_time = time.time() - start_time
                sleep_time = max(
                    0, self.min_time_between_tests_sec - elapsed_time)
                time.sleep(sleep_time)
            except ValueError as ve:
                msg = str(ve)
                if "No test context found for the target function" in msg:
                    console.log(
                        f"Skipping {test_filename} generation because test context is not found for the target func.")
                    Console(file=open(log_path, 'w'), color_system=None).print(f"Error generating test: {ve}")
                else:
                    raise
            except Exception as e:
                Console(file=open(log_path, 'w'), color_system=None).print(f"Error generating test: {e}")
        return test_files

    def _integrate(self, force_new, test_filename, test_content,
                   target_func: ExtractedFunction, test_context: TestContext):
        merged_test_funcs: Set[ExtractedFunction] = self._integrate_test_file(
            test_content=test_content,
            test_filename=test_filename,
            force_new=force_new,
            target_func=target_func,
            test_context=test_context
        )

        def sanitize_list_of_triplets(
                triplets: List[Tuple]) -> List[Tuple]:
            """Sanitize the list of triplets covert all to strings.

            For each element in triplets, convert it to a string if it is not
            already. This is needed in case one element is AST.Function which
            is not serializable to JSON.
            """
            new_triplets = []
            for triplet in triplets:
                new_triplet = []
                for elem in triplet:
                    # if elem is None, append None
                    # will be converted to null in JSON
                    if elem is None:
                        new_triplet.append(None)
                    elif isinstance(elem, str):
                        new_triplet.append(elem)
                    else:
                        new_triplet.append(elem.name if hasattr(
                            elem, 'name') else str(elem))
                new_triplets.append(tuple(new_triplet))
            return new_triplets

        # Save merged_test_funcs to a file, run_integrate_test will use it
        # to only run the just integrated test functions
        if merged_test_funcs:
            merged_test_funcs_path = self.test_dir / \
                f"{test_filename.replace('.py', '_integrated_test_funcs.json')}"
            with open(merged_test_funcs_path, 'w') as f:
                merged_test_funcs = list(merged_test_funcs)
                # format merged_test_funcs
                fmt_funcs = [
                    [self._get_path_of_existing_test_in_context(
                        target_func=target_func, test_context=test_context
                    ),
                        func.class_name, func.func_name]
                    for func in merged_test_funcs]
                # sanitize names
                fmt_funcs = sanitize_list_of_triplets(fmt_funcs)
                json.dump(fmt_funcs, f, indent=4)

    def _integrate_test_file(self, test_content: str, test_filename: str,
                             force_new: bool, target_func: ExtractedFunction,
                             test_context: TestContext) -> Optional[
            Set[ExtractedFunction]]:
        """
        Integrate the generated test file back into the regression test suite.

        First find the test file to be merged into, then ask the LLM to merge.
        """

        lm = dspy.LM(
            self.MODEL_NAME, temperature=self.temperature, cache=False)
        dspy.settings.configure(
            lm=lm,
            adapter=dspy.JSONAdapter())

        merge_tests_cot = dspy.ChainOfThought(MergeTestsDecision)
        # Find the test file to be merged into
        test_path = self._get_path_of_existing_test_in_context(
            target_func=target_func, test_context=test_context)

        # Retrieve the existing test file content from docker
        image_name = self._get_image_name()
        container = None
        merged_test_funcs = None
        try:
            client = docker.from_env()
            abs_path_test_case = self.test_dir.resolve()
            container = client.containers.run(
                image=image_name,
                detach=True,
                remove=False,
                tty=True,
                command=["tail", "-f", "/dev/null"],
                volumes={
                    abs_path_test_case: {
                        'bind': "/opt/tmp_output/",
                        'mode': 'rw'
                    }
                },
                working_dir=f"/workspace",
            )
            existing_test_content = read_from_container_file(
                container,
                test_path
            )

            merged_test_file = self.test_dir / \
                test_filename.replace('.py', '_integrated.py')
            merged_test_funcs_path = self.test_dir / \
                f"{test_filename.replace('.py', '_integrated_test_funcs.json')}"
            if not force_new and (not merged_test_file.exists() or
                                  not merged_test_funcs_path.exists()):
                # Merge the new test case into the existing test file
                response = merge_tests_cot(
                    new_test_case=test_content,
                    existing_test_file=shrink_context_size_no_marker(
                        file_content_str=existing_test_content,
                        lines_of_interest=[],
                        file_extension="py",
                    )
                )
                self.token_logger.log(lm=lm, stage=MergeTestsDecision)
                console.log(f"Merge decision: {response.merge_decision}")
                try:
                    ast.parse(test_content)
                except Exception as e:
                    console.log(
                        f"Generated new test file has syntax error: {e}")
                    raise e
                try:
                    merged_test_content, merged_test_funcs = merge_tests(
                        new_src=test_content, base_src=existing_test_content,
                        mode=response.merge_decision,
                        mapping=response.test_method_mapping)
                    ast.parse(merged_test_content)
                    console.log(
                        f"Merged into test functions: {merged_test_funcs}")
                except Exception as e:
                    console.log(f"Error merging test files: {e}")
                    file_integration_error_path = self.test_dir / \
                        f"{test_filename.replace('.py', '_integration_error.yaml')}"
                    data = {
                        "error": str(e),
                        "stacktrace": traceback.format_exc(),
                    }
                    with open(file_integration_error_path, 'w') as f:
                        yaml.dump(data, f, indent=2, default_style='|')
                    raise e
                # Save the merged test file
                with open(merged_test_file, 'w') as f:
                    f.write(f"# MERGED using {response.merge_decision} mode\n")
                    f.write(f"# {test_path}\n")
                    f.write(merged_test_content)
            else:
                # If the merged test file already exists, just read it
                merged_test_content = merged_test_file.read_text()

                # If the merged test functions file exists, load the functions
                with open(merged_test_funcs_path, 'r') as f:
                    merged_test_funcs_json = json.load(f)
                    merged_test_funcs: Set[ExtractedFunction] = set(
                        [ExtractedFunction(func[1], func[2]) for
                         func in merged_test_funcs_json])

            # Write the merged test file into the container for testing
            write_to_container_file(
                container,
                test_path,
                merged_test_content
            )

            # produce a diff file to be saved in the integrated_test_dir
            command = f"git diff --output=/opt/tmp_output/{test_filename.replace('.py', '.patch')} {test_path}"
            output = execute_command(
                container, command=command.split(),
                suppress=True,
                workdir=f"/opt/{self.pr_patch.repo_name}",
            )
            console.log(output)

        except Exception as e:
            console.log(f"Error integrating test file: {e}")
        finally:
            if container:
                container.stop()
                container.remove()
                return merged_test_funcs

    def _get_path_of_existing_test_in_context(
            self,
            target_func: Optional[ExtractedFunction] = None,
            test_context: Optional[TestContext] = None) -> str:
        if target_func is not None and test_context is not None:
            test_path, _, _, _ = test_context.most_common_test_context(
                target_func)
        else:
            # Right now we need both to integrate a standlone test case back
            # into an existing test file
            raise Exception(
                "Either target_func or test_context must be provided to get the path of existing test.")

        def clean_path(p): return re.sub(
            r'build-install[/\\].*?site-packages[/\\]', '', p)
        test_path = clean_path(test_path)
        # make test_path absolute in the container
        test_path = f"/opt/{self.pr_patch.repo_name}/{test_path}" \
            if not test_path.startswith("/") else test_path

        return test_path

    def run_test(self, test_name: str) -> None:
        self._dry_run_execution_environment()
        image_name = self._get_image_name()
        container = None
        try:
            client = docker.from_env()
            abs_test_dir = self.test_dir.resolve()
            abs_path_test_case = (self.test_dir / test_name).resolve()
            container = client.containers.run(
                image=image_name,
                detach=True,
                remove=False,
                tty=True,
                command=["tail", "-f", "/dev/null"],
                volumes={
                    abs_test_dir: {
                        'bind': '/opt/coverage_output',
                        'mode': 'rw'
                    },
                    abs_path_test_case: {
                        'bind': f'/opt/{self.pr_patch.repo_name}/test/{test_name}',
                        'mode': 'ro'
                    }
                },
                working_dir=f"/workspace",
            )
            # clean workspace
            command = "rm -rf /workspace/*"
            output = execute_command(
                container, command=command.split(),
                suppress=True)
            console.log(output)

            # # install pytest-timeout incase it is not installed
            # command = "pip install --no-cache-dir pytest-timeout"
            # output = execute_command(
            #     container, command=command.split(),
            #     suppress=True,
            #     workdir="/workspace")
            # console.log(output)

            # compute the coverage
            command = (
                f"timeout {120} python3 -m pytest --cov-report xml:coverage.xml "
                f"--cov=/opt/{self.pr_patch.repo_name} /opt/{self.pr_patch.repo_name}/test/{test_name}"
            )
            output = execute_command(
                container, command=command.split(),
                suppress=True,
                workdir="/workspace")
            console.log(truncate(output))
            with open(self.test_dir / f"{test_name.replace('.py', '_runtime.log')}", 'w') as f:
                f.write(output)
            # copy the coverage file to the host
            # execute command to copy the coverage file to the host in the
            # /opt/qiskit/test_cases directory
            coverage_name = test_name.replace('.py', '_coverage.xml')
            command = f"cp /workspace/coverage.xml /opt/coverage_output/{coverage_name}"
            output = execute_command(
                container, command=command.split(),
                suppress=True)
            console.log(output)
            # print the output
            console.log(container.logs().decode())
        except Exception as e:
            console.log(f"Error running the container: {e}")
        finally:
            if container:
                container.stop()
                container.remove()

    def run_integrated_test(self, test_name: str) -> None:

        # if patch file does not exist, skip the test
        patch_path = (
            self.test_dir / test_name.replace('.py', '.patch')).resolve()
        if not patch_path.exists():
            console.log(
                f"Patch file not found: {patch_path}, skipping test {test_name}")
            raise FileNotFoundError(f"Patch file not found: {patch_path}")

        # if integrated test funcs file does not exist, skip the test
        merged_test_funcs_path = self.test_dir / \
            f"{test_name.replace('.py', '_integrated_test_funcs.json')}"
        if not merged_test_funcs_path.exists():
            console.log(
                f"Integrated test funcs file not found: {merged_test_funcs_path}, skipping test {test_name}")
            raise FileNotFoundError(
                f"Integrated test funcs file not found: {merged_test_funcs_path}")

        self._dry_run_execution_environment()
        image_name = self._get_image_name()
        container = None
        try:
            client = docker.from_env()
            abs_test_dir = self.test_dir.resolve()
            container = client.containers.run(
                image=image_name,
                detach=True,
                remove=False,
                tty=True,
                command=["tail", "-f", "/dev/null"],
                volumes={
                    abs_test_dir: {
                        'bind': '/opt/tmp_output',
                        'mode': 'rw'
                    }
                },
                working_dir=f"/workspace",
            )
            # clean workspace
            command = "rm -rf /workspace/*"
            output = execute_command(
                container, command=command.split(),
                suppress=True)
            console.log(output)

            # read patch and retrieve full integrated test file path
            integrated_test_path = f"/opt/{self.pr_patch.repo_name}/" + \
                PatchSet.from_filename(patch_path)[0].path

            # or, read the integrated test funcs file and only run specific
            # merged test funcs
            with open(merged_test_funcs_path, 'r') as f:
                merged_test_funcs = json.load(f)
            # format into pytest format
            def fmt(
                f): return f[0] + "::" + (f[1] + "::" if f[1] else "") + f[2]
            fmt_tests = " ".join([fmt(full_func)
                                 for full_func in merged_test_funcs])

            # apply patch
            command = f"git apply /opt/tmp_output/{test_name.replace('.py', '.patch')}"
            output = execute_command(
                container, command=command.split(),
                suppress=True,
                workdir=f"/opt/{self.pr_patch.repo_name}")
            console.log(output)

            # install pytest-timeout incase it is not installed
            # command = "pip install --no-cache-dir pytest-timeout"
            # output = execute_command(
            #     container, command=command.split(),
            #     suppress=True,
            #     workdir="/workspace")
            # console.log(output)

            # compute the coverage
            command = f"timeout {600} python3 -m pytest --cov-report xml:coverage.xml --cov=/opt/{self.pr_patch.repo_name} {fmt_tests}"
            output = execute_command(
                container, command=command.split(),
                suppress=True,
                workdir="/workspace")
            console.log(truncate(output))
            with open(self.test_dir / f"{test_name.replace('.py', '_integrated_runtime.log')}", 'w') as f:
                f.write(output)
            # copy the coverage file to the host
            # execute command to copy the coverage file to the host in the
            # /opt/qiskit/test_cases directory
            coverage_name = test_name.replace(
                '.py', '_integrated_coverage.xml')
            command = f"cp /workspace/coverage.xml /opt/tmp_output/{coverage_name}"
            output = execute_command(
                container, command=command.split(),
                suppress=True)
            console.log(output)
            # print the output
            console.log(container.logs().decode())
        except Exception as e:
            console.log(f"Error running the container: {e}")
            raise e
        finally:
            if container:
                container.stop()
                container.remove()

    def run_test_exception(
            self, test_name: str, cov_files: List[str] = None) -> None:

        def write_to_coveragerc_file() -> Tuple[str, str]:
            rnd_suffix = str(uuid.uuid4())[:8]
            file_path = "/tmp/.coveragerc_custom_" + rnd_suffix
            # delete /tmp/.coveragerc_custom if it exists
            if os.path.exists(file_path):
                os.remove(file_path)

            if cov_files:
                with open(file_path, 'w') as f:
                    f.write("[run]\ninclude =")
                    f.write(
                        "\n\t".join(
                            [f"/opt/{self.pr_patch.repo_name}/{f}"
                             for f in cov_files]))
                    f.write("\n")
            return file_path, ".coveragerc_custom_" + rnd_suffix

        self._dry_run_execution_environment()
        image_name = self._get_image_name()
        container = None
        covrc_path, covrc_name = write_to_coveragerc_file()
        try:
            client = docker.from_env()
            abs_test_dir = self.test_dir.resolve()
            abs_path_test_case = (self.test_dir / test_name).resolve()
            container = client.containers.run(
                image=image_name,
                detach=True,
                remove=False,
                tty=True,
                command=["tail", "-f", "/dev/null"],
                volumes={
                    abs_test_dir: {
                        'bind': '/opt/coverage_output',
                        'mode': 'rw'
                    },
                    abs_path_test_case: {
                        'bind': f'/opt/{self.pr_patch.repo_name}/test/{test_name}',
                        'mode': 'ro'
                    },
                    covrc_path: {
                        'bind': f'/opt/{self.pr_patch.repo_name}/{covrc_name}',
                        'mode': 'rw'
                    }
                },
                working_dir=f"/workspace",
            )
            # clean workspace
            command = "rm -rf /workspace/*"
            output = execute_command(
                container, command=command.split(),
                suppress=True)
            console.log(output)

            try:
                # compute the coverage
                env = {}
                command = f"timeout {120} coverage run -m pytest /opt/{self.pr_patch.repo_name}/test/{test_name}"
                if cov_files:
                    env = {
                        "COVERAGE_RCFILE": f"/opt/{self.pr_patch.repo_name}/{covrc_name}"}

                runtime_output = execute_command(
                    container, command=command.split(),
                    suppress=False,
                    workdir="/workspace",
                    env=env)
                console.log(runtime_output)

            except RuntimeError as e:
                runtime_output = str(e)  # if pytest failed, output is empty
                raise e
            finally:
                command = "coverage xml -o /workspace/coverage.xml"
                output = execute_command(
                    container, command=command.split(),
                    suppress=True,
                    workdir="/workspace",
                    env=env)
                console.log(truncate(output))

                with open(self.test_dir / f"{test_name.replace('.py', '_runtime.log')}", 'w') as f:
                    f.write(runtime_output)
                # copy the coverage file to the host
                # execute command to copy the coverage file to the host in the
                # /opt/qiskit/test_cases directory
                coverage_name = test_name.replace('.py', '_coverage.xml')
                command = f"cp /workspace/coverage.xml /opt/coverage_output/{coverage_name}"
                output = execute_command(
                    container, command=command.split(),
                    suppress=True)
                console.log(output)

                # remove the custom cov file on the host
                os.remove(covrc_path)
                # print the output
                console.log(container.logs().decode())
        except Exception as e:
            console.log(f"Error running the container: {e}")
            raise e
        finally:
            if container:
                container.stop()
                container.remove()

    def run_test_for_output_only(self, test_name: str) -> str:
        self._dry_run_execution_environment()
        image_name = self._get_image_name()
        container = None
        try:
            client = docker.from_env()
            abs_path_test_case = (self.test_dir / test_name).resolve()
            container = client.containers.run(
                image=image_name,
                detach=True,
                remove=False,
                tty=True,
                command=["tail", "-f", "/dev/null"],
                volumes={
                    abs_path_test_case: {
                        'bind': f'/opt/{self.pr_patch.repo_name}/test/{test_name}',
                        'mode': 'ro'
                    }
                },
                working_dir=f"/workspace",
            )
            # clean workspace
            command = "rm -rf /workspace/*"
            output = execute_command(
                container, command=command.split(),
                suppress=True)
            console.log(output)
            # run the test without collecting coverage
            command = f"python3 -m pytest /opt/{self.pr_patch.repo_name}/test/{test_name}"
            try:
                output = execute_command(
                    container, command=command.split(),
                    suppress=False)
            except RuntimeError as e:
                # pytest command failed
                raise e
            finally:
                console.log(truncate(output))
            # print the output
            console.log(container.logs().decode())
            return output
        except Exception as e:
            console.log(f"Error running the container: {e}")
            raise e
        finally:
            if container:
                container.stop()
                container.remove()

    def compute_relevance(self, test_name: str) -> None:
        coverage_path = self.test_dir / \
            f"{test_name.replace('.py', '_coverage.xml')}"
        # make sure that the coverage file exists
        if not coverage_path.exists():
            console.log(f"Coverage file not found: {coverage_path}")
            self.run_test(test_name=test_name)
        abs_coverage_path = coverage_path.resolve()
        output_path = self.test_dir / \
            f"{test_name.replace('.py', '_relevance.json')}"
        abs_output_path = output_path.resolve()
        # make sure that the diff file exists (if not download under the hood)
        _ = self.pr_patch.diff
        self._compute_relevance(
            abs_coverage_path=abs_coverage_path,
            abs_output_path=abs_output_path,
        )

    def get_coverage_increment(self, test_name: str) -> Dict[str, Any]:
        output_path = self.test_dir / \
            f"{test_name.replace('.py', '_coverage_increment.json')}"
        if not output_path.exists():
            self.compute_coverage_increment(test_name=test_name)
        with open(output_path, 'r') as file:
            return json.load(file)

    def compute_coverage_increment(
            self, test_name: str, force_new=False) -> None:
        """compute the differnece between the set of coverd lines by the patch coverage and the lines covered by the given test"""

        output_path = self.test_dir / \
            f"{test_name.replace('.py', '_coverage_increment.json')}"
        if output_path.exists() and not force_new:
            console.log(f"Coverage increment already computed: {output_path}")

        test_coverage_path = self.test_dir / \
            f"{test_name.replace('.py', '_relevance.json')}"
        # if the relevance file is not there, compute it using the coverage
        # file
        if not test_coverage_path.exists() or force_new:
            console.log(
                f"Relevance file not found or force recomputing: {test_coverage_path}")
            self.compute_relevance(test_name=test_name)
        with open(test_coverage_path, 'r') as file:
            test_coverage_data = json.load(file)
        test_coverage = flatten_coverage_datapoint(test_coverage_data)
        lines_covered_by_test = [
            line for line in test_coverage if line.endswith(":c")]

        # get coverage of this PR
        pc = PatchCoverage(pr_patch=self.pr_patch)
        dev_coverage_data = pc.patch_coverage_data
        dev_coverage = flatten_coverage_datapoint(dev_coverage_data)
        lines_missed_by_dev = [
            line for line in dev_coverage if line.endswith(":m")]

        n_total_lines = len(dev_coverage)

        unique_lines_covered = set([
            line for line in test_coverage if line.endswith(":c")]) - set([
                line for line in dev_coverage if line.endswith(":c")])

        output_cov_increment = {
            "n_total_lines": n_total_lines,
            "line_missed_by_dev": lines_missed_by_dev,
            "n_lines_missed_by_dev": len(lines_missed_by_dev),
            "n_lines_covered_by_test": lines_covered_by_test,
            "patch_coverage_test": float(
                len(lines_covered_by_test) / n_total_lines) * 100,
            "unique_lines_covered": list(unique_lines_covered),
            "n_unique_lines_covered": len(unique_lines_covered),
            "perc_coverage_increment": float(
                len(unique_lines_covered) / n_total_lines) * 100,
        }
        with open(output_path, 'w') as file:
            json.dump(output_cov_increment, file, indent=4)
        console.log(f"Coverage increment computed: {output_path}")


@click.command()
@click.option('--pr_number', required=True, type=int,
              help="Pull request number.")
@click.option('--base-dir', required=True, type=click.Path(),
              help="Path to the base directory.")
@click.option('--repo', required=True,
              help="Full repository identifier (e.g., Qiskit/qiskit).")
def main(pr: str, base_dir: str, repo: str) -> None:
    try:
        pr_patch = PRPatch(
            pr_number=123,
            repo_owner=repo.split('/')[0],
            repo_name=repo.split('/')[1],
            base_dir=base_dir)
        generator = GeneratorOfTests(pr_patch=pr_patch, base_dir=base_dir)
        generator.generate()
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


if __name__ == "__main__":
    main()
