## PR Title: Add unit test for _FuncInfo equality in scipy.special

## PR Description: 
This PR introduces a new unit test for the `_FuncInfo` class in `scipy.special`. The test validates the equality and inequality of two `_FuncInfo` instances, ensuring the correctness of the equality operator. This addition covers previously uncovered lines from the original PR #22946, enhancing overall test coverage for the `xp_capabilities` feature.

## Lines Incremented by this Test
| File | Block | Permalink |
| ---- | ----- | --------- |
| scipy/special/_support_alternative_backends.py | 44 | [Here](https://github.com/crusaderky/scipy/blob/709510297dbb49d4e86aff55b1834f5150f69d00/scipy/special/_support_alternative_backends.py#L44) |
## Lines Increment Visualization
```python
--------------------------------------------------------------------------------
# scipy/special/_support_alternative_backends.py
--------------------------------------------------------------------------------
import functools
import operator
from collections.abc import Callable
from dataclasses import dataclass
from types import ModuleType

import numpy as np
from scipy._lib._array_api import (
    array_namespace, scipy_namespace_for, is_numpy, is_dask, is_marray,
    xp_promote, xp_capabilities, SCIPY_ARRAY_API
)
import scipy._lib.array_api_extra as xpx
from . import _ufuncs


@dataclass
class _FuncInfo:
    # NumPy-only function. IT MUST BE ELEMENTWISE.
    func: Callable
    # Number of arguments, not counting out=
    # This is for testing purposes only, due to the fact that
    # inspect.signature() just returns *args for ufuncs.
    n_args: int
    # @xp_capabilities decorator, for the purpose of
    # documentation and unit testing. Omit to indicate
    # full support for all backends.
    xp_capabilities: Callable[[Callable], Callable] | None = None
    # Generic implementation to fall back on if there is no native dispatch
    # available. This is a function that accepts (main namespace, scipy namespace)
    # and returns the final callable, or None if not available.
    generic_impl: Callable[
        [ModuleType, ModuleType | None], Callable | None
    ] | None = None

    @property
    def name(self):
        return self.func.__name__

    # These are needed by @lru_cache below
    def __hash__(self):
        return hash(self.func)

    def __eq__(self, other):
        return isinstance(other, _FuncInfo) and self.func == other.func #✅ NOW COVERED

    @property
    def wrapper(self):
        if self.name in globals():
            # Already initialised. We are likely in a unit test.
            # Return function potentially overridden by xpx.testing.lazy_xp_function.
            import scipy.special
            return getattr(scipy.special, self.name)

        if SCIPY_ARRAY_API:
            @functools.wraps(self.func)
            def wrapped(*args, **kwargs):
                xp = array_namespace(*args)
                return self._wrapper_for(xp)(*args, **kwargs)

            # Allow pickling the function. Normally this is done by @wraps,
            # but in this case it doesn't work because self.func is a ufunc.
            wrapped.__module__ = "scipy.special"
            wrapped.__qualname__ = self.name
            func = wrapped
        else:
            func = self.func

        capabilities = self.xp_capabilities or xp_capabilities()
        # In order to retain a naked ufunc when SCIPY_ARRAY_API is
        # disabled, xp_capabilities must apply its changes in place.
        cap_func = capabilities(func)
        assert cap_func is func
        return func

    @functools.lru_cache(1000)
    def _wrapper_for(self, xp):
        if is_numpy(xp):
            return self.func

        # If a native implementation is available, use that
        spx = scipy_namespace_for(xp)
        f = _get_native_func(xp, spx, self.name)
        if f is not None:
            return f

        # If generic Array API implementation is available, use that
        if self.generic_impl is not None:
            f = self.generic_impl(xp, spx)
            if f is not None:
                return f

        if is_marray(xp):
            # Unwrap the array, apply the function on the wrapped namespace,
            # and then re-wrap it.

--------------------------------------------------------------------------------
```
## Test Patch
```diff
diff --git a/scipy/special/tests/test_support_alternative_backends.py b/scipy/special/tests/test_support_alternative_backends.py
index e98939fef..4bee2d8b6 100644
--- a/scipy/special/tests/test_support_alternative_backends.py
+++ b/scipy/special/tests/test_support_alternative_backends.py
@@ -13,6 +13,8 @@ from scipy._lib._array_api import (is_cupy, is_dask, is_jax, is_torch,
                                    make_xp_pytest_param, make_xp_test_case,
                                    xp_default_dtype)
 from scipy._lib.array_api_compat import numpy as np
+import unittest
+from scipy.special._support_alternative_backends import _FuncInfo
 
 # Run all tests in this module in the Array API CI, including those without
 # the xp fixture
@@ -246,3 +248,14 @@ def test_chdtr_gh21311(xp):
     ref = special.chdtr(v, x)
     res = special.chdtr(xp.asarray(v), xp.asarray(x))
     xp_assert_close(res, xp.asarray(ref))
+
+class TestFuncInfo(unittest.TestCase):
+    def test_funcinfo_equality(self):
+        func_info1 = _FuncInfo('func1', 1, None)
+        func_info2 = _FuncInfo('func1', 1, None)
+        func_info3 = _FuncInfo('func2', 2, None)
+        
+        # Check equality of two identical FuncInfo instances
+        self.assertEqual(func_info1, func_info2)
+        # Check inequality of two different FuncInfo instances
+        self.assertNotEqual(func_info1, func_info3)

```
## Fully Integrated Test
The new test is fully integrated into test file `scipy/special/tests/test_support_alternative_backends.py`.

To view the test file, navigate to `test.py`

To view the test file before new test is added on Github, click [here](https://github.com/crusaderky/scipy/blob/709510297dbb49d4e86aff55b1834f5150f69d00/scipy/special/tests/test_support_alternative_backends.py)
## Test Runtime Log
```log
============================= test session starts ==============================
platform linux -- Python 3.11.12, pytest-8.3.5, pluggy-1.6.0
rootdir: /opt/scipy
configfile: pytest.ini
plugins: hypothesis-6.131.28, cov-6.1.1, timeout-2.4.0, xdist-3.7.0, anyio-4.9.0
collected 1 item

../opt/scipy/scipy/special/tests/test_support_alternative_backends.py .  [100%]

================================ tests coverage ================================
_______________ coverage: platform linux, python 3.11.12-final-0 _______________

Coverage XML written to file coverage.xml
============================== 1 passed in 51.63s ==============================

```