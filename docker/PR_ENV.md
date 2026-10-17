# Per-PR environments

`docker/{scipy,pandas,qiskit}/pr_env/` build a light image of one benchmark pull request: the
repository checked out and installed in editable mode, ready to run tests. Unlike the
`full_test_suite` images, nothing is run at build time.

```bash
docker build --build-arg PR_NUMBER=21700 -t scipy-pr-21700 docker/scipy/pr_env
docker run --rm -it scipy-pr-21700 bash
```

- `CHECKOUT=base` (default) is the commit the PR was merged into, `merge` the merge commit,
  `pr` the PR's head. The repository lives in `/opt/<repo>` with git tags `pr-base` and
  `pr-merge`, so `git diff pr-base pr-merge` is the PR's change.
- `prs.json` gives each PR's base commit, merge commit, and the date dependencies are resolved
  at (`uv pip install --exclude-newer`), so older PRs build with the packages of their time.
- Optional build args are listed at the top of each Dockerfile (`OPENBLAS_CORETYPE`,
  SciPy's `PYTEST_ADDOPTS`, pandas' `PANDAS_FUTURE_INFER_STRING`).
- Qiskit compiles a Rust extension: after changing Rust code, run `pip install -e .` again.
