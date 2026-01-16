To test the dockerimage in isolation, use the following command:
```shell
docker build \
    --build-arg UID=$(id -u) \
    --build-arg GID=$(id -g) \
    --build-arg PR_NUMBER=13496 \
    --build-arg PYTHON_TEST_PATH="test.python.circuit.library.test_adders" \
    --build-arg RUST_TEST_PATH="crates/circuit/src/*" \
    -t qiskit-pr-13496-test -f dockerfile .
```
This will run only a small subset of the tests, which is useful for debugging the creation of the coverage report.

Run it interactively:
```shell
docker run -it \
    --user $(id -u):$(id -g) \
    --name qiskit-pr-13496-test \
    qiskit-pr-13496-test bash
# print the head of the coverage_all.xml file
cat /opt/qiskit/coverage_all.xml | head -n 20
```

Build with full test suite:
```shell
docker build \
    --build-arg UID=$(id -u) \
    --build-arg GID=$(id -g) \
    --build-arg PR_NUMBER=13496 \
    -t qiskit-pr-13496-test -f dockerfile .
```