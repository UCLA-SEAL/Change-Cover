# use run_test_for_output_only function to run the test cases and get the output only.

from typing import Any, Dict, Tuple

import dspy
from approach.base.generator_of_tests import GeneratorOfTests
from approach.generators.generator_with_test_context import GeneratorWithTestContext


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
    The goal is to generate another test case that keeps the original test case
    functionality but also addresses the runtime errors.
    """

    diff_content: str = dspy.InputField(desc="Content of the diff file")
    pr_context: str = dspy.InputField(desc="Context of the PR")
    current_test_case_draft: str = dspy.InputField(
        desc="Current test case draft that needs to be improved.")
    runtime_error_message: str = dspy.InputField(
        desc="Runtime error message from the test case execution.")
    test_case: str = dspy.OutputField(
        desc="Improved test case (only python code output - no tags)"
        "Include at max 1 test cases."
        "Keep the original test case functionality."
        "Make sure to address all the runtime errors."
    )


class GeneratorOfTestWithRuntimeFeedbackComplete(GeneratorWithTestContext):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_repair_attempts = 3

    def _generate_test_content(self) -> Tuple[str, Dict[str, Any]]:
        lm = dspy.LM(
            self.MODEL_NAME,
            temperature=1,
            cache=False)
        dspy.settings.configure(lm=lm)

        test_case_1, metadata_1 = super()._generate_test_content()
        test_case = test_case_1
        test_case = self.remove_lines_with_prefix(test_case, "```")

        # fix imports
        fix_imports = dspy.ChainOfThought(FixImports)
        response = fix_imports(test_cases=test_case)
        test_case = response.test_cases_double_checked_for_imports
        test_case = self.remove_lines_with_prefix(test_case, "```")

        metadata = {
            "diff_content": self.pr_patch.diff,
            "pr_context": self.pr_patch.augmented_discussion.summary,
            "test_case": test_case
        }
        # store as tmp file
        test_name = self._generate_test_filename()
        tmp_test_name = f"__tmp__{test_name}"
        path_tmp_test = self.test_dir / tmp_test_name
        with open(path_tmp_test, "w") as f:
            f.write(test_case)

        num_repair_attempts = 0
        while num_repair_attempts < self.max_repair_attempts:
            # Run the test and get the runtime error message
            pytest_failed = False
            try:
                runtime_error_message = self.run_test_for_output_only(
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
                    current_test_case_draft=test_case,
                    runtime_error_message=runtime_error_message
                )
                fixed_test_case = response.test_case
                fixed_test_case = self.remove_lines_with_prefix(
                    fixed_test_case, "```")

                metadata["runtime_error_message"] = runtime_error_message
                metadata["fixed_test_case"] = fixed_test_case

                test_case = fixed_test_case
                test_case = self.remove_lines_with_prefix(test_case, "```")
                num_repair_attempts += 1
                # store as tmp file
                with open(path_tmp_test, "w") as f:
                    f.write(test_case)
            else:
                break
        
        return test_case, metadata
