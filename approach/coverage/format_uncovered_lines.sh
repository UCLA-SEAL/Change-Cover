#!/bin/bash

# from root:
# sh approach/coverage/format_uncovered_lines.sh --exp_number "005" --proj "qiskit" --context_size "10"

# Default values
exp_number="005"
proj="qiskit"
context_size="10"

# Parse command line arguments
pr_list_filename="pr_list_filtered.txt"
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --exp_number) exp_number="$2"; shift ;;
        --proj) proj="$2"; shift ;;
        --context_size) context_size="$2"; shift ;;
        --pr_list_filename) pr_list_filename="$2"; shift ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

# Read the list of PRs from pr_list.txt
pr_list="data/test_augmentation/${exp_number}/${proj}/${pr_list_filename}"

# Iterate over each PR in the list
while IFS= read -r pr; do
    # Define paths based on the PR
    json_file="data/test_augmentation/${exp_number}/${proj}/coverage/${pr}/current_relevance.json"
    source_dir="data/test_augmentation/${exp_number}/${proj}/file_content/${pr}/after"
    output_file="data/test_augmentation/${exp_number}/${proj}/coverage/${pr}/pr_uncovered_lines.txt"

    # Call the function with the specified parameters
    python -m approach.coverage.formatter --json-file "$json_file" --source-dir "$source_dir" --output-file "$output_file" --custom-string "# UNCOVERED" --context-size "$context_size"
done < "$pr_list"