import dspy
import docker
import shlex
import json
import uuid
import random
from collections import Counter
from typing import Any, Dict, Tuple, List, Optional
from pathlib import Path
from rich.console import Console
from approach.base.generator_of_tests import GeneratorOfTests, TestContent
from approach.coverage.patch_coverage import PatchCoverage
from approach.base.test_context import TestContextDynamic
from approach.docker_handling.docker_utils import execute_command
from approach.utils.test_extractor import ExtractedFunction
from approach.utils.time_logger import TimeLogger

console = Console(color_system=None)


class SummarizeUncoveredLines(dspy.Signature):
    """Inspect and summarize the lines in modified by the PR that
    are uncovered by existing regression test suites.
    """

    diff_content: str = dspy.InputField(desc="Content of the diff file")
    pr_context: str = dspy.InputField(desc="Context of the PR")
    uncovered_line: str = dspy.InputField(
        desc="Uncovered segment in the PR. Each uncovered line is marked with the `# UNCOVERED` ending comment.")
    summary: str = dspy.OutputField(
        desc="Summary of the uncovered lines in the PR. \
            Focus on WHY the lines are uncovered. That is, explain why the conditions (branches) guarding it \
            are never satisfied by the existing tests, leading to the # UNCOVERED lines. \
            The summary will be used to generate/augment test cases to cover the lines missing coverage."
    )


class GenerateTestCases(dspy.Signature):
    """Generate test cases for the changes made in the PR.
    You are provided with a summary of the PR, the diff content,
    the lines modified by the PR that are uncovered by existing regression test suites,
    an explanation of why these lines are uncovered
    and some information about existing test classes and methods that are relevant to the PR.

    Make sure to include all the relevant imports.

    """

    pr_context: str = dspy.InputField(desc="Context of the PR")
    # diff_content: str = dspy.InputField(desc="Content of the diff file")

    # uncovered_line: str = dspy.InputField(
    # desc="Uncovered line in the files of the PR. Each uncovered line is
    # marked with the `# UNCOVERED` ending comment.")
    uncovered_summary: str = dspy.InputField(
        desc="Summary of the uncovered lines in the PR.")

    test_path: str = dspy.InputField(
        desc="The full path of the test file for the PR")
    test_class: str = dspy.InputField(
        desc="The Test Class for which a new/modified test for this PR should belong to")
    test_method: str = dspy.InputField(
        desc="A full Test Method of the test class, that is the most relevant to the PR. \
                                       This could be a test method modified by the PR itself, or a test method that is \
                                       the most relevant to the PR.")

    test_cases: str = dspy.OutputField(
        desc="Generated test cases (only python code output - no tags)"
        "Include at max 1 test case."
        "Focus on the uncovered lines."
        "Make sure to include all the relevant imports. Do not leave placeholder imports."
        "The test case should be valid python code, that can be copy-pasted into the test file.")


class FixImports(dspy.Signature):
    """Make sure that the test case imports all the required modules/libaries.

    Make sure to include all the relevant imports.
    """

    test_cases: str = dspy.InputField(desc="Current test cases")
    test_cases_double_checked_for_imports: str = dspy.OutputField(
        desc="Test cases with all the required imports (added if missing)"
    )


class FixRuntimeErrors(dspy.Signature):
    """Fix the runtime errors in the test case based on the crash message.

    Make sure to address all the runtime errors.
    The goal is to generate another test case that addresses the runtime errors, and improve coverage.
    """

    diff_content: str = dspy.InputField(desc="Content of the diff file")
    pr_context: str = dspy.InputField(desc="Context of the PR")
    uncovered_summary: str = dspy.InputField(
        desc="Summary of the uncovered lines in the PR.")
    current_test_case_draft: str = dspy.InputField(
        desc="Current test case draft that needs to be improved.")
    runtime_error_message: str = dspy.InputField(
        desc="Runtime error message from the test case execution.")
    test_case: str = dspy.OutputField(
        desc="Improved test case (only python code output - no tags)"
        "Include at max 1 test case."
        "Keep the original test case functionality."
        "Make sure to address all the runtime errors."
    )


class FixRuntimeErrorsButCoverageAdded(dspy.Signature):
    """Fix the runtime errors in the test case based on the crash message.

    The test case added some coverage, but still has runtime errors.
    The goal is to preserve the coverage added by the test case, but also address the runtime errors.
    """

    diff_content: str = dspy.InputField(desc="Content of the diff file")
    pr_context: str = dspy.InputField(desc="Context of the PR")
    current_test_case_draft: str = dspy.InputField(
        desc="Current test case draft that needs to be improved.")
    runtime_error_message: str = dspy.InputField(
        desc="Runtime error message from the test case execution.")
    uncovered_lines: str = dspy.InputField(
        desc="Uncovered lines in the files of the PR. Each uncovered line is marked with the `# UNCOVERED` ending comment.")
    test_case: str = dspy.OutputField(
        desc="Improved test case (only python code output - no tags)"
        "Include at max 1 test cases."
        "Keep the original test case functionality."
        "Make sure to address all the runtime errors."
    )


class IncreaseCoverage(dspy.Signature):
    """Increase the coverage of the test case based on the uncovered lines.

    The current test case passes correctly, meaning there is no ImportError, Assertion Error, etc.
    But it doesn't cover any of the uncovered lines in the PR.
    Reflect on the uncovered lines of the PR.
    The goal is to preserve the current test case that passes, but add functionality to cover the uncovered lines.
    """

    diff_content: str = dspy.InputField(desc="Content of the diff file")
    pr_context: str = dspy.InputField(desc="Context of the PR")
    current_test_case_draft: str = dspy.InputField(
        desc="Current test case draft that needs to be improved.")
    uncovered_lines: str = dspy.InputField(
        desc="Uncovered lines in the files of the PR. Each uncovered line is marked with the `# UNCOVERED` ending comment.")
    uncovered_summary: str = dspy.InputField(
        desc="Summary of the uncovered lines in the PR.")
    test_case: str = dspy.OutputField(
        desc="Improved test case (only python code output - no tags)"
        "Include at max 1 test case."
        "Preserve the current test case that passes, but add functionality to cover the uncovered lines.")


class GeneratorBase(GeneratorOfTests):
    def __init__(self, *args,
                 dynamic_test_context=False,
                 runtime_feedback=False,
                 max_feedback=4, **kwargs):
        super().__init__(*args, **kwargs)
        # this flag indicates which Test Context strategy to use
        # true: use the dynamic call chain to find the relevant tests
        # false: use only prompting to find the relevant tests
        self.use_dynamic_test_context = dynamic_test_context
        self.runtime_feedback = runtime_feedback
        self.dynamic_failed = False
        self.max_feedback = max_feedback

        # the default text context to be used by the generator instance
        # Note: this is set to llm-generated / dynamic test context
        # depending on the
        #  1) configuration of the test generator
        #  2) whether dynamic test context generation failed previously
        #  3) whether exception was raised during DTC generation
        # in 2) and 3) we fall back to llm-generated test context
        # Note: it is not guaranteed even when DTC was correctly generated
        # that it will contain the tests for the selected target function
        # (e.g. if the target function is not called by any test)
        # in this scenario, we fall back to the llm-generated test context
        # locally within _generate_test_content
        self.test_context = None

        # Frequency Counter[ExtractedFunction -> int] that maps target functions to
        # the number of uncovered lines in it
        self.target_funcs: Counter[ExtractedFunction] = PatchCoverage(
            pr_patch=self.pr_patch).target_funcs
        assert self.target_funcs, \
            f"No functions with uncovered lines found in the PR patch {self.pr_patch.pr_number}"

        # check if DTC failed previously
        dtc_failed_mark = Path(self.pr_patch.test_context_dir) / \
            f"{self.pr_patch.pr_number}_dtc_failed.mark"
        if dtc_failed_mark.exists():
            console.log(
                f"Dynamic test context generation previously failed for PR \
                    {self.pr_patch.pr_number}.")
            self.dynamic_failed = True

        # Retrieve the test context from the PR patch
        # If dynamic test context is true, use the dynamic call chain to find
        # the relevant tests
        test_context_path = Path(self.pr_patch.test_context_dir) / \
            f"{self.pr_patch.pr_number}_dynamic.json"
        if self.use_dynamic_test_context and \
                not test_context_path.exists() and \
                not self.dynamic_failed:
            try:

                console.log(f"Uncovered regions: {len(self.target_funcs)}")
                assert self.target_funcs, "No uncovered lines found in the PR patch"

                # manually create the dynamic test context
                # Note: if the PR doesn't come with tests, TestContextDynamic falls back to
                # TestContext' llm-promping to select the relevant TEST FILES
                # which introduce undeterministic behavior
                dynamic_tc = TestContextDynamic(
                    pr_patch=self.pr_patch, MODEL_NAME=self.MODEL_NAME)

                test_names = list(dynamic_tc.test_contents.keys())
                console.log(f"Test names: {test_names}")

                # run viztracer on the test files
                call_chain_file_pattern = Path(
                    self.pr_patch.test_context_dir) / f"{self.pr_patch.pr_number}_call_chains_*.json"

                # if no call chain file is found, we run viztracer
                # run viztracer on the test file
                if not any(
                    call_chain_file_pattern.parent.glob(
                        call_chain_file_pattern.name)):
                    console.log(f"Running viztracer on {test_names}...")
                    self._run_viztracer_on_test(
                        test_names, target_funcs=self.target_funcs)

                # parse the call chains file into the dynamic test context
                dynamic_tc.parse_call_chain_target_funcs(
                    target_funcs=self.target_funcs,
                    call_chain_file_pattern=call_chain_file_pattern)

                # store the dynamic test context to disk
                dynamic_tc.to_json(test_context_path)

            except Exception as e:
                console.log(f"Dynamic test context generation failed: {e}")
                self.dynamic_failed = True

                # store a mark to disk
                dtc_failed_mark.touch()

        # If use DTC flag is true and dynamic generation didn't fail
        if self.use_dynamic_test_context and not self.dynamic_failed:
            self.test_context = self.pr_patch.test_context_dynamic
            # if no test is found to call the focal method,
            # then we fall back to the static test context
            if self.test_context.is_empty:
                console.log(
                    "No test file found to call the focal method.")
                console.log(
                    "Falling back to LLM test context generation.")
                self.test_context = self.pr_patch.test_context
        else:
            if self.use_dynamic_test_context and self.dynamic_failed:
                console.log(
                    "Using LLM test context (no valid dynamic call chain found or failed).")
            else:
                console.log("Using LLM test context by configuration")
            self.test_context = self.pr_patch.test_context

    def _generate_test_content(self) -> TestContent:
        # DSPy's ChainOfThought
        # DSPy.ChainOfThought provides structured prompting with reasoning steps
        #    - It automatically prompts the model to explain its reasoning step-by-step
        #    - Enforces input/output field structure defined in Signature classes
        #    - Handles parsing of responses into well-defined objects
        #    - Can be optimized/tuned using DSPy's teleprompter
        test_id = "test-" + str(uuid.uuid4())[:6]  # Unique test ID for logging
        self.time_logger.log_event(
            pr_number=self.pr_patch.pr_number,
            test_id=test_id,
            event_type="start",
            component="test_generation"
        )
        # Initialize the model and conversation
        lm = dspy.LM(model=self.MODEL_NAME,
                     temperature=self.temperature, cache=False)
        dspy.settings.configure(lm=lm)

        # Select a target func based on the frequency
        # We only computed test context for the top 3 functions
        target_func, uncovered_func_lines = self.pick_target_func(top_k_only=3)
        console.log(f"Selected target function: {target_func}")

        # By default, in this run of _generate_test_content, we use the
        # test context that was set in the constructor
        test_context_used = self.test_context

        # Summarize uncovered lines
        CoTSummarizeUncovered = dspy.ChainOfThought(SummarizeUncoveredLines)
        response = CoTSummarizeUncovered(
            diff_content=self.pr_patch.diff,
            uncovered_line=uncovered_func_lines,
            pr_context=self.pr_patch.augmented_discussion.summary)
        self.uncovered_lines_summary = response.summary
        # Log token usage for SummarizeUncoveredLines
        self.token_logger.log(lm=lm, stage=SummarizeUncoveredLines)

        # Retrieve test context
        # dynamic_test_context_unavailable:
        # This flag indicates whether dynamic test context is unavailable for
        # the specific target function, in this run of _generate_test_content
        test_context_used, dynamic_test_context_unavailable, test_path, test_class, test_method = \
            self._retrieve_test_context(target_func, test_context_used)

        CoTGenerateTest = dspy.ChainOfThought(GenerateTestCases)
        response = CoTGenerateTest(
            # diff_content=self.pr_patch.diff,
            # uncovered_line=self.pr_patch.uncovered_lines_summary,
            uncovered_summary=self.uncovered_lines_summary,
            pr_context=self.pr_patch.augmented_discussion.summary,
            test_path=test_path,
            test_class=test_class,
            test_method=test_method)
        test_case = response.test_cases
        test_case = self.remove_lines_with_prefix(test_case, "```")
        # Log token usage for GenerateTestCases
        self.token_logger.log(lm=lm, stage=GenerateTestCases)
        self.time_logger.log_event(
            pr_number=self.pr_patch.pr_number,
            test_id=test_id,
            event_type="end",
            component="test_generation"
        )

        # fix imports
        # fix_imports = dspy.ChainOfThought(FixImports)
        # response = fix_imports(test_cases=test_case)
        # test_case = response.test_cases_double_checked_for_imports
        # test_case = self.remove_lines_with_prefix(test_case, "```")

        # runtime feedback
        metadata_fb = None
        if self.runtime_feedback:
            self.time_logger.log_event(
                pr_number=self.pr_patch.pr_number,
                test_id=test_id,
                event_type="start",
                component="runtime_feedback"
            )
            test_case, metadata_fb = self._runtime_and_coverage_feedback(
                test_case=test_case, lm=lm, target_func=target_func
            )
            self.time_logger.log_event(
                pr_number=self.pr_patch.pr_number,
                test_id=test_id,
                event_type="end",
                component="runtime_feedback"
            )

        metadata = {
            "diff_content": self.pr_patch.diff,
            "uncovered_line": uncovered_func_lines,
            "uncovered_summary": self.uncovered_lines_summary,
            "pr_context": self.pr_patch.augmented_discussion.summary,
            "test_path": test_path,
            "test_class": test_class,
            "test_method": test_method,
            "dynamic_test_context": self.use_dynamic_test_context,
            "dynamic_failed": self.dynamic_failed,
            "target_func": str(target_func),
            "dynamic_test_context_unavailable": dynamic_test_context_unavailable,
            "test_case": test_case,
        }

        if metadata_fb:
            metadata["runtime_error_message"] = metadata_fb.get(
                "runtime_error_message", None)
            metadata["fixed_test_case"] = metadata_fb.get(
                "fixed_test_case", None)
            metadata["provenance"] = metadata_fb.get("provenance", None)
            metadata["num_feedback_attempts"] = metadata_fb.get(
                "num_feedback_attempts", None)

        return TestContent(
            content=test_case,
            metadata=metadata,
            target_func=target_func,
            test_context=test_context_used
        )

    def _retrieve_test_context(self, target_func, test_context_used):
        dynamic_test_context_unavilable = False
        try:
            test_path, test_class, _, test_method = test_context_used.most_common_test_context(
                target_func)
        except ValueError as e:
            # If no (dynamic) test context is available for the target function
            # fall back to LLM test context
            if self.use_dynamic_test_context:
                assert isinstance(self.test_context, TestContextDynamic), \
                    "The Test context non-available should be of type TestContextDynamic"
                console.log(
                    f"Failed to retrieve dynamic test context for target function {target_func}: {e}")
                console.log("Falling back to LLM test context generation.")
                dynamic_test_context_unavilable = True
                # If dynamic test context is unavailable, we fall back to the LLM
                # test context
                test_context_used = self.pr_patch.test_context
                test_path, test_class, _, test_method = test_context_used.most_common_test_context(
                    target_func)
            else:
                console.log(f"Failed to retrieve test context for target function {target_func}: {e}")
                raise e
        except Exception as e:
            console.log(
                f"Failed to retrieve test context for target function {target_func}: {e}")
            console.log(
                "Test Context type being used: ",
                type(test_context_used))
            console.log("Test Context: ", test_context_used)
            raise e
        return test_context_used, dynamic_test_context_unavilable, test_path, test_class, test_method

    def pick_target_func(self, top_k_only: int = 3) -> Tuple[ExtractedFunction, str]:
        if not self.target_funcs:
            raise ValueError("self.target_funcs is empty")

        # Sort by weight (descending) and keep only the top‑k when requested
        sorted_items = sorted(self.target_funcs.items(), key=lambda kv: kv[1], reverse=True)
        if top_k_only > 0:
            sorted_items = sorted_items[:top_k_only]

        funcs, weights = zip(*sorted_items)  # unzip into two parallel tuples
        target_func = random.choices(funcs, weights=weights, k=1)[0]

        uncovered_func_lines = self._uncovered_func_lines(target_func)
        return target_func, uncovered_func_lines

    def _uncovered_func_lines(self, target_func):
        uncovered_func_lines = PatchCoverage(
            pr_patch=self.pr_patch).create_uncovered_lines_summary_within_target_func(target_func)

        return uncovered_func_lines

    def _runtime_feedback(self, test_case: str, lm=None):
        """
        Fix the runtime errors in the test case based on the crash message.
        """

        metadata = {}

        # store as tmp file
        test_name = self._generate_test_filename()
        tmp_test_name = f"__tmp__{test_name}"
        path_tmp_test = self.test_dir / tmp_test_name
        with open(path_tmp_test, "w") as f:
            f.write(test_case)

        num_feedback_attempts = 0
        while num_feedback_attempts <= self.max_feedback:
            # Run the test and get the runtime error message
            pytest_failed = False
            try:
                pytest_output = self.run_test_for_output_only(
                    test_name=tmp_test_name)
            except RuntimeError as e:
                # If the test fails, get the runtime error message
                pytest_error_msg = str(e)
                pytest_failed = True

            if pytest_failed:
                # Fix the runtime errors
                # breakpoint()
                fix_runtime_errors = dspy.ChainOfThought(FixRuntimeErrors)
                response = fix_runtime_errors(
                    diff_content=self.pr_patch.diff,
                    pr_context=self.pr_patch.augmented_discussion.summary,
                    uncovered_summary=self.uncovered_lines_summary,
                    current_test_case_draft=test_case,
                    runtime_error_message=pytest_error_msg
                )
                test_case = self.remove_lines_with_prefix(
                    response.test_case, "```")
                # Log token usage for FixRuntimeErrors
                if lm is not None:
                    self.token_logger.log(lm=lm, stage=FixRuntimeErrors)

                metadata["runtime_error_message"] = pytest_error_msg
                metadata["fixed_test_case"] = test_case

                num_feedback_attempts += 1
                # store as tmp file
                with open(path_tmp_test, "w") as f:
                    f.write(test_case)
            else:
                break

        return test_case, metadata

    def _runtime_and_coverage_feedback(self, test_case: str,
                                       lm=None,
                                       target_func: ExtractedFunction = None):
        """
        Provide both runtime log and coverage feedback to the LLM

        if error -> fix the error prompt
        if coverage (not increased) -> increase the coverage prompt
        """

        metadata = {}
        provenance = []

        # store as tmp file
        tmp_test_name = f"__tmp__{self._generate_test_filename()}"
        path_tmp_test = self.test_dir / tmp_test_name
        with open(path_tmp_test, "w") as f:
            f.write(test_case)

        num_feedback_attempts = 0
        while num_feedback_attempts < self.max_feedback:
            # Run the test and get the runtime error message
            pytest_failed = False
            try:
                self.run_test_exception(
                    test_name=tmp_test_name,
                    cov_files=self.pr_patch.file_list_after)
            except RuntimeError as e:
                # If the test fails, get the runtime error message
                pytest_error_msg = str(e)
                metadata["runtime_error_message"] = pytest_error_msg
                pytest_failed = True

            # parse the coverage report, force to generate new relevance file
            try:
                self.compute_coverage_increment(tmp_test_name, force_new=True)
                # relevance file path
                relevance_file = self.test_dir / \
                    f"{tmp_test_name.replace('.py', '_relevance.json')}"
                # read the increment json file
                increment_file = self.test_dir / \
                    f"{tmp_test_name.replace('.py', '_coverage_increment.json')}"
                with open(increment_file) as f:
                    cov_incrmt = json.load(f)
                    num_lines_added = cov_incrmt.get("n_unique_lines_covered", 0)
                    lines_added = cov_incrmt.get("unique_lines_covered", [])
                uncovered_func_lines = PatchCoverage(
                    pr_patch=self.pr_patch).create_uncovered_lines_summary_within_target_func_custom(
                    target_func=target_func, json_file_path=relevance_file)
            except Exception as e:
                console.log(
                    f"Failed to compute coverage increment for test {tmp_test_name}: {e}")
                num_lines_added = 0
                lines_added = []
                relevance_file = None

            provenance.append({
                "pytest_failed": pytest_failed,
                "num_lines_added": num_lines_added,
            })

            # If pytest failed, and no coverage is added
            if pytest_failed and num_lines_added == 0:
                # Fix the runtime errors
                fix_runtime_errors = dspy.ChainOfThought(FixRuntimeErrors)
                response = fix_runtime_errors(
                    diff_content=self.pr_patch.diff,
                    pr_context=self.pr_patch.augmented_discussion.summary,
                    uncovered_summary=self.uncovered_lines_summary,
                    current_test_case_draft=test_case,
                    runtime_error_message=pytest_error_msg
                )
                test_case = self.remove_lines_with_prefix(
                    response.test_case, "```")
                # Log token usage for FixRuntimeErrors
                if lm is not None:
                    self.token_logger.log(lm=lm, stage=FixRuntimeErrors)

                metadata["fixed_test_case"] = test_case

                # store as tmp file
                with open(path_tmp_test, "w") as f:
                    f.write(test_case)
                num_feedback_attempts += 1

            # If pytest failed, but coverage is added
            elif pytest_failed and num_lines_added > 0:
                # Fix the runtime errors
                fix_runtime_errors = dspy.ChainOfThought(
                    FixRuntimeErrorsButCoverageAdded)
                response = fix_runtime_errors(
                    diff_content=self.pr_patch.diff,
                    pr_context=self.pr_patch.augmented_discussion.summary,
                    current_test_case_draft=test_case,
                    runtime_error_message=pytest_error_msg,
                    uncovered_lines=uncovered_func_lines
                )

                test_case = self.remove_lines_with_prefix(
                    response.test_case, "```")
                # Log token usage for FixRuntimeErrorsButCoverageAdded
                if lm is not None:
                    self.token_logger.log(
                        lm=lm, stage=FixRuntimeErrorsButCoverageAdded)

                metadata["fixed_test_case"] = test_case

                with open(path_tmp_test, "w") as f:
                    f.write(test_case)
                num_feedback_attempts += 1

            # If pytest passed, but no coverage is added
            elif not pytest_failed and num_lines_added == 0:
                add_coverage = dspy.ChainOfThought(IncreaseCoverage)
                response = add_coverage(
                    diff_content=self.pr_patch.diff,
                    pr_context=self.pr_patch.augmented_discussion.summary,
                    current_test_case_draft=test_case,
                    uncovered_lines=uncovered_func_lines,
                    uncovered_summary=self.uncovered_lines_summary
                )
                test_case = self.remove_lines_with_prefix(
                    response.test_case, "```")
                # Log token usage for IncreaseCoverage
                if lm is not None:
                    self.token_logger.log(lm=lm, stage=IncreaseCoverage)
                metadata["fixed_test_case"] = test_case
                # store as tmp file
                with open(path_tmp_test, "w") as f:
                    f.write(test_case)
                num_feedback_attempts += 1

            # If pytest passed, and coverage is added
            elif not pytest_failed and num_lines_added > 0:
                break

        # add provenance to metadata
        metadata["provenance"] = provenance
        metadata["num_feedback_attempts"] = num_feedback_attempts
        return test_case, metadata

    def _run_viztracer_on_test(
            self, test_names: List[str],
            target_funcs: Counter[ExtractedFunction]) -> None:

        def pytest_args(repo_name: str) -> str:
            if repo_name == "scipy":
                return ""
            elif repo_name == "pandas":
                return "-m \"not slow and not db\""
            else:
                return ""

        self._dry_run_execution_environment()
        image_name = self._get_image_name()
        container = None
        try:
            client = docker.from_env()
            abs_helper_dir = self.helper_dir.resolve()
            abs_test_context_dir = self.pr_patch.test_context_dir.resolve()
            container = client.containers.run(
                image=image_name,
                detach=True,
                remove=False,
                tty=True,
                command=["tail", "-f", "/dev/null"],
                volumes={
                    abs_test_context_dir: {
                        'bind': '/opt/helper_output',
                        'mode': 'rw'
                    },
                    abs_helper_dir: {
                        'bind': f'/opt/{self.pr_patch.repo_name}/helper',
                        'mode': 'ro'
                    },
                },
                working_dir=f"/workspace",
            )
            # clean workspace
            command = "rm -rf /workspace/*"
            output = execute_command(
                container, command=command.split(),
                suppress=True)
            console.log(output)

            # install viztracer
            command = "pip install viztracer pydantic"
            output = execute_command(
                container, command=command.split(),
                suppress=True)
            console.log(output)

            # install specific requirements for the repo
            # if self.pr_patch.repo_name == "qiskit":
            #     command = "pip install pillow matplotlib pylatexenc"
            #     output = execute_command(
            #         container, command=command.split(),
            #         suppress=True)
            #     console.log(output)

            # run viztracer on pytest {test_name}
            # if self.pr_patch.repo_name == "scipy":
            # command = f"viztracer --ignore_c_function --tracer_entries 5000000 -o result.json -- dev.py --no-build test {format_test_names(test_names)}"
            # else:

            pytest_args = pytest_args(self.pr_patch.repo_name)
            command = f"python -m viztracer --ignore_c_function --tracer_entries 20000000 -o result.json -- pytest {pytest_args} {' '.join(test_names)} -rs"

            output = execute_command(
                container, command=shlex.split(command),
                suppress=True,
                workdir=f"/opt/{self.pr_patch.repo_name}")
            console.log(output)

            command = "mkdir -p /opt/helper_output"
            output = execute_command(
                container, command=command.split(),
                suppress=True)
            console.log(output)

            # the top 3 target functions
            counter = 1
            for target_func, _ in target_funcs.most_common(n=3):
                call_chain_file = abs_test_context_dir / \
                    f"{self.pr_patch.pr_number}_call_chains_{counter}.json"
                # parse the trace file to get call_chains_{counter}.json
                command = f"python3 find_caller_chain.py ../result.json {str(target_func)} --output /opt/helper_output/{self.pr_patch.pr_number}_call_chains_{counter}.json"
                output = execute_command(
                    container, command=command.split(),
                    suppress=True,
                    workdir=f"/opt/{self.pr_patch.repo_name}/helper")
                console.log(output)
                counter += 1

                if call_chain_file.exists():
                    console.log(
                        f"Invocation of pattern {target_func} found in trace file")

            # if no call chain file is generated
            if not any(abs_test_context_dir.glob(
                    f"{self.pr_patch.pr_number}_call_chains_*.json")):
                console.log(
                    f"find_caller_chain.py failed to output call chain file {call_chain_file}")
                raise Exception(
                    f"find_caller_chain.py failed to output call chain file {call_chain_file}")

            # print the output
            console.log(container.logs().decode())
        except Exception as e:
            console.log(f"Error running the container: {e}")
            raise e
        finally:
            if container:
                container.stop()
                container.remove()
