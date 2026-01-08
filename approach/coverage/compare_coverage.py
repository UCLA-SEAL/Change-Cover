import json
import xml.etree.ElementTree as ET
from unidiff import PatchSet
import sys


# Helper function to clean up filenames, stripping off "b/" if present.
def clean_filename(filename):
    return filename[2:] if filename.startswith("b/") else filename


def parse_diff_file(diff_path):
    """
    Parse a unified diff file using unidiff.PatchSet to extract changed (added)
    line numbers per file.
    
    Only the added lines (i.e. the new lines with changes) are recorded.
    
    Args:
        diff_path (str): Path to the unified diff file.
        
    Returns:
        dict: Mapping from filename (as in the diff's target file) to a set of 
              line numbers that were added/changed.
              Example: {"src/foo.py": {10, 11, 15}, "lib/bar.py": {5, 6}}
    """
    file_changes = {}

    with open(diff_path, 'r', encoding='utf-8') as diff_file:
        patch = PatchSet(diff_file)

    # Iterate over each patched file in the diff.
    for patched_file in patch:
        # Use the target file name; if not available, fall back to the patch's file path.
        filename = patched_file.target_file or patched_file.path
        # Initialize with an empty set.
        file_changes.setdefault(filename, set())

        # Iterate through hunks in this file.
        for hunk in patched_file:
            # Within each hunk, iterate over each line.
            for line in hunk:
                if line.is_added:
                    # line.target_line_no holds the new line number.
                    if line.target_line_no is not None:
                        file_changes[filename].add(line.target_line_no)
                        
    return file_changes


def parse_coverage_xml(xml_path):
    """
    Parse an XML coverage file (e.g. produced by coverage.py) and extract the covered lines.
    
    The function creates a dictionary that maps filenames to a set of line numbers
    that have been executed (i.e., lines with hits > 0).
    
    Args:
        xml_path (str): Path to the XML coverage file.
    
    Returns:
        covered_lines (dict): A mapping of filenames to sets of covered line numbers.
        coverable_lines (dict): A mapping of filenames to sets of line numbers that can be covered.
    """
    covered_lines = {}
    coverable_lines = {}
    tree = ET.parse(xml_path)
    root = tree.getroot()
    
    # This example assumes the XML structure similar to that from coverage.py,
    # where each <class> element has a 'filename' attribute and a child <lines>
    # element containing <line> subelements.
    for cls in root.findall(".//class"):
        filename = cls.get("filename")
        if not filename:
            continue
        filename = filename.strip()
        covered_lines.setdefault(filename, set())
        coverable_lines.setdefault(filename, set())

        lines_elem = cls.find("lines")
        if lines_elem is None:
            continue

        for line_elem in lines_elem.findall("line"):
            num = line_elem.get("number")
            hits = line_elem.get("hits")
            if num is not None and hits is not None:
                coverable_lines[filename].add(int(num))
            if num is not None and hits is not None and int(hits) > 0:
                covered_lines[filename].add(int(num))
                
    return covered_lines, coverable_lines


def compute_coverage(diff_changes, coverage_data):
    """
    Compare changed lines (from the diff) with coverage data, and group results by file.
    
    For each file, the function groups changed lines into:
      - 'covered' if the changed line is in the coverage data (and has non-zero hits).
      - 'missed' if it is not in the coverage data.
      
    Filenames with the "b/" prefix (common from git diffs) will have that prefix stripped.
    
    The function returns a dictionary with two keys, "covered" and "missed". Each key maps to
    a list of dictionaries, where each dictionary represents a file with the keys:
         - "file": the filename with any "b/" prefix removed.
         - "lines": a list of changed line numbers that were covered or missed.
    
    Args:
        diff_changes (dict): A mapping of filenames to sets of changed line numbers.
        coverage_data (dict): A mapping of filenames to sets of covered line numbers.
        
    Returns:
        dict: A dictionary in the following format:
            {
                "missed": [
                    {
                        "file": "/keras/src/layers/rnn/gru.py",
                        "lines": [134, 135]
                    }
                ],
                "covered": [
                    {
                        "file": "another_file.py",
                        "lines": [10, 20]
                    }
                ]
            }
    """

    covered_by_file = {}
    missed_by_file = {}
    
    for file, changed_lines in diff_changes.items():
        # Clean the filename for use in the output.
        clean_file = clean_filename(file)
        # Retrieve covered lines for the file; default to an empty set.
        file_covered = coverage_data.get(clean_file, set())
        for line_number in changed_lines:
            if line_number in file_covered:
                covered_by_file.setdefault(clean_file, []).append(line_number)
            else:
                missed_by_file.setdefault(clean_file, []).append(line_number)
    
    # Convert the dictionaries to lists of dictionaries in the desired format.
    covered_output = []
    for file, lines in covered_by_file.items():
        covered_output.append({
            "file": file,
            "lines": sorted(lines)
        })
    
    missed_output = []
    for file, lines in missed_by_file.items():
        missed_output.append({
            "file": file,
            "lines": sorted(lines)
        })
    
    return {"covered": covered_output, "missed": missed_output}



def get_coverage_json(diff_path, xml_path):
    """
    Convenience function that, given paths to a unified diff file and an XML 
    coverage file, computes the coverage details for the changed lines and 
    returns a JSON-formatted string.
    
    The JSON object has two keys:
      - "missed": the changed lines that were not executed.
      - "covered": the changed lines that were executed.
    
    Note: Sets are converted to sorted lists because JSON does not support sets.
    
    Args:
        diff_path (str): Path to the unified diff file.
        xml_path (str): Path to the XML coverage file.
        
    Returns:
        dict: A dictionary with keys "missed" and "covered" containing lists of identifiers.
    """

    def clean_coverage_data_dir_prefix(coverage_data: dict):
        """
        Clean the coverage data dict by removing the directory prefix from the keys.
        e.g. "/opt/project/subproject/src/foo.py" -> "subproject/src/foo.py"
        """

        cleaned_coverage_data = {}
        for filename, lines in coverage_data.items():
            cleaned_filename = filename.split("/", 3)[-1]
            cleaned_coverage_data[cleaned_filename] = lines
        return cleaned_coverage_data
    
    diff_changes = parse_diff_file(diff_path)
    coverage_data, coverable_data = parse_coverage_xml(xml_path)
    coverage_data = clean_coverage_data_dir_prefix(coverage_data)
    coverable_data = clean_coverage_data_dir_prefix(coverable_data)

    # -- Filter out lines that do not appear in coverable data.
    filtered_diff_changes = {}
    for filename, changed_lines in diff_changes.items():
        # Only consider this file if it’s in the coverable data
        filename = clean_filename(filename)
        if filename in coverable_data:
            coverable_lines = coverable_data[filename]
            # Keep only changed lisnes that coverage can actually track.
            filtered_diff_changes[filename] = [
                line for line in changed_lines if line in coverable_lines
            ]

    # -- Compute coverage on the filtered changes.
    result = compute_coverage(filtered_diff_changes, coverage_data)
    
    return result

def test_coverable_data():
    # Test get_coverage_json
    result = get_coverage_json("/home/MYID/compiler-pr-analysis/data/test_augmentation/003/scipy/pr/diffs/22352.diff", 
                      "/tmp/regression_cov_22352.xml")
    assert result['missed'] == [{'file': 'scipy/stats/_quantile.py', 'lines': [23, 24, 25, 259, 260, 261]}], "Wrong missed lines"


if __name__ == "__main__":
    test_coverable_data()
    