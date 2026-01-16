cd /workspace
pytest -n auto -m "not slow and not network and not db and not single_cpu" --cov={proj} --cov-report=xml:regression_cov.xml /opt/pandas/pandas/tests/arrays/ > /dev/null 2>&1