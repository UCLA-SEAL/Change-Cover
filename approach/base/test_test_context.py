import pytest
import shutil
import os
import dspy
from pathlib import Path
from approach.base.pr_patch import PRPatch
from approach.base.test_context import TestContext
from rich.console import Console

console = Console(color_system=None)

def main():
    OPENAI_TOKEN = Path("secrets/openai_token.txt").read_text().strip()
    os.environ["OPENAI_API_KEY"] = OPENAI_TOKEN
    lm = dspy.LM("openai/gpt-4o-mini", temperature=0.1, cache=False)
    dspy.configure(lm=lm)

    # patch with a test
    patch = PRPatch(
        repo_owner="scipy",
        repo_name="scipy",
        pr_number=22475,
        base_dir="data/test_augmentation/005/scipy"
    )
    context = TestContext(pr_patch=patch)
    console.log(f"Relevant test files: {context.relevant_test_files}")
    console.log(f"Full context: {context.test_context}")

    # patch without a test
    patch = PRPatch(
        repo_owner="scipy",
        repo_name="scipy",
        pr_number=22401,
        base_dir="data/test_augmentation/005/scipy"
    )
    context = TestContext(pr_patch=patch)
    console.log(f"Relevant test files: {context.relevant_test_files}")
    console.log(f"Full context: {context.test_context}")
    console.log(f"Full context: {context.test_context}")

    patch = PRPatch(
        repo_owner="scipy",
        repo_name="scipy",
        pr_number=22393,
        base_dir="data/test_augmentation/005/scipy"
    )
    context = TestContext(pr_patch=patch)
    console.log(f"Relevant test files: {context.relevant_test_files}")
    assert 'scipy/stats/tests/test_marray.py' in context.relevant_test_files
    console.log(f"Full context: {context.test_context}")
    

if __name__ == "__main__":
    main()

