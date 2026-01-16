## PR Title: Add test for _trim_zeros function in _polyutils.py

## PR Description: 
This PR introduces a new test for the `_trim_zeros` function in the `_polyutils.py` module, which was previously uncovered. The test checks the functionality for both leading and trailing zeros, ensuring the robustness of the implementation. This addition enhances the test coverage of the recent PR that upgraded several signal processing functions to support the Array API. The new test validates the correctness of behavior under different conditions, thus improving the reliability of the SciPy library.

## Lines Incremented by this Test
| File | Block | Permalink |
| ---- | ----- | --------- |
| scipy/signal/_polyutils.py | 58 | [Here](https://github.com/ev-br/scipy/blob/6103e55cf6192fe70896f53b02925dde78db393d/scipy/signal/_polyutils.py#L58) |
| scipy/signal/_polyutils.py | 61-63 | [Here](https://github.com/ev-br/scipy/blob/6103e55cf6192fe70896f53b02925dde78db393d/scipy/signal/_polyutils.py#L61-L63) |
| scipy/signal/_polyutils.py | 65 | [Here](https://github.com/ev-br/scipy/blob/6103e55cf6192fe70896f53b02925dde78db393d/scipy/signal/_polyutils.py#L65) |
## Lines Increment Visualization
```python
--------------------------------------------------------------------------------
# scipy/signal/_polyutils.py
--------------------------------------------------------------------------------
import scipy._lib.array_api_extra as xpx


def _sort_cmplx(arr, xp):
    # xp.sort is undefined for complex dtypes. Here we only need some
    # consistent way to sort a complex array, including equal magnitude elements.
    arr = xp.asarray(arr)
    if xp.isdtype(arr.dtype, 'complex floating'):
        sorter = abs(arr) + xp.real(arr) + xp.imag(arr)**3
    else:
        sorter = arr

    idxs = xp.argsort(sorter)
    return arr[idxs]


def polyroots(coef, *, xp):
    """numpy.roots, best-effor replacement
    """
    if coef.shape[0] < 2:
        return xp.asarray([], dtype=coef.dtype)

    root_func = getattr(xp, 'roots', None)
    if root_func:
        # NB: cupy.roots is broken in CuPy 13.x, but CuPy is handled via delegation
        # so we never hit this code path with xp being cupy
        return root_func(coef)

    # companion matrix
    n = coef.shape[0]
    a = xp.eye(n - 1, n - 1, k=-1, dtype=coef.dtype)
    a[:, -1] = -xp.flip(coef[1:]) / coef[0]

    # non-symmetric eigenvalue problem is not in the spec but is available on e.g. torch
    if hasattr(xp.linalg, 'eigvals'):
        return xp.linalg.eigvals(a)
    else:
        import numpy as np
        return xp.asarray(np.linalg.eigvals(np.asarray(a)))


# https://github.com/numpy/numpy/blob/v2.1.0/numpy/lib/_function_base_impl.py#L1874-L1925
def _trim_zeros(filt, trim='fb'):
    first = 0
    trim = trim.upper()
    if 'F' in trim:
        for i in filt:
            if i != 0.:
                break
            else:
                first = first + 1 #✅ NOW COVERED
    last = filt.shape[0]
    if 'B' in trim:
        for i in filt[::-1]: #✅ NOW COVERED
            if i != 0.: #✅ NOW COVERED
                break #✅ NOW COVERED
            else:
                last = last - 1 #✅ NOW COVERED
    return filt[first:last]


# ### Old-style routines ###


# https://github.com/numpy/numpy/blob/v2.2.0/numpy/lib/_polynomial_impl.py#L1232
def _poly1d(c_or_r, *, xp):
    """ Constructor of np.poly1d object from an array of coefficients (r=False)
    """
    c_or_r = xpx.atleast_nd(c_or_r, ndim=1, xp=xp)
    if c_or_r.ndim > 1:
        raise ValueError("Polynomial must be 1d only.")
    c_or_r = _trim_zeros(c_or_r, trim='f')
    if c_or_r.shape[0] == 0:
        c_or_r = xp.asarray([0], dtype=c_or_r.dtype)
    return c_or_r


# https://github.com/numpy/numpy/blob/v2.2.0/numpy/lib/_polynomial_impl.py#L702-L779
def polyval(p, x, *, xp):
    """ Old-style polynomial, `np.polyval`
    """
    y = xp.zeros_like(x)

    for pv in p:
        y = y * x + pv
    return y


# https://github.com/numpy/numpy/blob/v2.2.0/numpy/lib/_polynomial_impl.py#L34-L157
def poly(seq_of_zeros, *, xp):
    # Only reproduce the 1D variant of np.poly
    seq_of_zeros = xp.asarray(seq_of_zeros)
    seq_of_zeros = xpx.atleast_nd(seq_of_zeros, ndim=1, xp=xp)

    if seq_of_zeros.shape[0] == 0:
        return 1.0

    # prefer np.convolve etc, if available
    convolve_func = getattr(xp, 'convolve', None)
    if convolve_func is None:
        from scipy.signal import convolve as convolve_func

    dt = seq_of_zeros.dtype
    a = xp.ones((1,), dtype=dt)
    one = xp.ones_like(seq_of_zeros[0])
    for zero in seq_of_zeros:
        a = convolve_func(a, xp.stack((one, -zero)), mode='full')


--------------------------------------------------------------------------------
```
## Test Patch
```diff
diff --git a/scipy/signal/tests/test_filter_design.py b/scipy/signal/tests/test_filter_design.py
index c21c6816c..9663db1c2 100644
--- a/scipy/signal/tests/test_filter_design.py
+++ b/scipy/signal/tests/test_filter_design.py
@@ -31,6 +31,8 @@ from scipy.signal._filter_design import (_cplxreal, _cplxpair, _norm_factor,
 from scipy.signal._filter_design import _logspace
 from scipy.signal import _polyutils as _pu
 from scipy.signal._polyutils import _sort_cmplx
+from scipy.signal._polyutils import _trim_zeros
+from numpy.testing import assert_array_almost_equal
 
 skip_xp_backends = pytest.mark.skip_xp_backends
 xfail_xp_backends = pytest.mark.xfail_xp_backends
@@ -1662,6 +1664,23 @@ class TestBilinear:
         with pytest.raises(ValueError, match="Sampling.*be none"):
             bilinear(b, a, fs=None)
 
+    def test_trim_zeros(self):
+        # Test for leading zeros
+        b = [0, 0, 1, 2, 3, 0, 0]
+        a = [1, 0, 0]
+        expected_b = [1, 2, 3]
+        expected_a = [1]
+        b_trimmed = _trim_zeros(np.array(b), 'fb')  # Adjusted to unpack single value
+        assert_array_almost_equal(b_trimmed, expected_b)
+
+        # Test for trailing zeros
+        b = [1, 2, 3, 0, 0]
+        a = [1, 0, 0]
+        expected_b = [1, 2, 3]
+        expected_a = [1]
+        b_trimmed = _trim_zeros(np.array(b), 'fb')  # Adjusted to unpack single value
+        assert_array_almost_equal(b_trimmed, expected_b)
+
 
 class TestLp2lp_zpk:
 

```
## Fully Integrated Test
The new test is fully integrated into test file `scipy/signal/tests/test_filter_design.py`.

To view the test file, navigate to `test.py`

To view the test file before new test is added on Github, click [here](https://github.com/ev-br/scipy/blob/6103e55cf6192fe70896f53b02925dde78db393d/scipy/signal/tests/test_filter_design.py)
## Test Runtime Log
```log
============================= test session starts ==============================
platform linux -- Python 3.11.12, pytest-8.3.5, pluggy-1.6.0
rootdir: /opt/scipy
configfile: pytest.ini
plugins: hypothesis-6.131.28, cov-6.1.1, timeout-2.4.0, xdist-3.7.0, anyio-4.9.0
collected 1 item

../opt/scipy/scipy/signal/tests/test_filter_design.py .                  [100%]

================================ tests coverage ================================
_______________ coverage: platform linux, python 3.11.12-final-0 _______________

Coverage XML written to file coverage.xml
============================== 1 passed in 59.11s ==============================

```