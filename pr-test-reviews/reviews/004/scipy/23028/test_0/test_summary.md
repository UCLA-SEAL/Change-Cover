## PR Title: Add tests for unsupported array types in array_namespace function

## PR Description: 
This PR adds a new test to improve coverage for the `array_namespace` function in `_lib._array_api_override`. The test validates that the function correctly raises exceptions for unsupported array types, including sparse and masked arrays, as well as unsupported dtypes. These tests cover previously uncovered lines, ensuring better robustness and adherence to the expected behavior.

## Lines Incremented by this Test
| File | Block | Permalink |
| ---- | ----- | --------- |
| scipy/_lib/_array_api_override.py | 48-51 | [Here](https://github.com/lucascolley/scipy/blob/7d73afb66b46971d0dc8d1cb8397eafa929ea2a3/scipy/_lib/_array_api_override.py#L48-L51) |
## Lines Increment Visualization
```python
--------------------------------------------------------------------------------
# scipy/_lib/_array_api_override.py
--------------------------------------------------------------------------------
"""
Override functions from array_api_compat, for use by array-api-extra
and internally.

See also _array_api_compat_vendor.py
"""
import os

from collections.abc import Iterable, Iterator
from types import ModuleType
from typing import Any, TypeAlias

import numpy as np
import numpy.typing as npt

from scipy._lib import array_api_compat
import scipy._lib.array_api_compat.numpy as np_compat
from scipy._lib.array_api_compat import is_array_api_obj
from scipy._lib._sparse import issparse


Array: TypeAlias = Any  # To be changed to a Protocol later (see array-api#589)
ArrayLike: TypeAlias = Array | npt.ArrayLike

# To enable array API and strict array-like input validation
SCIPY_ARRAY_API: str | bool = os.environ.get("SCIPY_ARRAY_API", False)
# To control the default device - for use in the test suite only
SCIPY_DEVICE = os.environ.get("SCIPY_DEVICE", "cpu")


def _compliance_scipy(arrays: Iterable[ArrayLike]) -> Iterator[Array]:
    """Raise exceptions on known-bad subclasses. Discard 0-dimensional ArrayLikes
    and convert 1+-dimensional ArrayLikes to numpy.

    The following subclasses are not supported and raise and error:
    - `numpy.ma.MaskedArray`
    - `numpy.matrix`
    - NumPy arrays which do not have a boolean or numerical dtype
    - Any array-like which is neither array API compatible nor coercible by NumPy
    - Any array-like which is coerced by NumPy to an unsupported dtype
    """
    for array in arrays:
        if array is None:
            continue

        # this comes from `_util._asarray_validated`
        if issparse(array):
            msg = ('Sparse arrays/matrices are not supported by this function. ' #✅ NOW COVERED
                   'Perhaps one of the `scipy.sparse.linalg` functions ' #✅ NOW COVERED
                   'would work instead.') #✅ NOW COVERED
            raise ValueError(msg) #✅ NOW COVERED

        if isinstance(array, np.ma.MaskedArray):
            raise TypeError("Inputs of type `numpy.ma.MaskedArray` are not supported.")

        if isinstance(array, np.matrix):
            raise TypeError("Inputs of type `numpy.matrix` are not supported.")

        if isinstance(array, np.ndarray | np.generic):
            dtype = array.dtype
            if not (np.issubdtype(dtype, np.number) or np.issubdtype(dtype, np.bool_)):
                raise TypeError(f"An argument has dtype `{dtype!r}`; "
                                f"only boolean and numerical dtypes are supported.")

        if is_array_api_obj(array):
            yield array
        else:
            try:
                array = np.asanyarray(array)
            except TypeError:
                raise TypeError("An argument is neither array API compatible nor "
                                "coercible by NumPy.")
            dtype = array.dtype
            if not (np.issubdtype(dtype, np.number) or np.issubdtype(dtype, np.bool_)):
                message = (
                    f"An argument was coerced to an unsupported dtype `{dtype!r}`; "
                    f"only boolean and numerical dtypes are supported."
                )
                raise TypeError(message)
            # Ignore 0-dimensional arrays, coherently with array-api-compat.
            # Raise if there are 1+-dimensional array-likes mixed with non-numpy
            # Array API objects.
            if array.ndim:
                yield array


def array_namespace(*arrays: Array) -> ModuleType:
    """Get the array API compatible namespace for the arrays xs.

    Parameters
    ----------
    *arrays : sequence of array_like
        Arrays used to infer the common namespace.

    Returns
    -------
    namespace : module
        Common namespace.

    Notes
    -----

--------------------------------------------------------------------------------
```
## Test Patch
```diff
diff --git a/scipy/_lib/tests/test_array_api.py b/scipy/_lib/tests/test_array_api.py
index 1a633a968..f9f3c122e 100644
--- a/scipy/_lib/tests/test_array_api.py
+++ b/scipy/_lib/tests/test_array_api.py
@@ -10,6 +10,8 @@ from scipy._lib._array_api import (
 from scipy._lib import array_api_extra as xpx
 from scipy._lib._array_api_no_0d import xp_assert_equal as xp_assert_equal_no_0d
 from scipy._lib.array_api_extra.testing import lazy_xp_function
+from scipy._lib._array_api import array_namespace, SCIPY_ARRAY_API
+from scipy.sparse import csr_matrix
 
 
 lazy_xp_function(_asarray)
@@ -223,6 +225,20 @@ class TestArrayAPI:
     def test_default_dtype(self, xp):
         assert xp_default_dtype(xp) == xp.asarray(1.).dtype
 
+    @pytest.mark.skipif(not SCIPY_ARRAY_API, reason='Array API test; set environment variable SCIPY_ARRAY_API=1 to run it')
+    def test_sparse_and_unsupported_types(self):
+        # Testing with a sparse array
+        sparse_array = csr_matrix([1, 2, 3])
+        with pytest.raises(ValueError, match='Sparse arrays/matrices are not supported by this function'):
+            array_namespace(sparse_array, np.array(1))
+        # Testing with a masked array
+        masked_array = np.ma.array([1, 2, 3])
+        with pytest.raises(TypeError, match='of type `numpy.ma.MaskedArray` are not supported'):
+            array_namespace(masked_array, np.array(1))
+        # Testing with unsupported types
+        with pytest.raises(TypeError, match='only boolean and numerical dtypes are supported'):
+            array_namespace({'key': 'value'}, np.array(1))
+
 
 scalars = [1, 1., 1. + 1j]
 lists = [[1], [1.], [1. + 1j]]

```
## Fully Integrated Test
The new test is fully integrated into test file `scipy/_lib/tests/test_array_api.py`.

To view the test file, navigate to `test.py`

To view the test file before new test is added on Github, click [here](https://github.com/lucascolley/scipy/blob/7d73afb66b46971d0dc8d1cb8397eafa929ea2a3/scipy/_lib/tests/test_array_api.py)
## Test Runtime Log
```log
============================= test session starts ==============================
platform linux -- Python 3.11.12, pytest-8.3.5, pluggy-1.6.0
rootdir: /opt/scipy
configfile: pytest.ini
plugins: hypothesis-6.131.28, cov-6.1.1, timeout-2.4.0, xdist-3.7.0, anyio-4.9.0
collected 1 item

../opt/scipy/scipy/_lib/tests/test_array_api.py .                        [100%]

================================ tests coverage ================================
_______________ coverage: platform linux, python 3.11.12-final-0 _______________

Coverage XML written to file coverage.xml
============================== 1 passed in 52.72s ==============================

```