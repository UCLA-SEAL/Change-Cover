#!/bin/bash

cd "$(dirname "$0")"/..
echo "Setting up RQ3 environment..."
echo "ChaCo root directory: $(pwd)"

## Revert Dockerfiles to the ones used in RQ versions
echo "Reverting Dockerfiles to RQ versions..."
mv docker/scipy/full_test_suite/dockerfile  docker/scipy/full_test_suite/dockerfile_dev
cp docker/scipy/full_test_suite/dockerfile-1.16  docker/scipy/full_test_suite/dockerfile

## Make data directory
mkdir -p data/test_augmentation/rq3/scipy && \
 mkdir -p data/test_augmentation/rq3/qiskit && \
 mkdir -p data/test_augmentation/rq3/pandas

## Run ChaCo
### Ablated Variant 1: LLM Test Context Only
python -m approach.evaluate_generator_on_benchmark --config config/rq3-llm-tc.yaml
### Ablated Variant 2: No Test Context
python -m approach.evaluate_generator_on_benchmark --config config/rq3-no-tc.yaml
### Ablated Variant 3: No Feedback
python -m approach.evaluate_generator_on_benchmark --config config/rq3-no-fb.yaml


### No need to rerun FULL CHACO, just copy it over
for proj in scipy qiskit pandas; do
  cp -r data/test_augmentation/rq1/$proj/test_cases/chaco_full \
    data/test_augmentation/rq3/$proj/test_cases/chaco_full
done