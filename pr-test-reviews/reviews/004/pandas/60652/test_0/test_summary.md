## PR Title: Add test for TypeError on interpolating non-numeric string dtype

## PR Description: 
This pull request adds tests to improve coverage for the interpolation functionality in the DataFrame. It specifically tests that a TypeError is raised when attempting to interpolate DataFrames containing string dtypes. This addresses previously uncovered lines in the `interpolate` method of `NumpyExtensionArray`, ensuring better handling of inappropriate data types. The new tests confirm that the function behaves correctly for both string-only DataFrames and mixed-type DataFrames.

## Lines Incremented by this Test
| File | Block | Permalink |
| ---- | ----- | --------- |
| pandas/core/arrays/numpy_.py | 291 | [Here](https://github.com/jorisvandenbossche/pandas/blob/2e41b35e37aca3f466b396e1ad4eaefca3f33aad/pandas/core/arrays/numpy_.py#L291) |
## Lines Increment Visualization
```python
--------------------------------------------------------------------------------
# pandas/core/arrays/numpy_.py
--------------------------------------------------------------------------------

    # Base EA class (and all other EA classes) don't have limit_area keyword
    # This can be removed here as well when the interpolate ffill/bfill method
    # deprecation is enforced
    def _pad_or_backfill(
        self,
        *,
        method: FillnaOptions,
        limit: int | None = None,
        limit_area: Literal["inside", "outside"] | None = None,
        copy: bool = True,
    ) -> Self:
        """
        ffill or bfill along axis=0.
        """
        if copy:
            out_data = self._ndarray.copy()
        else:
            out_data = self._ndarray

        meth = missing.clean_fill_method(method)
        missing.pad_or_backfill_inplace(
            out_data.T,
            method=meth,
            axis=0,
            limit=limit,
            limit_area=limit_area,
        )

        if not copy:
            return self
        return type(self)._simple_new(out_data, dtype=self.dtype)

    def interpolate(
        self,
        *,
        method: InterpolateOptions,
        axis: int,
        index: Index,
        limit,
        limit_direction,
        limit_area,
        copy: bool,
        **kwargs,
    ) -> Self:
        """
        See NDFrame.interpolate.__doc__.
        """
        # NB: we return type(self) even if copy=False
        if not self.dtype._is_numeric:
            raise TypeError(f"Cannot interpolate with {self.dtype} dtype") #✅ NOW COVERED

        if not copy:
            out_data = self._ndarray
        else:
            out_data = self._ndarray.copy()

        # TODO: assert we have floating dtype?
        missing.interpolate_2d_inplace(
            out_data,
            method=method,
            axis=axis,
            index=index,
            limit=limit,
            limit_direction=limit_direction,
            limit_area=limit_area,
            **kwargs,
        )
        if not copy:
            return self
        return type(self)._simple_new(out_data, dtype=self.dtype)

    # ------------------------------------------------------------------------
    # Reductions

    def any(
        self,
        *,
        axis: AxisInt | None = None,
        out=None,
        keepdims: bool = False,
        skipna: bool = True,
    ):
        nv.validate_any((), {"out": out, "keepdims": keepdims})
        result = nanops.nanany(self._ndarray, axis=axis, skipna=skipna)
        return self._wrap_reduction_result(axis, result)

    def all(
        self,
        *,
        axis: AxisInt | None = None,
        out=None,
        keepdims: bool = False,
        skipna: bool = True,
    ):
        nv.validate_all((), {"out": out, "keepdims": keepdims})
        result = nanops.nanall(self._ndarray, axis=axis, skipna=skipna)
        return self._wrap_reduction_result(axis, result)

    def min(
        self, *, axis: AxisInt | None = None, skipna: bool = True, **kwargs

--------------------------------------------------------------------------------
```
## Test Patch
```diff
diff --git a/pandas/tests/frame/methods/test_interpolate.py b/pandas/tests/frame/methods/test_interpolate.py
index ebee19e3de..08e10cd485 100644
--- a/pandas/tests/frame/methods/test_interpolate.py
+++ b/pandas/tests/frame/methods/test_interpolate.py
@@ -13,6 +13,8 @@ from pandas import (
     date_range,
 )
 import pandas._testing as tm
+import pandas as pd
+import re
 
 
 class TestDataFrameInterpolate:
@@ -550,3 +552,15 @@ class TestDataFrameInterpolate:
         result = df.interpolate(limit=2)
         expected = DataFrame({"a": [1, 1.5, 2.0, None, 3]}, dtype="float64[pyarrow]")
         tm.assert_frame_equal(result, expected)
+
+    def test_interpolate_string_dtype(self):
+        df = pd.DataFrame({'A': ['a', 'b', 'c', 'd']})
+        with pytest.raises(TypeError):
+            df.interpolate()
+    def test_interpolate_non_numeric(self):
+        df = pd.DataFrame({'B': [1, 2, 3, 4], 'C': ['x', 'y', 'z', 'w']})
+        # Explicitly set dtype of column C to string
+        df['C'] = df['C'].astype('string')
+        msg = re.escape("Cannot interpolate with string dtype")
+        with pytest.raises(TypeError, match=msg):
+            df.interpolate()

```
## Fully Integrated Test
The new test is fully integrated into test file `pandas/tests/frame/methods/test_interpolate.py`.

To view the test file, navigate to `test.py`

To view the test file before new test is added on Github, click [here](https://github.com/jorisvandenbossche/pandas/blob/2e41b35e37aca3f466b396e1ad4eaefca3f33aad/pandas/tests/frame/methods/test_interpolate.py)
## Test Runtime Log
```log
+ /home/regularuser/.local/bin/ninja
[1/1] Generating write_version_file with a custom command
============================= test session starts ==============================
platform linux -- Python 3.11.12, pytest-8.3.5, pluggy-1.5.0
PyQt5 5.15.11 -- Qt runtime 5.15.16 -- Qt compiled 5.15.14
rootdir: /opt/pandas
configfile: pyproject.toml
plugins: anyio-4.9.0, hypothesis-6.131.9, cov-6.1.1, cython-0.3.1, qt-4.4.0, xdist-3.6.1
collected 2 items

../opt/pandas/pandas/tests/frame/methods/test_interpolate.py ..

----------------- generated xml file: /workspace/test-data.xml -----------------
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.11.12-final-0 _______________

Coverage XML written to file coverage.xml
============================= slowest 30 durations =============================
0.01s call     pandas/tests/frame/methods/test_interpolate.py::TestDataFrameInterpolate::test_interpolate_non_numeric

(5 durations < 0.005s hidden.  Use -vv to show these durations.)
============================== 2 passed in 54.06s ==============================

```