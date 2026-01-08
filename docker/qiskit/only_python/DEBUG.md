To test the dockerimage in isolation, use the following command:
```shell
docker build \
    --build-arg UID=$(id -u) \
    --build-arg GID=$(id -g) \
    --build-arg PR_NUMBER=14424 \
    --build-arg PYTHON_TEST_PATH="test.python.circuit.library.test_adders" \
    -t qiskit-pr-14424-test -f dockerfile .
```
This will run only a small subset of the tests, which is useful for debugging the creation of the coverage report.

Run it interactively:
```shell
docker run -it --rm \
    --user $(id -u):$(id -g) \
    --name qiskit-pr-14424-test \
    qiskit-pr-14424-test bash
# print the head of the coverage_all.xml file
cat /opt/qiskit/coverage_all.xml | head -n 20
# run the single test
cd /opt/qiskit
python3 -m stestr run test.python.circuit.library.test_adders  --slowest
```

Build with full test suite:
```shell
docker build \
    --build-arg UID=$(id -u) \
    --build-arg GID=$(id -g) \
    --build-arg PR_NUMBER=14424 \
    -t qiskit-pr-14424-test -f dockerfile .
```

Copy the coverage report to the host:
```shell
docker cp qiskit-pr-14424-test:/opt/qiskit/coverage_all.xml .
```