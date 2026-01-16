import click
import yaml
import json
import os
import time
import sys
import concurrent.futures
from multiprocessing import get_context
from pathlib import Path
from rich.console import Console
from typing import List, Dict, Any
from approach.base.pr_patch import PRPatch
from approach.base.generator_of_tests import GeneratorOfTests
from approach.utils.available_prs import available_prs
from approach.generators.generator_base import GeneratorBase
from approach.generators.generator_base_no_test_context import GeneratorBaseNoTestContext
from approach.generators.generator_with_uncovered_feedback import (
    GeneratorWithUncoveredFeedback
)
from approach.generators.generator_with_linter_feedback import (
    GeneratorOfTestWithLinterFeedback
)
from approach.generators.generator_with_runtime_feedback import (
    GeneratorOfTestWithRuntimeFeedback
)
from approach.generators.generator_with_test_context import (
    GeneratorWithTestContext
)
from approach.generators.generator_with_runtime_feedback_new import (
    GeneratorOfTestWithRuntimeFeedbackComplete
)
from approach.utils.time_logger import TimeLogger

"""
## Task Description: Implement a Command Line Interface for Test Case Generation

**Objective:**
Create a Python script that reads a configuration file (`v002.yaml`), accesses the parameters within it, and sets up test case generation for specific pull requests (PRs). The script should load the PR information from disk using the `PRPatch` object and generate one test program for each PR using the `GeneratorOfTests` class and its subclass `GeneratorWithUncoveredFeedback`.

**Requirements:**

1. **Configuration File Parsing:**
   - The script should accept a configuration file as an argument (`--config v002.yaml`).
   - Parse the YAML configuration file to extract the following parameters:
     - `benchmark_name`: Name of the benchmark JSON file.
     - `benchmark_projects`: List of projects to process (e.g., `Qiskit/qiskit`).
     - `base_dir`: Base directory where PR information is stored.
     - `test_generator`: Configuration for the test generator, including:
       - `class_name`: Name of the test generator class.
       - `model_name`: Name of the model to use for test generation.

2. **Loading PR Information:**
   - Load the benchmark JSON file specified in the configuration (e.g., `v001.json`).
   - For each project listed in `benchmark_projects`, retrieve the PR numbers from the benchmark JSON file.
   - For each PR number, create a `PRPatch` object to load the PR information from disk.

3. **Test Generation:**
   - For each `PRPatch` object, instantiate the test generator class specified in the configuration.
   - Generate one test program for each PR using the specified model.
   - Provide feedback using the `console` from the `rich` library.

4. **Dependencies and Environment:**
   - Use standard Python libraries or specify any additional dependencies required.
   - Ensure compatibility with a Linux environment.

5. **Testing and Documentation:**
   - Include unit tests to verify the functionality of the script.
   - Provide documentation and usage examples for the script.

**Implementation Details:**

1. **Configuration File:**
   - The script should handle multiple test generator classes or models if specified in the configuration.

2. **PR Information:**
   - The script should handle cases where PR information is missing or incomplete gracefully.

3. **Test Generation:**
   - The generated test programs should follow PEP 8 coding standards.
   - The script should handle any post-processing or validation of the generated test programs.

4. **Logging and Output:**
   - Use the `console` from the `rich` library for feedback and error reporting.
   - The generated test programs should be saved to disk.

5. **Dependencies and Environment:**
   - Include a `requirements.txt` file with necessary dependencies.
   - Ensure compatibility with a Linux environment.

**Example Usage:**
```sh
python generate_tests.py --config v002.yaml
```

**Example Configuration File (`v002.yaml`):**
```yaml
benchmark_name: v001.json
benchmark_projects:
  - "Qiskit/qiskit"
base_dir: "data/test_augmentation/005"
test_generator:
  class_name: "GeneratorWithUncoveredFeedback"
  model_name: gemini/gemini-1.5-flash
```

**Example Benchmark File (`v001.json`):**
```json
{
    "projects": {
        "Qiskit/qiskit": {
            "pr_numbers": [
                13727,
                13637,
                13531,
                13624,
                13758,
                13704,
                13560,
                13646,
                13643,
                13596,
                13605,
                13618,
                13744
            ]
        }
    }
}
```


# Style
- use subfunctions appropriately
- each function has at maximum 7 lines of code of content, break them to smaller functions otherwise
- avoid function with a single line which is a function call
- always use named arguments when calling a function
    (except for standard library functions)
- keep the style consistent to pep8 (max 80 char)
- to print the logs it uses the console from Rich library
- make sure to have docstring for each subfunction and keep it brief to the point
(also avoid comments on top of the functions)
- it uses pathlib every time that paths are checked, created or composed.
- use type annotations with typing List, Dict, Any, Tuple, Optional as appropriate
- make sure that any output folder exists before storing file in it, otherwise create it.

Convert the function above into a click v8 interface in Python.
- map all the arguments to a corresponding option (in click) which is required
- add all the default values of the arguments as default of the click options
- use only underscores
- add a main with the command
- add the required imports
Make sure to add a function and call that function only in the main cli command.
The goal is to be able to import that function also from other files.

# Example usage:
# Assuming the module is located at /home/MYID/projects/PROJECT_PARENT/compiler-pr-analysis/approach/evaluate_generator_on_benchmark.py
# You can run the script using the following command:
# python -m approach.evaluate_generator_on_benchmark --config config/mt/v002.yaml

"""
console = Console(color_system=None)


def load_config(config_path: str) -> Dict[str, Any]:
    with open(config_path, 'r') as file:
        return yaml.safe_load(file)


def load_benchmark(benchmark_path: str) -> Dict[str, Any]:
    with open(benchmark_path, 'r') as file:
        return json.load(file)


def get_test_generator_class(class_name: str) -> Any:
    """Safely get the test generator class by name."""
    allowed_classes = {
        "simple_gen": GeneratorOfTests,
        "target_gen_with_self_fix": GeneratorWithUncoveredFeedback,
        "target_gen_with_self_fix_and_linter": GeneratorOfTestWithLinterFeedback,
        "target_gen_with_self_fix_and_runtime_feedback": GeneratorOfTestWithRuntimeFeedback,
        "target_gen_with_self_fix_and_test_context": GeneratorWithTestContext,
        "target_gen_with_self_fix_and_runtime_feedback_complete": GeneratorOfTestWithRuntimeFeedbackComplete,
        "target_gen_base": GeneratorBase,
        "target_gen_base_dynamic_test_context": GeneratorBase,
        "target_gen_base_no_test_context": GeneratorBaseNoTestContext
    }
    if class_name not in allowed_classes:
        raise ValueError(f"Invalid test generator class name: {class_name}")
    return allowed_classes[class_name]


def setup_model_api_keys(api_keys: Dict[str, str]) -> None:
    """Set up the model API keys from the specified paths."""
    for key, path in api_keys.items():
        with open(path, 'r') as file:
            api_key = file.read().strip()
        os.environ[key] = api_key
        console.log(f"API key for {key} set up successfully.")


def generate_and_evaluate_tests(test_generator: GeneratorOfTests,
                                integration: bool,
                                num_tests_per_pr: int,
                                num_workers: int,
                                min_time_between_tests_sec: int) -> bool:
    start_time = time.time()
    console.log("=" * 50)
    console.log(
        f"Generating tests for PR {test_generator.pr_patch.pr_number} in "
        f"{test_generator.pr_patch.repo_name} using model "
        f"{test_generator.MODEL_NAME} with {num_tests_per_pr} tests per PR.")
    files_before = set(os.listdir(test_generator.test_dir))
    time_logger = TimeLogger(logging_dir=Path(
        test_generator.base_dir) / "time" / str(test_generator.pr_patch.pr_number))

    try:
        if not integration:
            # TODO: remove not used
            new_tests = test_generator.generate(
                n=num_tests_per_pr, force_new=False)
        else:
            time_logger.log_event(
                pr_number=test_generator.pr_patch.pr_number,
                test_id=None,
                event_type="start",
                component="test_generation_and_integration"
            )
            new_tests = test_generator.generate_and_integrate(
                n=num_tests_per_pr, force_new=False)
            time_logger.log_event(
                pr_number=test_generator.pr_patch.pr_number,
                test_id=None,
                event_type="end",
                component="test_generation_and_integration"
            )
    except Exception as e:
        console.log(f"Error during test generation: {e}")
        return False

    files_after = set(os.listdir(test_generator.test_dir))
    has_something_new = len(files_after - files_before) > 0
    if has_something_new:
        console.log(f"Generated tests: {new_tests}")
    else:
        console.log("No new tests generated, skipping.")

    try:
        if num_workers == 1:
            for test_name in new_tests:
                run_and_compute(test_generator, test_name, integration)
                elapsed_time = time.time() - start_time
                sleep_time = max(0, min_time_between_tests_sec - elapsed_time)
                time.sleep(sleep_time)
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
                futures = [
                    executor.submit(
                        run_and_compute,
                        test_generator,
                        test_name,
                        integration) for test_name in new_tests]
                for future in concurrent.futures.as_completed(futures):
                    future.result()
    except KeyboardInterrupt:
        console.log("KeyboardInterrupt: Shutting down executor...")
        executor.shutdown(wait=False, cancel_futures=True)

    console.log(f"Finished processing PR {test_generator.pr_patch.pr_number}")
    return has_something_new


def run_and_compute(
        generator: GeneratorOfTests,
        test_name: str,
        integration: bool):
    time_logger = TimeLogger(logging_dir=Path(
        generator.base_dir) / "time" / str(generator.pr_patch.pr_number))
    time_logger.log_event(
        pr_number=generator.pr_patch.pr_number,
        test_id=test_name,
        event_type="start",
        component="test_execution"
    )
    # Execute the test
    try:
        generator.run_test(test_name=test_name)
    except Exception as e:
        console.log(f"Error executing test {test_name}: {e}")
    time_logger.log_event(
        pr_number=generator.pr_patch.pr_number,
        test_id=test_name,
        event_type="end",
        component="test_execution"
    )

    time_logger.log_event(
        pr_number=generator.pr_patch.pr_number,
        test_id=test_name,
        event_type="start",
        component="coverage_processing"
    )
    try:
        generator.compute_coverage_increment(test_name=test_name)
    except Exception as e:
        console.log(f"Error computing coverage for test {test_name}: {e}")
    time_logger.log_event(
        pr_number=generator.pr_patch.pr_number,
        test_id=test_name,
        event_type="end",
        component="coverage_processing"
    )

    if integration:
        integrated_test_name = test_name.replace(".py", "_integrated.py")
        time_logger.log_event(
            pr_number=generator.pr_patch.pr_number,
            test_id=integrated_test_name,
            event_type="start",
            component="integrated_test_execution"
        )
        # Run the integrated test
        # Note: Using 'test_name' not 'integrated_test_name' is intentional
        try:
            generator.run_integrated_test(test_name=test_name)
        except Exception as e:
            console.log(
                f"Error running integrated test {integrated_test_name}: {e}")
        time_logger.log_event(
            pr_number=generator.pr_patch.pr_number,
            test_id=integrated_test_name,
            event_type="end",
            component="integrated_test_execution"
        )

        time_logger.log_event(
            pr_number=generator.pr_patch.pr_number,
            test_id=integrated_test_name,
            event_type="start",
            component="integrated_coverage_processing"
        )
        # Compute coverage incr for integrated test
        try:
            generator.compute_coverage_increment(
                test_name=integrated_test_name)
        except Exception as e:
            console.log(
                f"Error computing coverage for integrated test {integrated_test_name}: {e}")
        time_logger.log_event(
            pr_number=generator.pr_patch.pr_number,
            test_id=test_name,
            event_type="end",
            component="test_and_coverage_processing"
        )


def parallel_initialize_generators(pr_numbers: List[int],
                                   repo_owner: str,
                                   repo_name: str,
                                   base_dir: Path,
                                   generator_class,
                                   model_name: str,
                                   min_time_between_tests_sec: int,
                                   test_folder_name: str,
                                   generator_kwargs: Dict[str,
                                                          Any],
                                   num_workers: int,
                                   dockerfile_path: str = None) -> List[GeneratorOfTests]:

    pr_details_list = [{"repo_owner": repo_owner,
                        "repo_name": repo_name,
                        "pr_number": pr_number,
                        "base_dir": base_dir / repo_name} for pr_number in pr_numbers]

    generators = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=num_workers, mp_context=get_context('spawn')) as executor:
        futures = [
            executor.submit(
                initialize_generator,
                pr_detail,
                generator_class,
                model_name,
                min_time_between_tests_sec,
                test_folder_name,
                dockerfile_path,
                generator_kwargs
            ) for pr_detail in pr_details_list
        ]
        for future in concurrent.futures.as_completed(futures):
            try:
                generator = future.result()
                generators.append(generator)
            except Exception as e:
                console.log(f"Failed to initialize generator: {e}")
    return generators


def initialize_generator(pr_details: Dict[str,
                                          Any],
                         generator_class,
                         model_name: str,
                         min_time_between_tests_sec: int,
                         test_folder_name: str,
                         dockerfile_path: str,
                         generator_kwargs: Dict[str,
                                                Any]) -> GeneratorOfTests:

    pr_patch = PRPatch(
        repo_owner=pr_details["repo_owner"],
        repo_name=pr_details["repo_name"],
        pr_number=pr_details["pr_number"],
        base_dir=pr_details["base_dir"],
        MODEL_NAME=model_name
    )
    return generator_class(
        pr_patch=pr_patch,
        base_dir=pr_patch.base_dir,
        MODEL_NAME=model_name,
        min_time_between_tests_sec=min_time_between_tests_sec,
        abs_custom_dockerfile_path=dockerfile_path,
        test_folder_name=test_folder_name,
        **generator_kwargs
    )


@click.command()
@click.option('--config', required=True, type=str,
              help='Path to the configuration file')
@click.option('--all-prs', default=False, is_flag=True, help='This flag OVERRIDEs the PR \
              numbers in the benchmark config and substitute with the PRs in pr_list_filtered.txt \
              that has a docker image with <100% patch coverage available on the system')
@click.option('--max_prs', default=None, type=int,
              help='Maximum number of PRs to process (default: all)')
def main(config: str, all_prs: bool, max_prs: int) -> None:
    config_data = load_config(config)
    setup_model_api_keys(config_data['api_keys'])
    benchmark_data = load_benchmark(config_data['benchmark_name'])
    base_dir = Path(config_data['base_dir'])
    generator_class = get_test_generator_class(
        config_data['test_generator']['class_name'])
    generator_kwargs = config_data['test_generator'].get('kwargs', {})
    integration = generator_kwargs.get('integration', False)
    num_tests_per_pr = config_data['test_generator'].get('num_tests_per_pr', 1)
    model_name = config_data['test_generator']['model_name']
    min_time_between_tests_sec = config_data['test_generator'].get(
        'min_time_between_tests_sec', 0)
    test_folder_name = config_data.get('test_folder_name', 'test_cases')
    num_workers = config_data.get('num_workers', 1)

    for project in config_data['benchmark_projects']:
        repo_owner, repo_name = project.split('/')
        if all_prs:
            console.log(f"Getting all PRs for {project} with <100% coverage")
            pr_numbers = available_prs(
                repo_owner=repo_owner, repo_name=repo_name, base_dir=base_dir)
            console.log(f"Found {len(pr_numbers)} PRs with <100% coverage")
        else:
            pr_numbers = benchmark_data['projects'][project]['pr_numbers']
        pr_numbers.sort(reverse=True)
        n_processed_prs = 0

        test_generators = parallel_initialize_generators(
            pr_numbers=pr_numbers,
            repo_owner=repo_owner,
            repo_name=repo_name,
            base_dir=base_dir,
            generator_class=generator_class,
            model_name=model_name,
            min_time_between_tests_sec=min_time_between_tests_sec,
            test_folder_name=test_folder_name,
            # dockerfile_path=f"docker/{repo_name}/full_test_suite/dockerfile",
            generator_kwargs=generator_kwargs,
            num_workers=num_workers
        )

        console.log(
            f"Initialized {len(test_generators)} test generators for {repo_name}")

        with concurrent.futures.ProcessPoolExecutor(max_workers=num_workers, mp_context=get_context('spawn')) as executor:
            future_to_generator = {
                executor.submit(
                    generate_and_evaluate_tests,
                    test_generator,
                    integration,
                    num_tests_per_pr,
                    num_workers,
                    min_time_between_tests_sec
                ): test_generator for test_generator in test_generators
            }

            for future in concurrent.futures.as_completed(future_to_generator):
                test_generator = future_to_generator[future]
                try:
                    success = future.result()
                    if success:
                        n_processed_prs += 1
                    if max_prs is not None and n_processed_prs >= max_prs:
                        console.log(f"Reached max_prs={max_prs}, stopping.")
                        return
                except Exception as e:
                    console.log(
                        f"Error processing PR {test_generator.pr_patch.pr_number} in {repo_name}: {e}")
                    console.log("Skipping this PR due to error.")
        console.log(
            f"Finished processing project {project}. Total PRs processed: {n_processed_prs}")


if __name__ == '__main__':
    main()
