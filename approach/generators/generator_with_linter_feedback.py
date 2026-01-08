import sys
from approach.base.generator_of_tests import GeneratorOfTests
from approach.base.pr_patch import PRPatch
from pathlib import Path

from approach.generators.generator_with_uncovered_feedback import (
    GeneratorWithUncoveredFeedback
)

import libcst as cst
import subprocess
import tempfile

from typing import List, Tuple, Dict, Any
import dspy


class IntegrateLinterFeedback(dspy.Signature):
    """Improve the given test by integrating the linter feedback.

    Make sure to address all the linter feedback.
    The goal is to generate another test case that keeps the original test case
    functionality but also addresses the linter feedback.
    """

    diff_content: str = dspy.InputField(desc="Content of the diff file")
    pr_context: str = dspy.InputField(desc="Context of the PR")
    uncovered_line: str = dspy.InputField(
        desc="Uncovered line in the files of the PR. Each uncovered line is marked with the `# UNCOVERED` ending comment.")
    current_test_case_draft: str = dspy.InputField(
        desc="Current test case draft that needs to be improved.")
    linter_feedback: str = dspy.InputField(
        desc="Linter feedback on the current test case draft.")
    test_case: str = dspy.OutputField(
        desc="Improved test case (only python code output - no tags)"
        "Include at max 1 test cases."
        "Keep the original test case functionality."
        "Make sure to address all the linter feedback."
    )


def get_undefined_references(src):
    undefined_variables = []  # using a list here to get a deterministic order

    ast = cst.parse_module(src)
    ast_wrapper = cst.metadata.MetadataWrapper(ast)
    scopes = ast_wrapper.resolve(cst.metadata.ScopeProvider).values()
    for scope in scopes:
        for access in scope.accesses:
            if len(access.referents) == 0:
                node = access.node
                undefined_variables.append(node.value)

    # remove duplicates
    undefined_variables = list(dict.fromkeys(undefined_variables))

    return undefined_variables


def run_flake8_linter(source: str, enabled_rules: List[str]) -> str:
    """Run the flake8 linter on the given source code and return the output."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".py") as temp_file:
        temp_file.write(source.encode())
        temp_file.flush()
        temp_file_name = temp_file.name
    try:
        python_executable = sys.executable  # Gets the current Python interpreter path
        flake8_path = str(Path(python_executable).parent / "flake8")  # Get flake8 from same env
        result = subprocess.run(
            [flake8_path, "--select", ",".join(enabled_rules), temp_file_name],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        return e.output
    finally:
        Path(temp_file_name).unlink()


class GeneratorOfTestWithLinterFeedback(GeneratorWithUncoveredFeedback):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.linter_classes = kwargs.get("linter_classes", None)

    def _generate_test_content(self) -> Tuple[str, Dict[str, Any]]:
        metadata = dict({})

        test_attempt_1, metadata_1 = super()._generate_test_content()
        metadata["test_attempt_1"] = metadata_1

        print(f"Test attempt 1: {test_attempt_1}")
        # Integrate linter feedback into test content generation
        linter_feedback = run_flake8_linter(
            source=test_attempt_1,
            enabled_rules=self.linter_classes
        )
        metadata["linter_feedback_on_attempt_1"] = linter_feedback
        if linter_feedback.strip() == "":
            return test_attempt_1, metadata

        print(f"Linter feedback: {linter_feedback}")
        linter_fixer = dspy.ChainOfThought(IntegrateLinterFeedback)
        response = linter_fixer(
            diff_content=self.pr_patch.diff,
            uncovered_line=self.pr_patch.uncovered_lines_summary,
            pr_context=self.pr_patch.augmented_discussion.summary,
            current_test_case_draft=test_attempt_1,
            linter_feedback=linter_feedback
        )
        test_attempt_after_linter_feedback = response.test_case

        print(
            f"Test attempt after linter feedback: {test_attempt_after_linter_feedback}")
        metadata["test_attempt_after_linter_feedback"] = test_attempt_after_linter_feedback

        return test_attempt_after_linter_feedback, metadata
