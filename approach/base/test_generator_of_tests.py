from approach.base.generator_of_tests import GeneratorOfTests
from approach.base.pr_patch import PRPatch
import pytest
import os
from pathlib import Path


@pytest.fixture
def groq_token_str():
    token = os.getenv("GROQ_API_KEY")
    if token is None:
        with open("secrets/groq_token.txt", "r") as file:
            token = file.read().strip()
    return token


@pytest.fixture
def gemini_token_str():
    token = os.getenv("GEMINI_API_KEY")
    if token is None:
        with open("secrets/gemini_token.txt", "r") as file:
            token = file.read().strip()
    return token


def test_generate(gemini_token_str):
    """Test main function with valid inputs."""

    os.environ["GEMINI_API_KEY"] = gemini_token_str

    pr_number = 13779
    repo = "Qiskit/qiskit"
    base_dir = 'data/tests_artifacts/qiskit_single_patch'

    pr_patch = PRPatch(
        pr_number=pr_number,
        repo_owner=repo.split('/')[0],
        repo_name=repo.split('/')[1],
        base_dir=base_dir
    )

    expected_path_new_test = os.path.join(
        base_dir, 'test_cases', '13779', 'test_1.py')
    # remove if already exists
    if os.path.exists(expected_path_new_test):
        os.remove(expected_path_new_test)

    generator = GeneratorOfTests(
        pr_patch=pr_patch,
        base_dir=base_dir,
        MODEL_NAME="gemini/gemini-1.5-flash",
        abs_custom_dockerfile_path="docker/qiskit/only_python/dockerfile"
    )
    generator.generate()

    # check that test_1 has been created
    assert os.path.exists(expected_path_new_test), "Test file was not created"


@pytest.fixture
def simple_qiskit_test_case():
    return """
import unittest
from qiskit import QuantumCircuit

def test_qiskit():
    qc = QuantumCircuit(1)
    qc.h(0)
    qc.measure_all()

    assert qc.num_qubits == 1
"""


def test_compute_coverage_new_test(tmp_path, simple_qiskit_test_case):
    """Check if we can get the coverage of the new test."""

    pr_number = 13779
    repo = "Qiskit/qiskit"

    pr_patch = PRPatch(
        pr_number=pr_number,
        repo_owner=repo.split('/')[0],
        repo_name=repo.split('/')[1],
        base_dir=tmp_path
    )

    print(tmp_path)
    path_dir_new_test = Path(
        tmp_path) / "test_cases" / str(pr_number)
    # ensure directory exists
    path_dir_new_test.mkdir(parents=True, exist_ok=True)
    path_new_test = path_dir_new_test / "test_1.py"
    # write the test case
    path_new_test.write_text(simple_qiskit_test_case)

    generator = GeneratorOfTests(
        pr_patch=pr_patch,
        base_dir=tmp_path,
        MODEL_NAME="gemini/gemini-1.5-flash",
        abs_custom_dockerfile_path="docker/qiskit/only_python/dockerfile"
    )
    generator.compute_relevance(
        test_name="test_1.py"
    )

    # check that test_1 has been created
    assert os.path.exists(Path(tmp_path) / "test_cases" / str(
        pr_number) / "test_1_relevance.json"), "Relevance file was not created"
