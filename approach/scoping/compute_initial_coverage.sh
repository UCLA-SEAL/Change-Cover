# Task Description
# Objective: Create a Bash script that processes a list of pull request (PR) numbers from a given text file, builds a Docker image for each PR, runs a Docker container to copy a specific file, and then cleans up the Docker image to reclaim space. The copied files should be stored in a structured output directory.

# Requirements:

# Input:

# A text file containing PR numbers, one per line.
# The path to this text file will be provided as the first argument to the script.
# Output:

# An output directory where the copied files will be stored.
# The path to this output directory will be provided as the second argument to the script.
# Each PR will have its own subdirectory within the output directory.
# Docker Build:

# Use the Dockerfile located at dockerfile.
# Build the Docker image with the following command:
# Docker Run:

# Run the Docker container to copy the file coverage_all.xml from the container to the host:
# Ensure that the <PR_NUMBER> directory is created within the output directory before running the container.
# Cleanup:

# Remove the Docker image after processing each PR to reclaim space:
# Error Handling:

# Log any errors encountered during the build, run, or cleanup steps.
# Continue processing the next PR even if an error occurs.
# Logging:

# Create a log file to record the progress and any errors encountered.
# Include a summary report at the end of the script execution.
# Execution:

# Execute the script sequentially, processing one PR at a time.

#!/bin/bash

# Kill all child processes upon Ctrl+C
trap "echo 'Caught Ctrl+C. Killing child processes...'; kill 0" SIGINT

# Parse named options
N=1  # Default: 1 worker (no parallel execution)
while [[ "$#" -gt 0 ]]; do
  case $1 in
    --pr_list) PR_LIST_FILE="$2"; shift ;;
    --output_dir) OUTPUT_DIR="$2"; shift ;;
    --proj) PROJ="$2"; shift ;;
    --workers) N="$2"; shift ;;
    *)
      echo "Unknown parameter passed: $1"
      exit 1
      ;;
  esac
  shift
done

# Check if all required arguments are provided
if [ -z "$PR_LIST_FILE" ] || [ -z "$OUTPUT_DIR" ] || [ -z "$PROJ" ]; then
  echo "Usage: $0 --pr_list <path_to_pr_list.txt> --output_dir <output_directory> --proj <project_name>"
  exit 1
fi
DOCKERFILE_PATH="docker/$PROJ/full_test_suite/"
LOG_FILE="script_$PROJ.log"

echo "Script execution started at $(date)" > "$LOG_FILE"
echo "PR list file: $PR_LIST_FILE" >> "$LOG_FILE"
echo "Output directory: $OUTPUT_DIR" >> "$LOG_FILE"
echo "Project name: $PROJ" >> "$LOG_FILE"
echo "Number of workers: $N" >> "$LOG_FILE"

# Create the output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"

# Create a coverage directory within the output directory
OUTPUT_COVERAGE_DIR="$OUTPUT_DIR/coverage"
mkdir -p "$OUTPUT_COVERAGE_DIR"

# Create a diffs directory within the output directory
OUTPUT_DIFFS_DIR="$OUTPUT_DIR/diffs"
mkdir -p "$OUTPUT_DIFFS_DIR"

# Function to process each PR - Collect Coverage
process_pr_collect_coverage() {
  PR_NUMBER=$1
  PR_OUTPUT_COVERAGE_DIR="$OUTPUT_COVERAGE_DIR/$PR_NUMBER"
  mkdir -p "$PR_OUTPUT_COVERAGE_DIR"
  echo "docker image name: $PROJ-pr-$PR_NUMBER" >> "$LOG_FILE"

  # check if the output exists already, skip this PR
    if [ -f "$PR_OUTPUT_COVERAGE_DIR/coverage_all.xml" ]; then
        echo "Output file (coverage_all.xml) already exists for PR $PR_NUMBER" >> "$LOG_FILE"
        return
    fi

  # Build the Docker image
  docker build --build-arg UID=$(id -u) --build-arg GID=$(id -g) --build-arg PR_NUMBER="$PR_NUMBER" -t "$PROJ-pr-$PR_NUMBER" "$DOCKERFILE_PATH"
  if [ $? -ne 0 ]; then
    echo "Error building Docker image for PR $PR_NUMBER" >> "$LOG_FILE"
    return
  fi

  echo "Successfully created Docker for PR $PR_NUMBER" >> "$LOG_FILE"
  echo "Check it interactively with:" >> "$LOG_FILE"
  echo "docker run --rm -it $PROJ-pr-$PR_NUMBER /bin/bash" >> "$LOG_FILE"
  # exit 0

  ABS_PATH_PR_OUTPUT_COVERAGE_DIR=$(realpath "$PR_OUTPUT_COVERAGE_DIR")

  # Run the Docker container to copy the file
  docker run --rm -v "$ABS_PATH_PR_OUTPUT_COVERAGE_DIR:/mnt" "$PROJ-pr-$PR_NUMBER" /bin/bash -c "cp /opt/$PROJ/coverage_all.xml /mnt/coverage_all.xml" >> "$LOG_FILE" 2>&1
  # docker run --rm -v "/home/MYID/projects/PROJECT_PARENT/compiler-pr-analysis/data/tests_artifacts/qiskit_single_patch/coverage:/mnt" "qiskit-pr-13758-custom" /bin/bash -c "cp /opt/qiskit/coverage_all.xml /mnt/coverage_all.xml"
  # enter interactively
  # docker run --rm -it -v "/home/MYID/projects/PROJECT_PARENT/compiler-pr-analysis/data/tests_artifacts/qiskit_single_patch/coverage:/mnt" "qiskit-pr-13758-custom" /bin/bash
  if [ $? -ne 0 ]; then
    echo "Error running Docker container for PR $PR_NUMBER" >> "$LOG_FILE"
    return
  fi


  # Remove the Docker image to reclaim space
  # Disabled, as we need the docker images to run LLM-generated tests
  # docker rmi "$PROJ-pr-$PR_NUMBER" >> "$LOG_FILE" 2>&1
  # if [ $? -ne 0 ]; then
  #   echo "Error removing Docker image for PR $PR_NUMBER" >> "$LOG_FILE"
  #   return
  # fi

#   python -m approach.coverage.get_relevance --diff_path data/test_augmentation/003/qiskit/diffs/13055.diff --coverage_path data/test_augmentation/003/qiskit/coverage/13055/coverage_all.xml --output_path data/test_augmentation/003/qiskit/coverage/13055/current_relevance.json --verbose

  echo "Successfully processed PR $PR_NUMBER" >> "$LOG_FILE"
}

process_pr_get_relevance() {
  PR_NUMBER=$1
  PR_OUTPUT_COVERAGE_DIR="$OUTPUT_COVERAGE_DIR/$PR_NUMBER"

  # check if the output exists already, skip this PR
    if [ -f "$PR_OUTPUT_COVERAGE_DIR/current_relevance.json" ]; then
        echo "Output file (current_relevance.json) already exists for PR $PR_NUMBER" >> "$LOG_FILE"
        return
    fi

  # Run the get_relevance script
  python -m approach.coverage.get_relevance --diff_path "$OUTPUT_DIFFS_DIR/$PR_NUMBER.diff" --coverage_path "$PR_OUTPUT_COVERAGE_DIR/coverage_all.xml" --output_path "$PR_OUTPUT_COVERAGE_DIR/current_relevance.json" --verbose >> "$LOG_FILE" 2>&1

  missed_lines=$?
  if [ $missed_lines -eq 255 ]; then
    echo "All lines are covered by regression tests for PR $PR_NUMBER" >> "$LOG_FILE"
    echo "Removing docker image for PR $PR_NUMBER" >> "$LOG_FILE"
    docker rmi "$PROJ-pr-$PR_NUMBER" >> "$LOG_FILE" 2>&1
    return
  fi
}

count=0

while IFS= read -r PR_NUMBER; do
  # Skip empty lines
  if [ -z "$PR_NUMBER" ]; then
    continue
  fi

  # If we're already running N jobs, wait for one to finish
  if (( count >= N )); then
    wait -n
    ((count--))
  fi

  {
    process_pr_collect_coverage "$PR_NUMBER"
    process_pr_get_relevance "$PR_NUMBER"
  } &  # Run in background

  ((count++))
done < "$PR_LIST_FILE"

# Wait for any leftover background jobs
wait

echo "Script execution completed at $(date)" | tee -a "$LOG_FILE"
echo "Check $LOG_FILE for details."