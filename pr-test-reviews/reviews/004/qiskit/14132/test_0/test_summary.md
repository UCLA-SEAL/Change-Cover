## PR Title: Add test for `coerce_observable` method to handle invalid types

## PR Description:
This pull request introduces a new test case for the `coerce_observable` method in the `ObservablesArray` class, specifically targeting the handling of invalid input types. The test ensures that appropriate exceptions are raised when invalid types are provided, improving the robustness of the code. This addition enhances the coverage of the original PR (#14132) by addressing previously uncovered lines, thereby contributing to better overall test reliability and code quality.

## Lines Incremented by this Test
| File | Block | Permalink |
| ---- | ----- | --------- |
| qiskit/primitives/containers/observables_array.py | 214 | [Here](https://github.com/yaelbh/qiskit/blob/8f7477ef84a0251bae1e9d8cba69ad7d4f09e96b/qiskit/primitives/containers/observables_array.py#L214) |
## Lines Increment Visualization
```python
--------------------------------------------------------------------------------
# qiskit/primitives/containers/observables_array.py
--------------------------------------------------------------------------------
        """
        Args:
            shape: The shape of the returned array.

        Returns:
            A new array.
        """
        shape = shape_tuple(*shape)
        return ObservablesArray(self._array.reshape(shape), copy=False, validate=False)

    def ravel(self) -> ObservablesArray:
        """Return a new array with one dimension.

        The returned array has a :attr:`shape` given by ``(size, )``, where
        the size is the :attr:`~size` of this array.

        Returns:
            A new flattened array.
        """
        return self.reshape(self.size)

    @classmethod
    def coerce_observable(cls, observable: ObservableLike) -> SparseObservable:
        """Format an observable-like object into the internal format.

        Args:
            observable: The observable-like to format.

        Returns:
            The coerced observable.

        Raises:
            TypeError: If the input cannot be formatted because its type is not valid.
            ValueError: If the input observable is invalid.
        """
        # Pauli-type conversions
        if isinstance(observable, SparsePauliOp):
            observable = SparseObservable.from_sparse_pauli_op(observable)
        elif isinstance(observable, Pauli):
            observable = SparseObservable.from_pauli(observable)
        elif isinstance(observable, str):
            observable = SparseObservable.from_label(observable)
        elif isinstance(observable, _Mapping):
            term_list = []
            for basis, coeff in observable.items():
                if isinstance(basis, str):
                    term_list.append((basis, coeff))
                elif isinstance(basis, Pauli):
                    unphased_basis, phase = basis[:].to_label(), basis.phase
                    term_list.append((unphased_basis, complex(0, 1) ** phase * coeff))
                else:
                    raise TypeError(f"Invalid observable basis type: {type(basis)}") #✅ NOW COVERED
            observable = SparseObservable.from_list(term_list)

        if isinstance(observable, SparseObservable):
            # Check that the operator has real coeffs
            coeffs = np.real_if_close(observable.coeffs)
            if np.iscomplexobj(coeffs):
                raise ValueError(
                    "Non-Hermitian input observable: the input SparsePauliOp has non-zero"
                    " imaginary part in its coefficients."
                )

            return SparseObservable.from_raw_parts(
                observable.num_qubits,
                coeffs,
                observable.bit_terms,
                observable.indices,
                observable.boundaries,
            ).simplify(tol=0)

        raise TypeError(f"Invalid observable type: {type(observable)}")

    @classmethod
    def coerce(cls, observables: ObservablesArrayLike) -> ObservablesArray:
        """Coerce ObservablesArrayLike into ObservableArray.

        Args:
            observables: an object to be observables array.

        Returns:
            A coerced observables array.
        """
        if isinstance(observables, ObservablesArray):
            return observables
        return cls(observables)

    def validate(self):
        """Validate the consistency in observables array."""
        num_qubits = None
        for obs in self._array.reshape(-1):
            if num_qubits is None:
                num_qubits = obs.num_qubits
            elif obs.num_qubits != num_qubits:
                raise ValueError(
                    "The number of qubits must be the same for all observables in the "
                    "observables array."
                )


@lru_cache(1)
def _regex_match(allowed_chars: str) -> re.Pattern:

--------------------------------------------------------------------------------
```
## Test Patch
```diff
diff --git a/test/python/primitives/containers/test_observables_array.py b/test/python/primitives/containers/test_observables_array.py
index be215f28a..4aad38077 100644
--- a/test/python/primitives/containers/test_observables_array.py
+++ b/test/python/primitives/containers/test_observables_array.py
@@ -19,6 +19,7 @@ import numpy as np
 import qiskit.quantum_info as qi
 from qiskit.primitives.containers.observables_array import ObservablesArray
 from test import QiskitTestCase  # pylint: disable=wrong-import-order
+import pytest


 @ddt.ddt
@@ -355,3 +356,11 @@ class ObservablesArrayTestCase(QiskitTestCase):
                             {labels_rs[idx]: 1},
                             msg=f"failed for shape {shape} with input format {input_shape}",
                         )
+
+class TestObservablesArray:
+
+    @pytest.mark.parametrize('invalid_input', [123, 45.67, None, [], {}, {'a': 1, 2: 3}])
+    def test_coerce_observable_invalid_type(self, invalid_input):
+        """Test coerce_observable for invalid basis types"""
+        with pytest.raises((TypeError, ValueError)):
+            ObservablesArray.coerce_observable(invalid_input)

```
## Fully Integrated Test
The new test is fully integrated into test file `test/python/primitives/containers/test_observables_array.py`.

To view the test file, navigate to `test.py`

To view the test file before new test is added on Github, click [here](https://github.com/yaelbh/qiskit/blob/8f7477ef84a0251bae1e9d8cba69ad7d4f09e96b/test/python/primitives/containers/test_observables_array.py)
## Test Runtime Log
```log
============================= test session starts ==============================
platform linux -- Python 3.11.13, pytest-8.4.1, pluggy-1.6.0
rootdir: /opt/qiskit
configfile: pyproject.toml
plugins: cov-6.2.1, hypothesis-6.135.29
collected 6 items

../opt/qiskit/test/python/primitives/containers/test_observables_array.py . [ 16%]
.....                                                                    [100%]

================================ tests coverage ================================
_______________ coverage: platform linux, python 3.11.13-final-0 _______________

Coverage XML written to file coverage.xml
============================== 6 passed in 34.99s ==============================

```