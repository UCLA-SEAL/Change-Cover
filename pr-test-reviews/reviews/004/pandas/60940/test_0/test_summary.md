## PR Title: Add test for 'dtype' argument in str.decode method

## PR Description:
This pull request adds a new test to enhance coverage for the 'dtype' argument in the 'str.decode' method. The test ensures that when 'dtype' is set to None and the 'future.infer_string' option is enabled, the method correctly infers the string data type. This addresses previously uncovered lines in the original PR, improving the robustness of the string handling functionality in pandas.

## Lines Incremented by this Test
| File | Block | Permalink |
| ---- | ----- | --------- |
| pandas/core/strings/accessor.py | 2152 | [Here](https://github.com/rhshadrach/pandas/blob/91d6be373598e2c9dde1ed548ad7e35ffdbbec55/pandas/core/strings/accessor.py#L2152) |
## Lines Increment Visualization
```python
--------------------------------------------------------------------------------
# pandas/core/strings/accessor.py
--------------------------------------------------------------------------------
        result = self._data.array._str_slice_replace(start, stop, repl)
        return self._wrap_result(result)

    def decode(
        self, encoding, errors: str = "strict", dtype: str | DtypeObj | None = None
    ):
        """
        Decode character string in the Series/Index using indicated encoding.

        Equivalent to :meth:`str.decode` in python2 and :meth:`bytes.decode` in
        python3.

        Parameters
        ----------
        encoding : str
            Specifies the encoding to be used.
        errors : str, optional
            Specifies the error handling scheme.
            Possible values are those supported by :meth:`bytes.decode`.
        dtype : str or dtype, optional
            The dtype of the result. When not ``None``, must be either a string or
            object dtype. When ``None``, the dtype of the result is determined by
            ``pd.options.future.infer_string``.

            .. versionadded:: 2.3.0

        Returns
        -------
        Series or Index
            A Series or Index with decoded strings.

        See Also
        --------
        Series.str.encode : Encodes strings into bytes in a Series/Index.

        Examples
        --------
        For Series:

        >>> ser = pd.Series([b"cow", b"123", b"()"])
        >>> ser.str.decode("ascii")
        0   cow
        1   123
        2   ()
        dtype: object
        """
        if dtype is not None and not is_string_dtype(dtype):
            raise ValueError(f"dtype must be string or object, got {dtype=}")
        if dtype is None and get_option("future.infer_string"):
            dtype = "str" #✅ NOW COVERED
        # TODO: Add a similar _bytes interface.
        if encoding in _cpython_optimized_decoders:
            # CPython optimized implementation
            f = lambda x: x.decode(encoding, errors)
        else:
            decoder = codecs.getdecoder(encoding)
            f = lambda x: decoder(x, errors)[0]
        arr = self._data.array
        result = arr._str_map(f)
        return self._wrap_result(result, dtype=dtype)

    @forbid_nonstring_types(["bytes"])
    def encode(self, encoding, errors: str = "strict"):
        """
        Encode character string in the Series/Index using indicated encoding.

        Equivalent to :meth:`str.encode`.

        Parameters
        ----------
        encoding : str
            Specifies the encoding to be used.
        errors : str, optional
            Specifies the error handling scheme.
            Possible values are those supported by :meth:`str.encode`.

        Returns
        -------
        Series/Index of objects
            A Series or Index with strings encoded into bytes.

        See Also
        --------
        Series.str.decode : Decodes bytes into strings in a Series/Index.

        Examples
        --------
        >>> ser = pd.Series(["cow", "123", "()"])
        >>> ser.str.encode(encoding="ascii")
        0     b'cow'
        1     b'123'
        2      b'()'
        dtype: object
        """
        result = self._data.array._str_encode(encoding, errors)
        return self._wrap_result(result, returns_string=False)

    _shared_docs["str_strip"] = r"""
    Remove %(position)s characters.


--------------------------------------------------------------------------------
```
## Test Patch
```diff
diff --git a/pandas/tests/strings/test_strings.py b/pandas/tests/strings/test_strings.py
index 025f837982..199a039bee 100644
--- a/pandas/tests/strings/test_strings.py
+++ b/pandas/tests/strings/test_strings.py
@@ -15,6 +15,7 @@ from pandas import (
 import pandas._testing as tm
 from pandas.core.strings.accessor import StringMethods
 from pandas.tests.strings import is_object_or_nan_string_dtype
+from pandas import Series, set_option


 @pytest.mark.parametrize("pattern", [0, True, Series(["foo", "bar"])])
@@ -778,3 +779,11 @@ def test_series_str_decode():
     result = Series([b"x", b"y"]).str.decode(encoding="UTF-8", errors="strict")
     expected = Series(["x", "y"], dtype="str")
     tm.assert_series_equal(result, expected)
+
+def test_decode_with_dtype_none():
+    # Ensure that future.infer_string is enabled
+    set_option('future.infer_string', True)
+    ser = Series([b'a', b'b', b'c'])  # Use byte strings
+    result = ser.str.decode('utf-8', dtype=None)
+    expected = Series(['a', 'b', 'c'], dtype='str')
+    tm.assert_series_equal(result, expected)

```
## Fully Integrated Test
The new test is fully integrated into test file `pandas/tests/strings/test_strings.py`.

To view the test file, navigate to `test.py`

To view the test file before new test is added on Github, click [here](https://github.com/rhshadrach/pandas/blob/91d6be373598e2c9dde1ed548ad7e35ffdbbec55/pandas/tests/strings/test_strings.py)
## Test Runtime Log
```log
+ /home/regularuser/.local/bin/ninja
[1/1] Generating write_version_file with a custom command
============================= test session starts ==============================
platform linux -- Python 3.11.12, pytest-8.3.5, pluggy-1.5.0
PyQt5 5.15.11 -- Qt runtime 5.15.16 -- Qt compiled 5.15.14
rootdir: /opt/pandas
configfile: pyproject.toml
plugins: anyio-4.9.0, hypothesis-6.131.9, cov-6.1.1, cython-0.3.1, localserver-0.9.0.post0, qt-4.4.0, xdist-3.6.1
collected 1 item

../opt/pandas/pandas/tests/strings/test_strings.py .

----------------- generated xml file: /workspace/test-data.xml -----------------
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.11.12-final-0 _______________

Coverage XML written to file coverage.xml
============================= slowest 30 durations =============================

(3 durations < 0.005s hidden.  Use -vv to show these durations.)
============================== 1 passed in 54.35s ==============================

```