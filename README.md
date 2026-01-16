# Change and Cover

[![ICSE 2026](https://img.shields.io/badge/ICSE-2026-blue)](https://conf.researchr.org/home/icse-2026)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## Overview
**Change and Cover (ChaCo)** is an approach to automatically generate high-quality regression tests to cover the uncovered lines in pull requests (PRs). It leverages large language models (LLMs) to generate test cases based on the code changes in the PRs and the existing test suite. Unlike traditional test generation techniques, ChaCo aims to generate ready-to-merge regression tests that minimize the developer effort required to integrate them into the codebase.

<img src= "assets/workflow_w_codebase_rev.png" alt="ChaCo Workflow" style="border: 10px solid white;">

## Install ChaCo

### Prerequisites
- Conda
- Docker

Clone the repository and create the virtual environment::
```bash
git clone https://github.com/UCLA-SEAL/Change-Cover.git
cd Change-Cover
conda env create -f environment.yml
conda activate chaco
```

## Running ChaCo
### [Preparation] Local Test Suite with Dockerfile
> Note: The following steps use SciPy as an example project to demonstrate how to use ChaCo.

To use ChaCo to generate tests for a project, first, you need to have a Dockerfile that simulates the test suite run environment of the project.

See an example: [Dockerfile for SciPy](docker/scipy/full_test_suite/dockerfile). It pulls and builds SciPy **at a PR**, runs the regression test suite, and places the coverage file in `/opt/scipy/coverage_all.xml`. We recommend referring to the CI builder of the target project to simulate the test environment as closely as possible.

#### API Token

Add the GitHub API token to the `secrets/github_token.txt` file. This token is used to access the GitHub API to fetch PRs and other data.

Add the OpenAI API token to the `secrets/openai_token.txt` file. This token is used to access the OpenAI API for generating test cases. For other LLM providers, refer to the Config section below.

### [Step 1] Collect the PRs to use

First, ChaCo needs to collect the target PRs that do not have 100% of patch coverage.

1. Create a config file to specify the projects and PR selection criteria. For example, see [`config/benchmark_creation/v001.yaml`](config/benchmark_creation/v001.yaml). 
   - Select the folder where the results will be stored using the field `output_folder`. 
   - The field `num_prs` specifies how many recent PRs to analyze per project (check your Github API quota). 
   - The field `pr_state` specifies whether to analyze `open`, `merged`, or 'all` PRs. 
   - Other fields specify exclusion criteria (e.g., exclude PRs that contain title keywords, labels, or modifies files under a path).

2. Run the script to select suitable PRs for SciPy:
   ```bash
   screen -L -Logfile select_scipy_pr.log python -m approach.scoping.pr_selection --config config/benchmark_creation/v001.yaml --benchmark_projects scipy/scipy
   ```
   This will create a new file at path `data/test_augmentation/001/pr_list_filtered.txt` containing the PRs that were selected based on the criteria defined in the config file. 

### [Step 2] Compute the patch coverage of the PRs
1. To compute the patch coverage of the filtered PRs, run the following command. This will build a Docker image for each PR and store the patch coverage results in the `data/test_augmentation/001` folder.
   ```bash
   screen -L -Logfile scipy_patch_coverage.log python -m approach.pipeline.compute_patch_coverage --pr_list data/test_augmentation/001/scipy/pr_list_filtered.txt --repo scipy/scipy --output_dir data/test_augmentation/001 --workers=4
   ```

4. Identify PRs with uncovered lines:
   ```bash
   python -m approach.pipeline.get_uncovered_prs --repository scipy/scipy --project_name scipy --output_folder data/test_augmentation/001
   ```
   This script produces a json file, e.g., `config/benchmark/scipy_{YYMMDD}.json` that contains the PRs that do not have 100% patch coverage, for which we want to generate test cases.

### [Step 3] Generate Tests with ChaCo

1. To generate tests, ChaCo needs a configuration file specifying the parameters. An example config file is provided at `config/scipy_example.yaml`.
   - `benchmark_name` specifies the path to the PRs to generate tests for (e.g., `config/benchmark/scipy_rq.json`). **Replace it with the json file created in the previous step.**
   - `benchmark_projects` specifies the target projects.
   - `base_dir` specifies the data folder (e.g., `data/test_augmentation/001`).
   - `test_folder_name` specifies the folder name to store the generated tests.
   - `test_generator` class specifies LLM-related parameters.
      - `class_name` is the type of test generator to use. We use ChaCo's full pipeline here. Ablated variants are in [script](approach/evaluate_generator_on_benchmark.py).
      - `model_name` is the LLM model to use (e.g., `openai/gpt-4o-mini`).
      - `integration` needs to be True.
      - `temperature` controls the randomness of the LLM output.
      - `dynamic_test_context` specifies whether to use dynamic test context.
      - `runtime_feedback` specifies whether to iteratively improve tests with dynamic feedback. `max_feedback` controls how many iterations to perform.
   - `num_workers` controls the parallelism of test generation.

2. After modifying the config file, run ChaCo to generate tests:
   ```shell
   screen -L -Logfile scipy_test_gen.log python -m approach.evaluate_generator_on_benchmark --config config/scipy_example.yaml --max_prs 10
   ```
   The tests will be stored in `data/test_augmentation/001/chaco_full`.

### [Step 4] Evaluate Generated Tests
We provide evaluation notebooks to analyze the effectiveness of the tests. 
```bash
cd eval
papermill example.ipynb scipy_results.ipynb \
  -p CONFIG_FILE "config/benchmark/{your PRs}.json" \
  -p REPO_NAME "scipy/scipy" \
  -p ARTIFACT_FOLDER "../data/test_augmentation/001/scipy" \
  -p GENERATOR_NAME_KEY "Full ChaCo" \
  -p FOLDER_WITH_TESTS "chaco_full"
```
Open `scipy_results.ipynb` and check metrics: Pass Rate, PRs fully covered, ...

## Data Availability
To replicate the results of the controlled experiments in our paper, please refer to [REPLICATE.md](REPLICATE.md)  for detailed instructions.

## Citation
Please cite our paper if you use this code:
```bibtex
@inproceedings{zhou2024change,
   title={Change And Cover: Last-Mile, Pull Request-Based Regression Test Augmentation},
   author={Zhou, Zitong and Paltenghi, Matteo and Kim, Miryung and Pradel, Michael},
   booktitle={Proceedings of the 48th International Conference on Software Engineering},
   year={2026},
   organization={ACM}
}
```
## Repository Structure
```
Change-Cover/
├── approach               // ChaCo source code
├── config                 // config files for selecting PRs and running ChaCo
├── docker                 // Dockerfiles for simulating test environments
├── eval                   // evaluation notebooks
├── README.md              // this file
├── REPLICATE.md           // instructions to replicate the experiments
├── data                   // data folder for PR metadata, generated tests, etc
├── pr-test-reviews        // folder for test case reviews
├── secrets                // GitHub and LLM tokens     
├── environment.yml
└── tests
```

## License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknolowledgements
This work is supported by the National Science Foundation under grant numbers 2426162, 2106838, and 2106404, by the European Research Council (ERC; grant agreements 851895 and 101155832), and by the German Research Foundation (DFG; projects 492507603, 516334526, and 526259073). It is also supported in part by funding from Amazon and Samsung.

