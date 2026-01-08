import dspy
import json
import uuid
import random
from collections import Counter
from typing import Any, Dict, Tuple, List, Optional, Set
from pathlib import Path
from rich.console import Console
from approach.utils.merge_tests import merge_tests
from approach.base.generator_of_tests import GeneratorOfTests, TestContent
from approach.generators.generator_base import GeneratorBase
from approach.coverage.patch_coverage import PatchCoverage
from approach.utils.test_extractor import ExtractedFunction

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
    an explanation of why these lines are uncovered.

    Make sure to include all the relevant imports.
    """

    pr_context: str = dspy.InputField(desc="Context of the PR")

    uncovered_summary: str = dspy.InputField(
        desc="Summary of the uncovered lines in the PR.")

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


class GeneratorBaseNoTestContext(GeneratorBase):
    def __init__(self, *args,
                 dynamic_test_context=False,
                 runtime_feedback=False,
                 max_feedback=4, **kwargs):
        super().__init__(*args, **kwargs)
        self.runtime_feedback = runtime_feedback
        self.max_feedback = max_feedback

        # Frequency Counter[ExtractedFunction -> int] that maps target functions to
        # the number of uncovered lines in it
        self.target_funcs: Counter[ExtractedFunction] = PatchCoverage(
            pr_patch=self.pr_patch).target_funcs
        assert self.target_funcs, \
            f"No functions with uncovered lines found in the PR patch {self.pr_patch.pr_number}"

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
        target_func, uncovered_func_lines = self.pick_target_func(top_k_only=3)
        console.log(f"Selected target function: {target_func}")

        # Summarize uncovered lines
        CoTSummarizeUncovered = dspy.ChainOfThought(SummarizeUncoveredLines)
        response = CoTSummarizeUncovered(
            diff_content=self.pr_patch.diff,
            uncovered_line=uncovered_func_lines,
            pr_context=self.pr_patch.augmented_discussion.summary)
        self.uncovered_lines_summary = response.summary
        # Log token usage for SummarizeUncoveredLines
        self.token_logger.log(lm=lm, stage=SummarizeUncoveredLines)

        CoTGenerateTest = dspy.ChainOfThought(GenerateTestCases)
        response = CoTGenerateTest(
            uncovered_summary=self.uncovered_lines_summary,
            pr_context=self.pr_patch.augmented_discussion.summary)
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
            "target_func": str(target_func),
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
            test_context=None
        )

    def _integrate(self, force_new, test_filename, test_content,
                   target_func: ExtractedFunction, test_context=None):
        assert test_context is None, \
            "GeneratorBaseNoTestContext::_integrate: test_context must be None"

        # recompute the test context, but only for integration
        test_context_used = self.pr_patch.test_context

        # Call the superclass implementation
        super()._integrate(force_new, test_filename, test_content, target_func, test_context=test_context_used)
