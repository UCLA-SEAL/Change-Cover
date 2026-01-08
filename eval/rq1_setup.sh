#!/bin/bash

cd "$(dirname "$0")"/..
echo "Setting up RQ1 environment..."
echo "ChaCo root directory: $(pwd)"

## Revert Dockerfiles to the ones used in RQ versions
echo "Reverting Dockerfiles to RQ versions..."
mv docker/scipy/full_test_suite/dockerfile  docker/scipy/full_test_suite/dockerfile_dev
cp docker/scipy/full_test_suite/dockerfile-1.16  docker/scipy/full_test_suite/dockerfile

## Make data directory
mkdir -p data/test_augmentation/rq1
mkdir -p data/test_augmentation/rq1/scipy && \
 mkdir -p data/test_augmentation/rq1/qiskit && \
 mkdir -p data/test_augmentation/rq1/pandas 

### Hardcode the benchmark PRs
printf "%s\n" \
  20543 23028 20382 22393 20722 20320 20789 20753 20137 21700 \
  21783 22554 21074 22969 22475 21216 21713 22755 22896 20438 \
  21076 21505 21996 22983 22099 22304 21819 21223 21551 20811 \
  21332 22037 21528 22616 22555 20773 22401 20284 21389 21485 \
  21435 22170 22222 21777 21462 22358 22549 22373 20349 21637 \
> data/test_augmentation/rq1/scipy/pr_list_filtered.txt

printf "%s\n" \
  12335 12369 12380 12474 12483 12495 12561 12579 12608 12705 \
  12767 12770 12775 12776 12785 12799 12814 12825 12848 12898 \
  12904 12927 12952 12963 12979 13214 13251 13343 13357 13375 \
  13450 13530 13531 13539 13596 13601 13624 13643 13704 13801 \
  13922 14024 14132 14143 14217 14275 14353 14381 14417 14529 \
> data/test_augmentation/rq1/qiskit/pr_list_filtered.txt

printf "%s\n" \
  59682 59928 60940 59626 60713 60505 60742 60333 59686 60413 \
  60739 60196 59624 61216 60295 59555 60191 60541 61578 60871 \
  59768 59501 59854 59114 58370 59141 59488 59034 59142 61173 \
  58792 60518 58893 58314 59254 58767 58791 60586 60637 60652 \
  60584 58886 61467 59544 59441 \
> data/test_augmentation/rq1/pandas/pr_list_filtered.txt



screen -L -Logfile rq1_scipy_patch_coverage.log \
  python -m approach.pipeline.compute_patch_coverage \
    --pr_list "data/test_augmentation/rq1/scipy/pr_list_filtered.txt" \
    --repo "scipy/scipy" \
    --output_dir "data/test_augmentation/rq1" \
    --workers=4