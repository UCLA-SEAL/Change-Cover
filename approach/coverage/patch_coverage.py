from approach.base.isolated_environment import IsolatedEnvironment
from approach.base.pr_patch import PRPatch

import json
import numpy as np
import re
from typing import Any, Dict, List
from collections import Counter
from rich.console import Console

from pathlib import Path
import docker
import subprocess

import approach.coverage.formatter as cov_formatter
from approach.utils.test_extractor import extract_names, ExtractedFunction
from approach.utils.time_logger import TimeLogger

console = Console(color_system=None)


def flatten_coverage_datapoint(datapoint: Dict[str, Any]) -> List[str]:
    """
    Flattens a coverage datapoint into a list of strings.

    Args:
        datapoint (Dict[str, Any]): A dictionary where keys are file names and
                                    values are dictionaries containing "covered"
                                    and "missed" line numbers.

    Returns:
        List[str]: A list of strings in the format "file_name:line_number:c" for
                   covered lines and "file_name:line_number:m" for missed lines.
    """
    flat_datapoint = []
    for file_name, file_data in datapoint.items():
        for line_number in file_data.get("covered", []):
            flat_datapoint.append(f"{file_name}:{line_number}:c")
        for line_number in file_data.get("missed", []):
            flat_datapoint.append(f"{file_name}:{line_number}:m")
    return flat_datapoint


class PatchCoverage(IsolatedEnvironment):

    def __init__(
            self, pr_patch: PRPatch,
            abs_custom_dockerfile_path: str = None):
        super().__init__(pr_patch, abs_custom_dockerfile_path)
        self.time_logger = TimeLogger(
            logging_dir=self.pr_patch.base_dir / "time" / str(self.pr_patch.pr_number))


    def _prepare_coverage_info(self) -> None:
        """Compute or retrive the coverage information (coverage_all.xml).

        The coverage information is computed by running the test suite or
        retrieved from the Docker image if the test suite was run at build time.
        The default location for the coverage file is:
        Path(self.pr_patch.coverage_dir) / "coverage_all.xml"
        """
        if self.pr_patch.repo_name.lower() in ["qiskit", "pandas", "scipy"]:
            if self.pr_patch.repo_name.lower() == "qiskit":
                image_filepath = "/opt/qiskit/coverage_all.xml"
            elif self.pr_patch.repo_name.lower() == "pandas":
                image_filepath = "/opt/pandas/coverage_all.xml"
            elif self.pr_patch.repo_name.lower() == "scipy":
                image_filepath = "/opt/scipy/coverage_all.xml"
            else:
                raise ValueError(
                    f"Unknown repository: {self.pr_patch.repo_name}. "
                    "Not clear where to find the coverage file. "
                    "You should specify the path to the coverage file in the "
                    "PatchCoverage._get_coverage_info method.")
            # the same name as the one used in the dockerfile
            # will be used to copy the file, aka coverage_all.xml
            self._copy_from_image(
                image_filepath=image_filepath,
                output_folder=self.pr_patch.coverage_dir
            )
        elif self.pr_patch.repo_name.lower() in ["astroquery", "ax"]:
            self._run_test_suite()

    def compute_patch_coverage(self) -> None:
        self.time_logger.log_event(
            pr_number=self.pr_patch.pr_number,
            test_id=None,
            event_type="start",
            component="patch_coverage_computation"
        )
        self._dry_run_execution_environment()
        coverage_file_path = Path(
            self.pr_patch.coverage_dir) / "coverage_all.xml"
        if not coverage_file_path.exists():
            print(
                f"PR {self.pr_patch.pr_number}: Coverage file not found. Compute patch coverage first."
            )
            self._prepare_coverage_info()
        self._compute_relevance(
            abs_coverage_path=str(coverage_file_path),
            abs_output_path=self.pr_patch.patch_coverage_path
        )
        self._create_uncovered_lines_summary()
        self.time_logger.log_event(
            pr_number=self.pr_patch.pr_number,
            test_id=None,
            event_type="end",
            component="patch_coverage_computation"
        )


    def _create_uncovered_lines_summary(self) -> None:
        """Create the summary of the uncovered lines in a textual format."""
        if not self.pr_patch.patch_coverage_path.exists():
            print(
                "Coverage file not found. Compute patch coverage first.")
            self.compute_patch_coverage()
        filepath = self.pr_patch.coverage_dir / "pr_uncovered_lines.txt"
        cov_formatter.process_json_file(
            json_file=self.pr_patch.patch_coverage_path,
            source_dir=self.pr_patch.after_dir,
            output_file=filepath,
            custom_string='# UNCOVERED',
            context_size=10)

    def create_uncovered_lines_summary_within_target_func(
            self, target_func: ExtractedFunction) -> str:
        """
        Create a summary of uncovered lines within a specific target function.
        """
        if not self.pr_patch.patch_coverage_path.exists():
            print(
                "Coverage file not found. Compute patch coverage first.")
            self.compute_patch_coverage()
        return cov_formatter.process_json_file_within_target_func(
            json_file=self.pr_patch.patch_coverage_path,
            source_dir=self.pr_patch.after_dir,
            target_func=target_func,
            custom_string='# UNCOVERED',
            context_size=10)

    def create_uncovered_lines_summary_within_target_func_custom(
            self, target_func: ExtractedFunction, json_file_path: Path) -> str:
        """
        Create a summary of uncovered lines within a specific target function.
        Using a custom json file
        """
        return cov_formatter.process_json_file_within_target_func(
            json_file=json_file_path,
            source_dir=self.pr_patch.after_dir,
            target_func=target_func,
            custom_string='# UNCOVERED',
            context_size=10)

    def _process_patch_coverage_data(self) -> Counter[ExtractedFunction]:
        """
        Process the patch coverage data to be used by Test Context.

        For all the uncovered lines from the patch coverage data, visit the AST to extract
        its class name, function name, and whole function definition.

        Returns a dictionary with the following structure:
        {
            (classname, funcname, funcdef): frequency
        }
        where frequency is the #uncovered lines inside this function.
        """

        pc_data = self.patch_coverage_data
        target_names = Counter()

        file_dir = self.pr_patch.after_dir

        for filepath, cov_dict in pc_data.items():

            # if the file is a test file, skip it
            if 'test' in filepath:
                continue
            # if the file is not a python file, skip it
            if not filepath.endswith('.py'):
                continue

            # Get the absolute path of the file
            abs_filepath = Path(file_dir) / filepath

            # Check if the file exists
            if not abs_filepath.exists():
                console.log(f"File {abs_filepath} does not exist.")
                continue

            # Read the file content
            with open(abs_filepath, 'r') as f:
                file_content = f.read()

            missed_lines = cov_dict['missed']

            l = []
            for line in missed_lines:
                try:
                    # Extract the function name and class name from the line
                    l.append(extract_names(int(line), file_content, filepath))
                except ValueError as e:
                    # If the line is not a function or class definition, skip
                    # it
                    console.log(
                        f"Error extracting names from line {line}: {e}")
                    continue

            target_names.update(l)

        return target_names

    @property
    def target_funcs(self) -> Counter[ExtractedFunction]:
        """
        Extract the target functions from the patch coverage data.

        Returns:
            Counter[ExtractedFunction]: A counter of ExtractedFunction objects
                                         with their frequencies.
        """
        return self._process_patch_coverage_data()

    @property
    def patch_coverage_data(self) -> Dict[str, Any]:
        if not self.pr_patch.patch_coverage_path.exists():
            self.compute_patch_coverage()
        with open(self.pr_patch.patch_coverage_path, 'r') as file:
            relevance_data = json.load(file)
        return relevance_data

    @property
    def patch_coverage_percentage(self) -> float:
        if not self.pr_patch.patch_coverage_path.exists():
            self.compute_patch_coverage()
        with open(self.pr_patch.patch_coverage_path, 'r') as file:
            relevance_data = json.load(file)

        total_lines = 0
        covered_lines = 0

        # only compute patch coverage on non-test source files
        for file_full_name, file_data in relevance_data.items():
            if not re.search(r"test|tests|__init__", file_full_name):
                total_lines += len(file_data.get("covered", [])
                                   ) + len(file_data.get("missed", []))
                covered_lines += len(file_data.get("covered", []))

        if total_lines > 0:
            patch_coverage = (covered_lines / total_lines) * 100
        else:
            # If there are no lines, set patch coverage to NA
            patch_coverage = np.nan
        return patch_coverage

    def _run_test_suite(self) -> None:
        """Run the test suite to generate coverage data."""
        self.time_logger.log_event(
            pr_number=self.pr_patch.pr_number,
            test_id=None,
            event_type="start",
            component="test_suite_execution"
        )
        client = docker.from_env()
        abs_path_output = str(self.pr_patch.coverage_dir.resolve())
        abs_path_test_script = str(
            Path(f"docker/{self.pr_patch.repo_name.lower()}/run_tests.sh").resolve())
        # start the container
        print(f"Starting container {self._get_image_name()}...")

        container = client.containers.run(
            image=self._get_image_name(),
            # useless continually running command
            #  to keep the container alive
            command="bash -c \"while true; do sleep 1; done\"",
            detach=True,
            remove=True,
            tty=True,
            volumes={
                abs_path_output: {
                    'bind': '/opt/coverage', 'mode': 'rw'},
                # mount the run_tests.sh script
                abs_path_test_script: {
                    'bind': f'/opt/{self.pr_patch.repo_name.lower()}/run_tests.sh', 'mode': 'ro'}
            },
        )
        print(f"Container {container.name} started.")
        print(f"Run this command to enter interactive mode:\n"
              f"docker exec -it {container.name} /bin/bash")
        # run the test suite
        command = (
            f"bash -c \"cd /opt/{self.pr_patch.repo_name.lower()}; ./run_tests.sh --pr-number {self.pr_patch.pr_number} \""
        )
        try:
            print(f"Running test suite in container {container.name}...")
            print(f"Command: {command}")
            exec_result = container.exec_run(command, stream=True)
            for output in exec_result.output:
                if output:
                    print(output.decode('utf-8').strip())

            # Check exit code after command completes
            # if exec_result.exit_code != 0:
            #     print(f"Command failed with exit code {exec_result.exit_code}")
            #     container.stop()
            #     return None
            container.stop()
        except Exception as e:
            print(f"Error running test suite: {e}")
            container.stop()
            self.time_logger.log_event(
                pr_number=self.pr_patch.pr_number,
                test_id=None,
                event_type="end",
                component="test_suite_execution",
                is_error=True
            )
            return None
        self.time_logger.log_event(
            pr_number=self.pr_patch.pr_number,
            test_id=None,
            event_type="end",
            component="test_suite_execution"
        )
        return str(Path(abs_path_output) / "coverage_all.xml")

    def __lt__(self, other: 'PatchCoverage') -> bool:
        """Compare PatchCoverage instances based on pr_patch."""
        if not isinstance(other, PatchCoverage):
            return NotImplemented
        return self.pr_patch < other.pr_patch

    def __gt__(self, other: 'PatchCoverage') -> bool:
        """Compare PatchCoverage instances based on pr_patch."""
        if not isinstance(other, PatchCoverage):
            return NotImplemented
        return self.pr_patch > other.pr_patch

    def __eq__(self, other: 'PatchCoverage') -> bool:
        """Compare PatchCoverage instances based on pr_patch."""
        if not isinstance(other, PatchCoverage):
            return NotImplemented
        return self.pr_patch == other.pr_patch
