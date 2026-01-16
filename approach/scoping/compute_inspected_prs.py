import click
import logging
from pathlib import Path
from typing import List
from rich.console import Console

"""

### Task Description

**Objective**: Create a command-line interface (CLI) script in Python that iterates over subfolders within a given input folder, checks for the presence of a file named `coverage_all.xml` in each subfolder, and generates a text file (`pr_inspected.txt`) listing the PR numbers of the folders containing the file.

**Requirements**:
1. **Input Folder**:
   - The script should accept an optional argument `--input_folder` specifying the path to the input folder containing PR number subfolders.
   - If `--input_folder` is not provided, the script should use the current working directory.

2. **Output Path**:
   - The script should accept an optional argument `--output_path` specifying the path to store the output file `pr_inspected.txt`.
   - If `--output_path` is not provided, the script should store `pr_inspected.txt` in the same directory as the script.

3. **Folder Structure**:
   - The input folder contains subfolders named with PR numbers (integers).
   - Each PR number subfolder may or may not contain a file named `coverage_all.xml`.

4. **File Check**:
   - The script should check for the presence of `coverage_all.xml` directly within each PR number subfolder.
   - The content of `coverage_all.xml` does not need to be checked.

5. **Output File**:
   - The script should create a text file named `pr_inspected.txt` in the specified output path.
   - Each line of `pr_inspected.txt` should contain the PR number of a folder that contains the `coverage_all.xml` file.

6. **Logging**:
   - Use the `logging` library to print which folders contain the `coverage_all.xml` file and which do not.

7. **Error Handling**:
   - The script should handle missing folders or files gracefully by logging errors and continuing execution.
   - Use appropriate logging to capture any issues encountered during execution.

8. **Dependencies**:
   - The script should be written in Python 3.x.
   - Use the `click` library for handling command-line arguments.

9. **Execution Environment**:
   - The script should be compatible with both Linux and Windows environments.

10. **Testing**:
    - Include unit tests to verify the functionality of the script.
    - Tests should cover scenarios such as missing `coverage_all.xml` files, non-integer folder names, and empty input folders.

11. **Documentation**:
    - Provide inline comments explaining the code.
    - Include a README file with instructions on how to run the script and any dependencies required.

### Example Usage


### Example Usage with `python -m`

```sh
python -m approach.scoping.compute_inspected_prs --input_folder data/test_augmentation/005/qiskit/coverage --output_folder data/test_augmentation/005/qiskit/
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

"""

console = Console(color_system=None)


def find_pr_folders(input_folder: Path) -> List[Path]:
    """Find all subfolders in the input folder."""
    return [f for f in input_folder.iterdir() if f.is_dir()
            and f.name.isdigit()]


def check_coverage_file(pr_folder: Path) -> bool:
    """Check if the coverage_all.xml file exists in the PR folder."""
    return (pr_folder / 'coverage_all.xml').exists()


def write_output_file(output_path: Path, pr_numbers: List[int]) -> None:
    """Write the PR numbers to the output file."""
    with output_path.open('w') as f:
        for pr_number in sorted(pr_numbers):
            f.write(f"{pr_number}\n")


def ensure_output_folder_exists(output_path: Path) -> None:
    """Ensure the output folder exists, create if not."""
    output_path.parent.mkdir(parents=True, exist_ok=True)


@click.command()
@click.option('--input_folder', default='.', type=click.Path(
    exists=True, file_okay=False, path_type=Path),
    help='Path to the input folder containing PR number subfolders.')
@click.option('--output_folder', default='.', type=click.Path(
    exists=True, file_okay=False, path_type=Path),
    help='Path to the folder where the output file pr_inspected.txt will be stored.')
def main(input_folder: Path, output_folder: Path) -> None:
    """Main function to find PR folders with coverage_all.xml and write to output file."""
    logging.basicConfig(level=logging.INFO)
    pr_folders = find_pr_folders(input_folder=input_folder)
    pr_numbers = []

    for pr_folder in pr_folders:
        if check_coverage_file(pr_folder=pr_folder):
            pr_numbers.append(int(pr_folder.name))
            console.log(f"Found coverage_all.xml in {pr_folder.name}")
        else:
            console.log(f"No coverage_all.xml in {pr_folder.name}")

    output_path = output_folder / 'pr_inspected.txt'
    ensure_output_folder_exists(output_path=output_path)
    write_output_file(output_path=output_path, pr_numbers=pr_numbers)


if __name__ == '__main__':
    main()
