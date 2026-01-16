
from approach.coverage.patch_coverage import PatchCoverage
import pytest
from approach.base.pr_patch import PRPatch


def test_patch_coverage_initialization():
    """Test that PatchCoverage initializes correctly with given PRPatch and Dockerfile path."""
    pr_patch = PRPatch(
        repo_owner='Qiskit',
        repo_name='qiskit',
        pr_number=13758,
        base_dir='data/tests_artifacts/qiskit_single_patch'
    )
    dockerfile_path = 'docker/qiskit/full_test_suite/dockerfile'
    patch_coverage = PatchCoverage(
        pr_patch=pr_patch,
        abs_custom_dockerfile_path=dockerfile_path
    )

    assert patch_coverage.pr_patch == pr_patch
    assert patch_coverage.abs_custom_dockerfile_path == dockerfile_path


def test_patch_coverage_relevance():
    """Test that PatchCoverage computes the patch coverage relevance correctly."""
    pr_patch = PRPatch(
        repo_owner='Qiskit',
        repo_name='qiskit',
        pr_number=13758,
        base_dir='data/tests_artifacts/qiskit_single_patch'
    )
    pr_patch.retrieve_diff_file()
    pr_patch._ensure_directories_exist()

    dockerfile_path = 'docker/qiskit/full_test_suite/dockerfile'
    patch_coverage = PatchCoverage(
        pr_patch=pr_patch,
        abs_custom_dockerfile_path=dockerfile_path
    )

    patch_coverage.compute_patch_coverage()

    assert patch_coverage.pr_patch.patch_coverage_path.exists(
    ), "Patch coverage file was not created (no .json file in the folder coverage for this PR)."
