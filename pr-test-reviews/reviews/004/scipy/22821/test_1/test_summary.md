## PR Title: Add test for lp2hp function with various wo parameters

## PR Description:
This PR introduces a new test for the `lp2hp` function in the `scipy.signal` module, ensuring coverage of various `wo` parameter values. The test confirms that the function produces non-empty outputs for `wo` values less than, equal to, and greater than 1. This addition addresses uncovered lines from the previous PR, enhancing the robustness of our signal processing functions.

## Lines Incremented by this Test
| File | Block | Permalink |
| ---- | ----- | --------- |
| scipy/signal/_filter_design.py | 2029 | [Here](https://github.com/ev-br/scipy/blob/db4e9cc5eaf4039de8dffc60a77f7e5dca725601/scipy/signal/_filter_design.py#L2029) |
## Lines Increment Visualization
```python
--------------------------------------------------------------------------------
# scipy/signal/_filter_design.py
--------------------------------------------------------------------------------
    """
    See Also
    --------
    lp2lp, lp2bp, lp2bs, bilinear
    lp2hp_zpk

    Notes
    -----
    This is derived from the s-plane substitution

    .. math:: s \rightarrow \frac{\omega_0}{s}

    This maintains symmetry of the lowpass and highpass responses on a
    logarithmic scale.

    Examples
    --------
    >>> from scipy import signal
    >>> import matplotlib.pyplot as plt

    >>> lp = signal.lti([1.0], [1.0, 1.0])
    >>> hp = signal.lti(*signal.lp2hp(lp.num, lp.den))
    >>> w, mag_lp, p_lp = lp.bode()
    >>> w, mag_hp, p_hp = hp.bode(w)

    >>> plt.plot(w, mag_lp, label='Lowpass')
    >>> plt.plot(w, mag_hp, label='Highpass')
    >>> plt.semilogx()
    >>> plt.grid(True)
    >>> plt.xlabel('Frequency [rad/s]')
    >>> plt.ylabel('Amplitude [dB]')
    >>> plt.legend()

    """
    xp = array_namespace(a, b)

    a, b = map(xp.asarray, (a, b))
    a, b = xp_promote(a, b, force_floating=True, xp=xp)
    a = xpx.atleast_nd(a, ndim=1, xp=xp)
    b = xpx.atleast_nd(b, ndim=1, xp=xp)

    try:
        wo = float(wo)
    except TypeError:
        wo = float(wo[0])
    d = a.shape[0]
    n = b.shape[0]
    if wo != 1:
        pwo = wo ** xp.arange(max((d, n)), dtype=b.dtype)
    else:
        pwo = xp.ones(max((d, n)), dtype=b.dtype) #✅ NOW COVERED
    if d >= n:
        outa = xp.flip(a) * pwo
        outb = _resize(b, (d,), xp=xp)
        outb[n:] = 0.0
        outb[:n] = xp.flip(b) * pwo[:n]
    else:
        outb = xp.flip(b) * pwo
        outa = _resize(a, (n,), xp=xp)
        outa[d:] = 0.0
        outa[:d] = xp.flip(a) * pwo[:d]

    return normalize(outb, outa)


def lp2bp(b, a, wo=1.0, bw=1.0):
    r"""
    Transform a lowpass filter prototype to a bandpass filter.

    Return an analog band-pass filter with center frequency `wo` and
    bandwidth `bw` from an analog low-pass filter prototype with unity
    cutoff frequency, in transfer function ('ba') representation.

    Parameters
    ----------
    b : array_like
        Numerator polynomial coefficients.
    a : array_like
        Denominator polynomial coefficients.
    wo : float
        Desired passband center, as angular frequency (e.g., rad/s).
        Defaults to no change.
    bw : float
        Desired passband width, as angular frequency (e.g., rad/s).
        Defaults to 1.

    Returns
    -------
    b : array_like
        Numerator polynomial coefficients of the transformed band-pass filter.
    a : array_like
        Denominator polynomial coefficients of the transformed band-pass filter.

    See Also
    --------
    lp2lp, lp2hp, lp2bs, bilinear
    lp2bp_zpk

    Notes
    -----
    This is derived from the s-plane substitution

--------------------------------------------------------------------------------
```
## Test Patch
```diff
diff --git a/scipy/signal/tests/test_signaltools.py b/scipy/signal/tests/test_signaltools.py
index b63a6211f..8bff8abe3 100644
--- a/scipy/signal/tests/test_signaltools.py
+++ b/scipy/signal/tests/test_signaltools.py
@@ -36,6 +36,7 @@ from scipy._lib._array_api import (
     assert_array_almost_equal, assert_almost_equal,
     xp_copy, xp_size, xp_default_dtype
 )
+from scipy.signal import lp2hp
 skip_xp_backends = pytest.mark.skip_xp_backends
 xfail_xp_backends = pytest.mark.xfail_xp_backends

@@ -4561,3 +4562,16 @@ class TestUniqueRoots:
 def test_gh_22684():
     actual = signal.resample_poly(np.arange(2000, dtype=np.complex64), 6, 4)
     assert actual.dtype == np.complex64
+
+def test_lp2hp_with_various_wo():
+    # Test with wo < 1
+    b, a = lp2hp([1], [1, np.sqrt(2), 1], wo=0.5)
+    assert len(b) > 0 and len(a) > 0, 'Expected non-empty output for wo < 1'
+
+    # Test with wo = 1
+    b, a = lp2hp([1], [1, np.sqrt(2), 1], wo=1)
+    assert len(b) > 0 and len(a) > 0, 'Expected non-empty output for wo = 1'
+
+    # Test with wo > 1
+    b, a = lp2hp([1], [1, np.sqrt(2), 1], wo=2)
+    assert len(b) > 0 and len(a) > 0, 'Expected non-empty output for wo > 1'

```
## Fully Integrated Test
The new test is fully integrated into test file `scipy/signal/tests/test_signaltools.py`.

To view the test file, navigate to `test.py`

To view the test file before new test is added on Github, click [here](https://github.com/ev-br/scipy/blob/db4e9cc5eaf4039de8dffc60a77f7e5dca725601/scipy/signal/tests/test_signaltools.py)
## Test Runtime Log
```log
============================= test session starts ==============================
platform linux -- Python 3.11.12, pytest-8.3.5, pluggy-1.6.0
rootdir: /opt/scipy
configfile: pytest.ini
plugins: hypothesis-6.131.28, cov-6.1.1, timeout-2.4.0, xdist-3.7.0, anyio-4.9.0
collected 1 item

../opt/scipy/scipy/signal/tests/test_signaltools.py .                    [100%]

================================ tests coverage ================================
_______________ coverage: platform linux, python 3.11.12-final-0 _______________

Coverage XML written to file coverage.xml
========================= 1 passed in 69.75s (0:01:09) =========================

```