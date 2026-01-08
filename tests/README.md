# Testing

## Unit Tests

The unit tests are located in the same folder of the module they are testing.
Following the convention of the `pytest` framework, the test files are named `test_<module>.py`.

To run the unit tests in the `approach` module, run the following command:
```bash
python -m pytest -s -vv approach
```

## Integration Tests

The integration tests are located in the `tests` folder.
Following the convention of the `pytest` framework, the test files are named `test_<module>.py`.

To run the integration tests, run the following command:
```bash
python -m pytest -s -vv tests
```