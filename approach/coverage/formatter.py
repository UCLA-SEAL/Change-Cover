import json
from pathlib import Path
import click
from rich.console import Console
from typing import Dict, List, Tuple
import libcst as cst
import ast
import warnings
from approach.utils.test_extractor import ExtractedFunction

"""Task Description
Objective: Develop a command-line interface (CLI) tool that processes JSON files to identify uncovered lines in Python files, appends a custom string to these lines, and generates a consolidated report.

Requirements:

Input:

A folder containing a JSON file (e.g., current_relevance.json).
The JSON file contains file paths as keys and lists of covered and missed lines as values.
Processing:

For each file path in the JSON, read the corresponding file content from a specified directory (e.g., after).
Append a custom string (default: # UNCOVERED) to each missed line in the file.
Concatenate the modified content of all files into a single text file.
Output:

Generate a text file named pr_uncovered_lines.txt in the same directory as the input JSON file.
The text file should contain:
A header with the full file name.
An 80-character separator line.
The modified content of the file with missed lines annotated.
Another 80-character separator line between files.
Example:

Given the JSON file:
{
    "qiskit/quantum_info/operators/symplectic/pauli_list.py": {
        "covered": [448, 452, 454, 455, 466, 1122],
        "missed": [1123]
    }
}

And the file content at pauli_list.py:
# ...existing code...
def some_function():
    # ...existing code...
    line_1123 = "This is line 1123"
    # ...existing code...
The output pr_uncovered_lines.txt should look like:
# qiskit/quantum_info/operators/symplectic/pauli_list.py
--------------------------------------------------------------------------------
# ...existing code...
def some_function():
    # ...existing code...
    line_1123 = "This is line 1123"  # UNCOVERED
    # ...existing code...
--------------------------------------------------------------------------------
Steps:

Parse the JSON file to extract file paths and missed lines.
Read the content of each file specified in the JSON.
Append the custom string to each missed line.
Concatenate the modified content into a single text file with appropriate headers and separators.
Test Case:

Create a test JSON file:
{
    "test_file.py": {
        "covered": [1, 2, 3],
        "missed": [4]
    }
}
Create the corresponding file content:
# filepath: data/test_augmentation/005/qiskit/file_content/13637/after/test_file.py
# Line 1
# Line 2
# Line 3
# Line 4
Expected output in pr_uncovered_lines.txt:
# test_file.py
--------------------------------------------------------------------------------
# Line 1
# Line 2
# Line 3
# Line 4  # UNCOVERED
--------------------------------------------------------------------------------

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
def truncate(s, n=5000): return s if len(s) <= 2 * \
    n else s[:n] + "\n... [truncated] ...\n" + s[-n:]


def add_trailing_newline(s): return s + "\n" if not s.endswith("\n") else s


def process_json_file(json_file: Path, source_dir: Path, output_file: Path,
                      custom_string: str, context_size: int = None) -> None:
    data = load_json(json_file)
    modified_content = concatenate_files(
        data, source_dir, custom_string, context_size)
    write_output_file(output_file, modified_content)


def process_json_file_within_target_func(json_file: Path, source_dir: Path,
                                         target_func: ExtractedFunction,
                                         custom_string: str,
                                         context_size: int = None) -> str:
    data = load_json(json_file)
    modified_content = concatenate_files(
        data, source_dir, custom_string, context_size, target_func=target_func)
    return modified_content


def load_json(json_file: Path) -> Dict[str, Dict[str, List[int]]]:
    with json_file.open('r') as file:
        return json.load(file)


def concatenate_files(
        data: Dict[str, Dict[str, List[int]]],
        source_dir: Path, custom_string: str, context_size: int, missed: bool = True,
        include_class_definition: bool = True, include_function_signature: bool = True,
        target_func: ExtractedFunction = None) -> str:
    content = []
    for file_path, lines in data.items():
        file_extension = file_path.split('.')[-1]
        full_path = source_dir / file_path
        file_content = read_file(full_path)

        if missed:
            lines_of_interest = lines['missed']
        else:
            lines_of_interest = lines['covered']

        # if target_func is provided, we need to append the custom string
        # only to the lines within that function and file
        if target_func is not None:
            if file_path == target_func.file_path:
                modified_content = append_custom_string(
                    file_content, lines_of_interest, custom_string, target_func=target_func)
            else:
                modified_content = file_content
        else:
            modified_content = append_custom_string(
                file_content, lines_of_interest, custom_string)
        if context_size is not None and len(lines_of_interest) > 0:
            try:
                modified_content = shrink_context_size(
                    file_content=modified_content,
                    custom_string=custom_string,
                    context_size=context_size,
                    file_extension=file_extension,
                    include_class_definition=include_class_definition,
                    include_function_signature=include_function_signature)
            except Exception as e:
                console.log(
                    f"Error while shrinking context size: {e}, full_path: {full_path}")
                raise e
        else:
            modified_content = ["\n"]
        content.append(format_file_content(file_path, modified_content))
    return '\n'.join(content)


def read_file(file_path: Path) -> List[str]:
    with file_path.open('r') as file:
        return file.readlines()


def find_target_func(
        source: str, target_func: ExtractedFunction) -> Tuple[int, int]:
    """
    Find the start and end line numbers of the target function in the source code.
    """
    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            # for top-level functions, match target_func.func_name
            if isinstance(
                    node,
                    ast.FunctionDef) and node.name == target_func.func_name:
                return node.lineno, node.end_lineno
            # for class methods, match target_func.class_name and
            # target_func.func_name
            if isinstance(
                    node,
                    ast.ClassDef) and node.name == target_func.class_name:
                # continue the walk to find methods within the class
                for subnode in node.body:
                    # check if the subnode is a function and matches the target
                    # function name
                    if isinstance(
                            subnode,
                            ast.FunctionDef) and subnode.name == target_func.func_name:
                        return subnode.lineno, subnode.end_lineno
        raise ValueError(
            f"Function {target_func.func_name} not found in the source code.")
    except ValueError as e:
        console.log(f"Error finding target function: {e}")
        raise e
    except SyntaxError as e:
        console.log(f"Syntax error in source code: {e}")
        raise e


def append_custom_string(
        file_content: List[str],
        missed_lines: List[int],
        custom_string: str,
        target_func: ExtractedFunction = None) -> List[str]:
    for line_num in missed_lines:
        # if target_func is provided, only append to lines within that function
        if target_func is not None:
            try:
                start_line, end_line = find_target_func(
                    ''.join(file_content), target_func)
            except Exception as e:
                console.log(f"Error finding target function: {e}")
                continue
            if not (start_line <= line_num <= end_line):
                continue
        file_content[line_num - 1] = file_content[line_num - \
            1].rstrip() + f" {custom_string}\n"
    return file_content


def format_file_content(file_path: str, file_content: List[str]) -> str:
    separator = '-' * 80
    header = f"{separator}\n# {file_path}\n{separator}"
    footer = separator
    return f"{header}\n{''.join(file_content)}\n{footer}"


def write_output_file(output_file: Path, content: str) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open('w') as file:
        file.write(content)


def get_lines_of_function_signature(file_content: List[str]) -> List[int]:
    """Given the file content, return the line numbers with function signatures.

    Args:
        file_content (List[str]): List of strings representing the file content.

    Returns:
        List[int]: Line numbers where function signatures are found.
        Note that the first line is numbered as 1.
    """

    class FunctionSignatureVisitor(ast.NodeVisitor):
        def __init__(self):
            self.function_lines = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            # Append all lines from the start to the end of the function
            # signature
            start_line = node.lineno
            end_line = node.body[0].lineno - 1 if node.body else node.lineno
            self.function_lines.extend(range(start_line, end_line + 1))
            self.generic_visit(node)

    # Parse the file content into an AST tree
    try:
        tree = ast.parse("".join(file_content))
    except Exception as e:
        console.log(f"Error parsing file content: {e}")
        raise e
    visitor = FunctionSignatureVisitor()
    visitor.visit(tree)

    return visitor.function_lines


def get_lines_of_class_definition(file_content: List[str]) -> List[int]:
    """Given the file content, return the line numbers with class definitions.

    Args:
        file_content (List[str]): List of strings representing the file content.

    Returns:
        List[int]: Line numbers where class definitions are found.
        Note that the first line is numbered as 1.
    """

    class ClassDefinitionVisitor(ast.NodeVisitor):
        def __init__(self):
            self.class_lines = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            # Append all lines from the start to the end of the class
            # definition
            start_line = node.lineno
            end_line = node.body[0].lineno - 1 if node.body else node.lineno
            self.class_lines.extend(range(start_line, end_line + 1))
            self.generic_visit(node)

    # Parse the file content into an AST tree
    try:
        tree = ast.parse("".join(file_content))
    except Exception as e:
        console.log(f"Error parsing file content: {e}")
        raise e
    visitor = ClassDefinitionVisitor()
    visitor.visit(tree)

    return visitor.class_lines


def shrink_context_size(
        file_content: List[str],
        custom_string: str,
        file_extension: str,
        context_size: int = 1,
        include_class_definition: bool = True,
        include_function_signature: bool = True
) -> List[str]:
    """
    Given the file content, drop all lines that are further than context_size from any line ending with custom_string.
    There are multiple lines ending with custom_string, consider all of them.
    Return the new file content.
    """
    uncovered_indices = [
        i for i, line in enumerate(file_content)
        if line.rstrip().endswith(custom_string)]
    context_lines = set()
    if file_extension == 'py':
        try:
            if include_class_definition:
                class_definitions = get_lines_of_class_definition(file_content)
                context_lines.update([i - 1 for i in class_definitions])
            if include_function_signature:
                function_signatures = get_lines_of_function_signature(
                    file_content)
                context_lines.update([i - 1 for i in function_signatures])
        except Exception as e:
            console.log(f"Error while processing file content: {e}")
            raise e
    else:
        if include_class_definition:
            warnings.warn(
                "Class definitions are only supported for Python files.")
        if include_function_signature:
            warnings.warn(
                "Function signatures are only supported for Python files.")
    for index in uncovered_indices:
        start = max(0, index - context_size)
        end = min(len(file_content), index + context_size + 1)
        context_lines.update(range(start, end))

    # Add two artificial lines between clusters
    artificial_lines = ['...\n']
    new_content = []
    last_index = -1

    for i, line in enumerate(file_content):
        if i in context_lines:
            if last_index != -1 and i > last_index + 1:
                new_content.extend(artificial_lines)
            new_content.append(line)
            last_index = i

    return new_content


def shrink_context_size_no_marker(
        file_content_str: str,
        lines_of_interest: List[int],
        file_extension: str,
        context_size: int = 1,
        include_class_definition: bool = True,
        include_function_signature: bool = True
) -> str:
    """
    Drop lines that are farther than context_size from any line of interest.
    Also keep class/function definitions if file is Python and flags are set.
    Insert an artificial '...\n' line between separated clusters of kept lines.

    :param file_content_str: The file content as a single string.
    :param lines_of_interest: 0-based indices of lines to keep.
    :param file_extension: The file extension (e.g., 'py' for Python).
    :param context_size: Number of lines of context to keep on each side.
    :param include_class_definition: If True, keep lines with class definitions (Python only).
    :param include_function_signature: If True, keep lines with function signatures (Python only).
    :return: A new string containing only the relevant lines + context (and '...\n' separators).
    """

    # Split into lines, retaining end-of-line characters
    file_lines = file_content_str.splitlines(keepends=True)

    # We'll collect the lines we definitely want to keep in a set
    # (class definitions, function signatures, or lines of interest).
    context_lines = set()

    # For Python, optionally preserve class/function signatures
    if file_extension == 'py':
        if include_class_definition:
            class_definitions = get_lines_of_class_definition(file_lines)
            context_lines.update(class_definitions)
        if include_function_signature:
            function_signatures = get_lines_of_function_signature(file_lines)
            context_lines.update(function_signatures)
    else:
        if include_class_definition:
            warnings.warn(
                "Class definitions are only supported for Python files.")
        if include_function_signature:
            warnings.warn(
                "Function signatures are only supported for Python files.")

    # For each line of interest, we keep that line plus the ± context_size
    # lines
    for idx in lines_of_interest:
        start = max(0, idx - context_size)
        end = min(len(file_lines), idx + context_size + 1)
        context_lines.update(range(start, end))

    new_content = []
    last_index = -1
    # We'll insert these lines when there's a gap between clusters
    artificial_lines = ['...\n']

    for i, line in enumerate(file_lines):
        # context_lines are 1-based line numbers
        if i + 1 in context_lines:
            # If there's a gap from the previous cluster, insert artificial
            # lines
            if last_index != -1 and i > last_index + 1:
                new_content.extend(artificial_lines)
            new_content.append(line)
            last_index = i

    return "".join(new_content)


@click.command()
@click.option('--json-file', required=True, type=click.Path(
    exists=True, path_type=Path),
    help='Path to the JSON file.')
@click.option('--source-dir', required=True, type=click.Path(
    exists=True, file_okay=False, path_type=Path),
    help='Directory containing the source files.')
@click.option('--output-file', required=True, type=click.Path(
    path_type=Path),
    help='Path to the output file.')
@click.option('--custom-string', default='# UNCOVERED',
              help='Custom string to append to uncovered lines.')
@click.option('--context-size', default=None, type=int,
              help='Context size for uncovered lines.')
def main(json_file: Path, source_dir: Path, output_file: Path,
         custom_string: str, context_size: int) -> None:
    process_json_file(json_file, source_dir, output_file,
                      custom_string, context_size)


if __name__ == '__main__':
    main()

    # Example usage:
    # python -m approach.coverage.formatter --json-file
    # /path/to/current_relevance.json --source-dir /path/to/source/files
    # --output-file /path/to/pr_uncovered_lines.txt --custom-string "#
    # UNCOVERED"
