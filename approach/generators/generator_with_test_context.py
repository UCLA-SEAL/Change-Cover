import dspy
from approach.base.generator_of_tests import GeneratorOfTests


class GenerateTestCases(dspy.Signature):
    """Generate test cases for the changes made in the PR.

    Make sure to include all the relevant imports.
    Prefer import forms that you can see already done in the code.
    Prefer key focus test cases rather than many test cases.
    """

    diff_content: str = dspy.InputField(desc="Content of the diff file")
    uncovered_line: str = dspy.InputField(
        desc="Uncovered line in the files of the PR. Each uncovered line is marked with the `# UNCOVERED` ending comment.")
    pr_context: str = dspy.InputField(desc="Context of the PR")
    test_path: str = dspy.InputField(desc="The full pat of the test file for which a new/modified test for this PR should belong to")
    test_class: str = dspy.InputField(desc="The Test Class for which a new/modified test for this PR should belong to")
    test_method: str = dspy.InputField(desc="A full Test Method of the test class, that is the most relevant to the PR. \
                                       This could be a test method modified by the PR itself, or a test method that is \
                                       the most relevant to the PR.")
    test_cases: str = dspy.OutputField(
        desc="Generated test cases (only python code output - no tags)"
        "Include at max 1 test cases."
        "Focus on the uncovered lines."
        "Make sure to include all the relevant imports. Do no leave placeholder imports."
        "The test case should be a valid python code, that can be copy-pasted into the test file."
    )


class FixImports(dspy.Signature):
    """Make sure that the test case imports all the required modules/libaries.

    Make sure to include all the relevant imports.
    """

    test_cases: str = dspy.InputField(desc="Current test cases")
    test_cases_double_checked_for_imports: str = dspy.OutputField(
        desc="Test cases with all the required imports (added if missing)"
    )


class GeneratorWithTestContext(GeneratorOfTests):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _generate_test_content(self) -> str:
        lm = dspy.LM(model=self.MODEL_NAME, temperature=self.temperature, cache=False)
        dspy.settings.configure(lm=lm)

        generate_tests = dspy.ChainOfThought(GenerateTestCases)

        # For now, randomly pick a test_file
        # testfile2classmethod = list(self.pr_patch.test_context._test_context['testfile2classmethod'].items())[0]
        
        # test_path, test_class, test_method = testfile2classmethod[0], testfile2classmethod[1][0], testfile2classmethod[1][1]

        # Retrieve test context
        test_path, test_class, test_method_name, test_method = self.pr_patch.test_context.most_common_test_context

        response = generate_tests(
            diff_content=self.pr_patch.diff,
            uncovered_line=self.pr_patch.uncovered_lines_summary,
            pr_context=self.pr_patch.augmented_discussion.summary,
            test_path=test_path,
            test_class=test_class,
            test_method=test_method)
        test_case = response.test_cases
        test_case = self.remove_lines_with_prefix(test_case, "```")

        metadata = {
            "diff_content": self.pr_patch.diff,
            "uncovered_line": self.pr_patch.uncovered_lines_summary,
            "pr_context": self.pr_patch.augmented_discussion.summary,
            "test_path": test_path,
            "test_class": test_class,
            "test_method": test_method,
            "test_case": test_case
        }

        # fix imports
        fix_imports = dspy.ChainOfThought(FixImports)
        response = fix_imports(test_cases=test_case)
        test_case = response.test_cases_double_checked_for_imports
        test_case = self.remove_lines_with_prefix(test_case, "```")

        return test_case, metadata
