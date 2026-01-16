from typing import Any, Dict, Tuple

import dspy
from approach.base.generator_of_tests import GeneratorOfTests


class GenerateTestCases(dspy.Signature):
    """Generate test cases for the changes made in the PR.

    Make sure to include all the relevant imports.
    Prefer import forms that you can see already done in the code.
    Prefer key focus test cases rather than many test cases.
    """

    diff_content: str = dspy.InputField(desc="Content of the diff file")
    pr_context: str = dspy.InputField(desc="Context of the PR")
    uncovered_line: str = dspy.InputField(
        desc="Uncovered line in the files of the PR. Each uncovered line is marked with the `# UNCOVERED` ending comment.")
    test_cases: str = dspy.OutputField(
        desc="Generated test cases (only python code output - no tags)"
        "Include at max 1 test cases."
        "Focus on the uncovered lines."
        "Make sure to include all the relevant imports."
    )


class FixImports(dspy.Signature):
    """Make sure that the test case imports all the required modules/libaries.

    Make sure to include all the relevant imports.
    """

    test_cases: str = dspy.InputField(desc="Current test cases")
    test_cases_double_checked_for_imports: str = dspy.OutputField(
        desc="Test cases with all the required imports (added if missing)"
    )


class GeneratorWithUncoveredFeedback(GeneratorOfTests):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _generate_test_content(self) -> Tuple[str, Dict[str, Any]]:
        lm = dspy.LM(
            self.MODEL_NAME,
            temperature=1,
            cache=False)
        dspy.settings.configure(lm=lm)
        generate_tests = dspy.ChainOfThought(GenerateTestCases)
        response = generate_tests(
            diff_content=self.pr_patch.diff,
            uncovered_line=self.pr_patch.uncovered_lines_summary,
            pr_context=self.pr_patch.augmented_discussion.summary)
        test_case = response.test_cases
        test_case = self.remove_lines_with_prefix(test_case, "```")

        # fix imports
        fix_imports = dspy.ChainOfThought(FixImports)
        response = fix_imports(test_cases=test_case)
        test_case = response.test_cases_double_checked_for_imports
        test_case = self.remove_lines_with_prefix(test_case, "```")

        metadata = {
            "diff_content": self.pr_patch.diff,
            "pr_context": self.pr_patch.augmented_discussion.summary,
            "uncovered_line": self.pr_patch.uncovered_lines_summary,
            "test_case": test_case
        }

        return test_case, metadata
