import xml.etree.ElementTree as ET
from unidiff import PatchSet
import click
import json
from rich.console import Console
from rich.table import Table

console = Console()

def parse_diff_file(diff_file):
    """
    Parses a diff file to extract changed lines for Python files.
    """
    with open(diff_file) as f:
        patch = PatchSet(f)
    changed_lines = {}
    for file in patch:
        if file.path.endswith('.py'):  # Focus on Python files
            # We'll collect individual changed lines (not ranges) so it's easier
            # to match them with coverage lines individually.
            changed_lines[file.path] = []
            for hunk in file:
                for line in hunk.target_lines():
                    if line.is_added:  # Only include added lines
                        changed_lines[file.path].append(line.target_line_no)
    return changed_lines


def parse_coverage(coverage_file):
    """
    Parses a coverage XML report to extract covered lines.
    """
    tree = ET.parse(coverage_file)
    root = tree.getroot()
    covered_lines = {}
    for package in root.findall(".//package"):
        for class_ in package.findall("classes/class"):
            filename = class_.get("filename")
            lines = []
            for line in class_.findall("lines/line"):
                if line.get("hits") != "0":  # Line was executed
                    lines.append(int(line.get("number")))
            covered_lines[filename] = lines
    return covered_lines


def assess_relevance(changed_lines, covered_lines):
    """
    Compares changed lines with coverage results to assess relevance.
    Returns a dict containing:
        - relevant_lines: a dict of file -> covered changed lines
        - total_covered: how many changed lines are covered in total
        - total_changed: how many lines changed in total
    """
    relevant_lines = {}
    total_covered = 0
    total_changed = 0

    for file, lines in changed_lines.items():
        if file in covered_lines:
            for line_no in lines:
                total_changed += 1
                if line_no in covered_lines[file]:
                    total_covered += 1
                    if file not in relevant_lines:
                        relevant_lines[file] = []
                    relevant_lines[file].append(line_no)
        else:
            # Even if not in coverage, they are still changed lines
            total_changed += len(lines)

    return relevant_lines, total_covered, total_changed


def generate_report(changed_lines, covered_lines, total_covered, total_changed):
    """
    Generates a detailed report (list of dicts) and a coverage ratio string.
    Each entry in the report is a dict:
        {
          "file": filename,
          "covered": [... list of covered lines ...],
          "missed": [... list of missed lines ...]
        }
    """
    report = []
    for file, changed_line_list in changed_lines.items():
        file_report = {"file": file, "covered": [], "missed": []}
        covered_in_file = covered_lines.get(file, [])
        for line_no in changed_line_list:
            if line_no in covered_in_file:
                file_report["covered"].append(line_no)
            else:
                file_report["missed"].append(line_no)
        report.append(file_report)

    coverage_ratio = (total_covered / total_changed) * 100 if total_changed > 0 else None

    return report, coverage_ratio


@click.command()
@click.option("-v", "--verbose", is_flag=True, default=False, help="Enable verbose output")
@click.argument("diff_file", type=click.Path(exists=True))
@click.argument("coverage_file", type=click.Path(exists=True))
def main(diff_file, coverage_file, verbose):
    """
    Assess the relevance of synthetic tests using a diff file and a coverage report.

    Returns a dict:
    {
        "coverage_ratio": str,
        "covered_lines": list of line numbers,
        "missed_lines": list of line numbers
    }
    """
    # Read diff
    if verbose:
        console.print(f"[bold cyan]Reading diff file:[/bold cyan] {diff_file}")
    changed_lines = parse_diff_file(diff_file)

    # Read coverage
    if verbose:
        console.print(f"[bold cyan]Reading coverage file:[/bold cyan] {coverage_file}")
    covered_lines = parse_coverage(coverage_file)

    # Assess relevance
    if verbose:
        console.print("[bold green]Assessing relevance...[/bold green]")
    relevant_lines, total_covered, total_changed = assess_relevance(changed_lines, covered_lines)

    # Generate report (detailed lines) + coverage ratio
    report, coverage_ratio = generate_report(changed_lines, relevant_lines, total_covered, total_changed)

    # If verbose, print out the report in a table
    if verbose:
        table = Table(title="Synthetic Test Relevance Report")
        table.add_column("File", style="cyan", no_wrap=True)
        table.add_column("Covered Lines", style="green")
        table.add_column("Missed Lines", style="red")

        for file_report in report:
            covered_str = ", ".join(map(str, file_report["covered"])) or "None"
            missed_str = ", ".join(map(str, file_report["missed"])) or "None"
            table.add_row(file_report["file"], covered_str, missed_str)

        console.print(table)
        console.print(f"\n[bold green]Total Changed Lines Covered by Tests:[/bold green] {coverage_ratio}")

    # Flatten covered and missed lines across all files to return
    all_covered = [line for item in report for line in item["covered"]]
    all_missed = [line for item in report for line in item["missed"]]

    # print as a dictionary (deserialized)
    print(json.dumps({
        "coverage_ratio": coverage_ratio,
        "covered_lines": all_covered,
        "missed_lines": all_missed
    }))


if __name__ == "__main__":
    main()
