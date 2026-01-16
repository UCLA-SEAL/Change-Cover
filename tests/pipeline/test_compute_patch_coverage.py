import pytest
from pathlib import Path
from approach.pipeline.compute_patch_coverage import (
    compute_coverage_main
)


def test_compute_coverage_main(tmp_path):
    pr_list_content = "13758\n13779\n"
    pr_list_file = tmp_path / "pr_list.txt"
    pr_list_file.write_text(pr_list_content)

    repo = "Qiskit/qiskit"
    output_dir = Path('data/tests_artifacts/qiskit_single_patch')
    output_dir.mkdir(parents=True, exist_ok=True)

    workers = 1

    compute_coverage_main(
        pr_list=str(pr_list_file),
        repo=repo, output_dir=str(output_dir),
        workers=workers)

    coverage_dir = output_dir / "coverage"

    # Check if the output directory for each PR was created
    assert (coverage_dir / "13758").exists()
    assert (coverage_dir / "13779").exists()

    # Check if the coverage file for each PR was created
    assert (coverage_dir / "13758" / "current_relevance.json").exists()
    assert (coverage_dir / "13779" / "current_relevance.json").exists()
