To build the Docker image, run the following command in the root directory of the repository:

```bash
docker build --build-arg UID=$(id -u) --build-arg GID=$(id -g) -t qiskit-compiler-pr-analysis docker/qiskit
```

To run the Docker container, run the following command:

```bash
docker run --rm -it qiskit-compiler-pr-analysis
```

To run a new command in the Docker container, run the following command:

```bash
docker run --rm -it -v ${PWD}/tests/example_fuzzed_qiskit_programs:/workspace qiskit-compiler-pr-analysis /bin/bash -c "coverage run --source=/usr/local/lib/python3.10/site-packages/qiskit/transpiler/passes/layout/ test_sabre.py && ls .coverage && coverage xml"
```
Downside: this fails in case the python file crashes.

The following command is more robust:
```bash
docker run --rm -it -v ${PWD}/tests/example_fuzzed_qiskit_programs:/workspace qiskit-compiler-pr-analysis /bin/bash -c "coverage run --source=/opt/qiskit/ test_sabre.py || true && coverage xml"
# another example becomes
# coverage run --source=/usr/local/lib/python3.10/site-packages/qiskit/ /workspace/to_run/program.py || true && coverage xml
docker run --rm -it -v ${PWD}/tests/example_fuzzed_qiskit_programs:/workspace qiskit-compiler-pr-analysis /bin/bash -c "coverage run --source=/opt/qiskit/ test_exception.py"
# debug
docker run --rm \
    -v ${PWD}/data/fake_tmp_folder:/workspace/to_run:rw \
    -v ${PWD}/data/fuzzing_runs/v001/QiskitCompilerEntryPoint/2024_10_11_16_46:/workspace:rw \
    -w /workspace/to_run \
    qiskit-compiler-pr-analysis \
    /bin/bash -c "coverage run --source=/opt/qiskit /workspace/to_run/program.py || true ; coverage xml --data-file='/workspace/to_run/.coverage' -o /workspace/to_run/coverage.xml"

```

Run it in interactive mode:
```bash
docker run --rm -it qiskit-compiler-pr-analysis /bin/bash
# with the volume mounted
docker run --rm -it -v ${PWD}/tests/example_fuzzed_qiskit_programs:/workspace qiskit-compiler-pr-analysis /bin/bash
```


