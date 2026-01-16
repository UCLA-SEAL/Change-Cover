

import click
"""
This script analyzes the relevance of lines modified by a pull request (PR) in terms of code coverage.
It checks if the lines modified by the PR are triggered in the coverage report.

Usage:
    python get_relevance.py --diff_path <path_to_diff_file> --coverage_path <path_to_coverage_xml> --output_path <path_to_output_xml> [--verbose]

Functions:
    main(diff_path, coverage_path, output_path, verbose):
        Command-line interface entry point. Parses command-line options and calls check_relevance.

    check_relevance(diff_path, coverage_path, output_path, verbose):
        Parses the diff file and coverage xml, analyzes the relevance of modified lines, and saves the result to the output file.
"""
import json
from coverage import Coverage
from unidiff import PatchSet
from xml.etree import ElementTree as ET
from typing import Dict, List
from pathlib import Path


@click.command()
@click.option('--diff_path', required=True, type=click.Path(exists=True),
              help='Path to the diff file.')
@click.option(
    '--coverage_path', required=True, type=click.Path(exists=True),
    help='Path to the coverage xml.')
@click.option('--output_path', required=True, type=click.Path(),
              help='Path to save the output report.')
@click.option('--verbose', is_flag=True, help='Enable verbose output.')
def main(diff_path, coverage_path, output_path, verbose):
    """Check if the lines modified by the PR are triggered in the coverage xml."""
    missed_lines = check_relevance(
        diff_path, coverage_path, output_path, verbose)

    # Exit with 0 if there are missed lines: we are interested in this PR
    if missed_lines:
        exit(0)
    # Exit with -1 if there are no missed lines: we are not interested in this
    # PR
    else:
        exit(-1)


def check_relevance(
        diff_path: str, after_dir: str, coverage_path: str, output_path: str,
        verbose: bool) -> bool:
    """Analyze if lines modified in a PR are covered by tests in the coverage report.

    Parses a diff file to identify added lines of code, then checks if these lines
    appear in the coverage report as either covered or missed. Results are saved to
    the specified output path as JSON.

    Args:
        diff_path (str): Path to the diff file containing PR changes
        after_dir (str): Directory of the project after changes
        coverage_path (str): Path to the coverage XML report
        output_path (str): Path to save the JSON report of covered/missed lines
        verbose (bool): Whether to print progress information

    Returns:
        bool: True if there are missed lines, False otherwise
    """

    # Parse the diff file
    with open(diff_path, 'r') as diff_file:
        diff_content = diff_file.read()
    patch = PatchSet(diff_content)

    # Parse the coverage xml

    tree = ET.parse(coverage_path)
    root = tree.getroot()

    coverage_data = {}
    for package in root.findall('packages/package'):
        for class_ in package.findall('classes/class'):
            filename = class_.get('filename')
            # if the filename starts with /opt then it is the
            # absolute file, we need to recovere the relative path, by removing the first two folders
            # e.g. /opt/pandas/pandas -> pandas
            # e.g. /opt/qiskit/qiskit/terra -> qiskit/terra

            # if the filenames are relative, sometimes the src directory is missing from the path
            # e.g. 'linalg/special_matrices.py' ->
            # 'scipy/linalg/special_matrices.py'
            if "site-packages/" in filename:
                filename = filename.split("site-packages/")[-1]
            elif filename.startswith('/opt'):
                filename = '/'.join(filename.split('/')[3:])

            covered_lines = set()
            missed_lines = set()
            for line in class_.findall('lines/line'):
                line_number = int(line.get('number'))
                if line.get('hits') != '0':
                    covered_lines.add(line_number)
                else:
                    missed_lines.add(line_number)
            coverage_data[filename] = {
                'covered': covered_lines,
                'missed': missed_lines
            }

    # keep data in the patch
    relevant_files = [
        modified_file.path
        for modified_file in patch
    ]
    coverage_data = {
        filename: coverage_data[filename]
        for filename in relevant_files
        if filename in coverage_data.keys()
    }

    # Analyze the diff and coverage
    result = {}
    missed_lines = False
    for modified_file in patch:
        filename = modified_file.path
        if filename.endswith('.py'):  # or filename.endswith('.rs'):
            from coverage.parser import PythonParser
            target_file_path = Path(
                after_dir) / filename
            content = target_file_path.read_text()
            parser = PythonParser(
                text=content,
                filename=filename,
            )
            parser.parse_source()

            covered = set()
            missed = set()
            if filename in coverage_data:
                for hunk in modified_file:
                    for line in hunk:
                        if line.is_added:
                            line_number = line.target_line_no
                            # map to the first executable line
                            # the same used by coveragepy to create
                            # the report
                            exec_line_number = list(
                                parser.first_lines([line_number]))[0]
                            if exec_line_number in coverage_data[filename][
                                    'covered']:
                                covered.add(line_number)
                            elif exec_line_number in coverage_data[filename]['missed']:
                                missed.add(line_number)
                            else:
                                # If the line is not in the coverage data,
                                # we can assume it is docstring or comment
                                # and we can ignore it
                                pass
                # check that we have at least one line
                if len(covered) > 0 or len(missed) > 0:
                    # add the file to the result
                    result[filename] = {
                        'covered': list(sorted(covered)),
                        'missed': list(sorted(missed))
                    }

    # Save the result to the output file
    with open(output_path, 'w') as output_file:
        json.dump(result, output_file, indent=4)

    if verbose:
        click.echo(f'Relevance saved to {output_path}')

    # return True if there are missing lines, False otherwise
    return missed_lines


if __name__ == '__main__':
    main()

    # Example usage:
    # python -m qiskit.get_relevance --diff_path /path/to/diff_file.diff
    # --coverage_path /path/to/coverage_xml.info --output_path
    # /path/to/output_report.json --verbose
