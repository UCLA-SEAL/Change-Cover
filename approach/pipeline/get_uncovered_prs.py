import re
import os
import pandas as pd
from multiprocessing import Pool
import json
import csv
from typing import List, Dict, Any
from pathlib import Path
from datetime import datetime
import click
from rich.console import Console

console = Console(color_system=None)


def read_json_file(file_path: str) -> Dict[str, Any]:
    with open(file_path, 'r') as file:
        data = json.load(file)
        data["_filename"] = os.path.basename(file_path)
        data["pr_number"] = data["_filename"].split(".")[0]
        return data


def read_all_jsons(dir_path: str) -> pd.DataFrame:
    json_files = [os.path.join(dir_path, f) for f in os.listdir(
        dir_path) if re.match(r'.*\.json$', f)]
    records = []

    with Pool() as pool:
        results = pool.map(read_json_file, json_files)
        records.extend(results)

    return pd.DataFrame(records)


def ensure_output_folder_exists(output_folder: Path) -> None:
    """Ensure the output folder exists, create if missing."""
    if not output_folder.exists():
        output_folder.mkdir(parents=True, exist_ok=True)


def list_pr_folders(coverage_folder: Path) -> List[Path]:
    """List all PR subfolders in the coverage folder."""
    return [
        f for f in coverage_folder.iterdir()
        if f.is_dir() and f.name.isdigit()
    ]


def load_relevance_json(pr_folder: Path) -> Dict[str, Any]:
    """Load current_relevance.json from a PR folder."""
    json_path = pr_folder / "current_relevance.json"
    if not json_path.exists():
        raise FileNotFoundError(f"{json_path} not found.")
    with open(json_path, "r") as f:
        return json.load(f)


def pr_has_missed_lines(relevance_data: Dict[str, Any]) -> bool:
    """Check if any file in relevance_data has missed lines."""
    for file_name, file_data in relevance_data.items():
        # file must not be a test file
        if 'test' not in file_name and file_data.get("missed"):
            if len(file_data["missed"]) > 0:
                return True
    return False


def find_uncovered_prs(
        coverage_folder: Path, prs_to_exclude: List[str]
) -> List[str]:
    """Find PR numbers with at least one missed line."""
    uncovered_prs = []
    pr_folders = list_pr_folders(coverage_folder=coverage_folder)
    for pr_folder in pr_folders:
        try:
            # Skip excluded PRs
            if pr_folder.name in prs_to_exclude:
                continue
            relevance_data = load_relevance_json(pr_folder=pr_folder)
            if pr_has_missed_lines(relevance_data=relevance_data):
                uncovered_prs.append(pr_folder.name)
        except Exception as e:
            console.print(
                f"[yellow]Warning: {e} in PR folder {pr_folder.name}[/yellow]"
            )
    return uncovered_prs


def write_uncovered_prs_csv(
    uncovered_prs: List[str], output_folder: Path
) -> None:
    """Write uncovered PR numbers to a CSV file."""
    csv_path = output_folder / "uncovered_prs.csv"
    # sort uncovered PRs numerically
    uncovered_prs = sorted(uncovered_prs, key=lambda x: int(x))
    with open(csv_path, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["PR Number"])
        for pr_number in uncovered_prs:
            writer.writerow([pr_number])


def write_uncovered_prs_json(
    repository: str,
    uncovered_prs: List[str],
    output_folder: Path,
    project_name: str
) -> None:
    """Write uncovered PR numbers to a JSON file in config/benchmark."""
    config_folder = output_folder / "config" / "benchmark"
    ensure_output_folder_exists(output_folder=config_folder)
    date_str = datetime.now().strftime("%Y-%m-%d")
    json_path = config_folder / f"{project_name}_{date_str}.json"
    data = {
        "projects": {
            repository: {
                "pr_numbers": list(sorted([int(pr) for pr in uncovered_prs]))
            }
        }
    }
    # if the file already exists, create a new one with a timestamp
    if json_path.exists():
        date_and_time = datetime.now().strftime("%Y-%m-%d__%H_%M_%S")
        json_path = config_folder / f"{project_name}_{date_and_time}.json"
    with open(json_path, "w") as f:
        json.dump(data, f, indent=4)
    console.print(
        f"[green]JSON written to {json_path}[/green]"
    )


def get_excluded_prs(inclusion_path: Path) -> List[str]:
    """Get PRs to exclude from the inclusion coverage folder."""
    assert inclusion_path.exists(), (
        f"Inclusion coverage folder {inclusion_path} does not exist."
    )
    df_inclusion = read_all_jsons(dir_path=str(inclusion_path))
    # keep only those with "status" == "excluded"
    df_excluded = df_inclusion[df_inclusion["status"] == "excluded"]
    all_prs = df_excluded["pr_number"].unique()
    print(f"Excluding {len(all_prs)} PRs from inclusion coverage.")
    return all_prs.tolist()


def process_uncovered_prs(
    repository: str, project_name: str, output_folder: str
) -> None:
    """Process and write PRs with missed lines to CSV and JSON."""
    output_path = Path(output_folder)
    ensure_output_folder_exists(output_folder=output_path)
    # get inclusion coverage folder
    inclusion_path = Path(os.path.join(
        output_path, project_name, "inclusion"))
    prs_to_exclude = get_excluded_prs(inclusion_path=inclusion_path)

    coverage_folder = Path(os.path.join(
        output_path, project_name, "coverage"))
    if not coverage_folder.exists():
        console.print(
            f"[red]Coverage folder not found: {coverage_folder}[/red]"
        )
        return
    uncovered_prs = find_uncovered_prs(
        coverage_folder=coverage_folder, prs_to_exclude=prs_to_exclude)
    write_uncovered_prs_csv(
        uncovered_prs=uncovered_prs, output_folder=output_path
    )
    write_uncovered_prs_json(
        repository=repository,
        uncovered_prs=uncovered_prs,
        output_folder=Path("."),
        project_name=project_name
    )
    console.print(
        f"[green]Found {len(uncovered_prs)} uncovered PRs. "
        f"CSV written to {output_path / 'uncovered_prs.csv'}[/green]"
    )


@click.command()
@click.option(
    "--repository",
    required=True,
    type=str,
    help="Name of the repository (e.g., Qiskit/qiskit)."
)
@click.option(
    "--project_name",
    required=True,
    type=str,
    help="Name of the project (e.g., qiskit)."
)
@click.option(
    "--output_folder",
    required=True,
    type=str,
    help="Folder to save the resulting CSV file."
)
def main(
    repository: str, project_name: str, output_folder: str
) -> None:
    """CLI to identify PRs with missed lines in coverage data."""
    process_uncovered_prs(
        repository=repository,
        project_name=project_name,
        output_folder=output_folder
    )


if __name__ == "__main__":
    main()
