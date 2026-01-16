## PR Title: Add test for nchypergeom_fisher handling NaN values

## PR Description: 
This pull request adds a new test to improve coverage for the `nchypergeom_fisher` distribution in the `scipy.stats` module. The test verifies that the `_stats` method correctly handles NaN inputs for parameters `M`, `n`, and `N`, ensuring that the function returns NaN for moments as expected. This enhancement addresses previously uncovered lines in the original pull request #22969, contributing to the robustness of the SciPy library's discrete distribution functionality.

## Lines Incremented by this Test
| File | Block | Permalink |
| ---- | ----- | --------- |
| scipy/stats/_discrete_distns.py | 1918 | [Here](https://github.com/mdhaber/scipy/blob/0c1945395d16945f7de749008f2c214f4440b97e/scipy/stats/_discrete_distns.py#L1918) |
## Lines Increment Visualization
```python
--------------------------------------------------------------------------------
# scipy/stats/_discrete_distns.py
--------------------------------------------------------------------------------
        x_min = np.maximum(0, n - m2)
        x_max = np.minimum(n, m1)
        return x_min, x_max

    def _argcheck(self, M, n, N, odds):
        M, n = np.asarray(M), np.asarray(n),
        N, odds = np.asarray(N), np.asarray(odds)
        cond1 = (~np.isnan(M)) & (M.astype(int) == M) & (M >= 0)
        cond2 = (~np.isnan(n)) & (n.astype(int) == n) & (n >= 0)
        cond3 = (~np.isnan(N)) & (N.astype(int) == N) & (N >= 0)
        cond4 = odds > 0
        cond5 = N <= M
        cond6 = n <= M
        return cond1 & cond2 & cond3 & cond4 & cond5 & cond6

    def _rvs(self, M, n, N, odds, size=None, random_state=None):

        @_vectorize_rvs_over_shapes
        def _rvs1(M, n, N, odds, size, random_state):
            if np.isnan(M) | np.isnan(n) | np.isnan(N):
                return np.full(size, np.nan)
            length = np.prod(size)
            urn = _PyStochasticLib3()
            rv_gen = getattr(urn, self.rvs_name)
            rvs = rv_gen(N, n, M, odds, length, random_state)
            rvs = rvs.reshape(size)
            return rvs

        return _rvs1(M, n, N, odds, size=size, random_state=random_state)

    def _pmf(self, x, M, n, N, odds):

        x, M, n, N, odds = np.broadcast_arrays(x, M, n, N, odds)
        if x.size == 0:  # np.vectorize doesn't work with zero size input
            return np.empty_like(x)

        @np.vectorize
        def _pmf1(x, M, n, N, odds):
            if np.isnan(x) | np.isnan(M) | np.isnan(n) | np.isnan(N):
                return np.nan
            urn = self.dist(N, n, M, odds, 1e-12)
            return urn.probability(x)

        return _pmf1(x, M, n, N, odds)

    def _stats(self, M, n, N, odds, moments='mv'):

        @np.vectorize
        def _moments1(M, n, N, odds):
            if np.isnan(M) | np.isnan(n) | np.isnan(N):
                return np.nan, np.nan #✅ NOW COVERED
            urn = self.dist(N, n, M, odds, 1e-12)
            return urn.moments()

        m, v = (_moments1(M, n, N, odds) if ("m" in moments or "v" in moments)
                else (None, None))
        s, k = None, None
        return m, v, s, k


class nchypergeom_fisher_gen(_nchypergeom_gen):
    r"""A Fisher's noncentral hypergeometric discrete random variable.

    Fisher's noncentral hypergeometric distribution models drawing objects of
    two types from a bin. `M` is the total number of objects, `n` is the
    number of Type I objects, and `odds` is the odds ratio: the odds of
    selecting a Type I object rather than a Type II object when there is only
    one object of each type.
    The random variate represents the number of Type I objects drawn if we
    take a handful of objects from the bin at once and find out afterwards
    that we took `N` objects.

    %(before_notes)s

    See Also
    --------
    nchypergeom_wallenius, hypergeom, nhypergeom

    Notes
    -----
    Let mathematical symbols :math:`N`, :math:`n`, and :math:`M` correspond
    with parameters `N`, `n`, and `M` (respectively) as defined above.

    The probability mass function is defined as

    .. math::

        p(x; M, n, N, \omega) =
        \frac{\binom{n}{x}\binom{M - n}{N-x}\omega^x}{P_0},

    for
    :math:`x \in [x_l, x_u]`,
    :math:`M \in {\mathbb N}`,
    :math:`n \in [0, M]`,
    :math:`N \in [0, M]`,
    :math:`\omega > 0`,
    where
    :math:`x_l = \max(0, N - (M - n))`,
    :math:`x_u = \min(N, n)`,

    .. math::

--------------------------------------------------------------------------------
```
## Test Patch
```diff
diff --git a/scipy/stats/tests/test_continuous.py b/scipy/stats/tests/test_continuous.py
index 2be327145..eeaa96d2d 100644
--- a/scipy/stats/tests/test_continuous.py
+++ b/scipy/stats/tests/test_continuous.py
@@ -1441,6 +1441,18 @@ class TestMakeDistribution:
             assert repr(dist(beta=2)) == "HalfGeneralizedNormal(beta=np.float64(2.0))"
         assert 'HalfGeneralizedNormal' in dist.__doc__
 
+    def test_nchypergeom_fisher_with_nan(self):
+        # Create an instance of the distribution
+        dist = stats.nchypergeom_fisher
+        # Set parameters M, n, N to NaN and odds to a valid number
+        M = np.nan
+        n = np.nan
+        N = np.nan
+        odds = 1.0  # Use a valid odds value
+        # Check if the stats method handles NaN as expected
+        result = dist._stats(M, n, N, odds)
+        assert np.isnan(result[0]) and np.isnan(result[1]), 'Expected NaN values for moments'
+
 
 class TestTransforms:
 

```
## Fully Integrated Test
The new test is fully integrated into test file `scipy/stats/tests/test_continuous.py`.

To view the test file, navigate to `test.py`

To view the test file before new test is added on Github, click [here](https://github.com/mdhaber/scipy/blob/0c1945395d16945f7de749008f2c214f4440b97e/scipy/stats/tests/test_continuous.py)
## Test Runtime Log
```log
============================= test session starts ==============================
platform linux -- Python 3.11.12, pytest-8.3.5, pluggy-1.6.0
rootdir: /opt/scipy
configfile: pytest.ini
plugins: hypothesis-6.131.28, cov-6.1.1, timeout-2.4.0, xdist-3.7.0, anyio-4.9.0
collected 1 item

../opt/scipy/scipy/stats/tests/test_continuous.py .                      [100%]

================================ tests coverage ================================
_______________ coverage: platform linux, python 3.11.12-final-0 _______________

Coverage XML written to file coverage.xml
============================== 1 passed in 51.47s ==============================

```