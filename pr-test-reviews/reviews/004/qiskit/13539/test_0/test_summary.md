## PR Title: Add test for invalid input handling in StabilizerState.expectation_value

## PR Description: 
This pull request introduces a new test case for the `StabilizerState.expectation_value` method to enhance error handling coverage. The test checks that the method raises a `QiskitError` when provided with invalid input types. This addition addresses previously uncovered lines in the original PR (#13539), ensuring robustness in the method's functionality. The new test improves overall test coverage and contributes to maintaining high code quality in the Qiskit library.

## Lines Incremented by this Test
| File | Block | Permalink |
| ---- | ----- | --------- |
| qiskit/quantum_info/states/stabilizerstate.py | 284-287 | [Here](https://github.com/ShellyGarion/qiskit-terra/blob/03d1d90588060c82a8e391d9e2a6f96eb5b97f83/qiskit/quantum_info/states/stabilizerstate.py#L284-L287) |
## Lines Increment Visualization
```python
--------------------------------------------------------------------------------
# qiskit/quantum_info/states/stabilizerstate.py
--------------------------------------------------------------------------------
        ret = self.copy()
        ret._data = self.clifford.expand(other.clifford)
        return ret

    def evolve(
        self, other: Clifford | QuantumCircuit | Instruction, qargs: list | None = None
    ) -> StabilizerState:
        """Evolve a stabilizer state by a Clifford operator.

        Args:
            other (Clifford or QuantumCircuit or qiskit.circuit.Instruction):
                The Clifford operator to evolve by.
            qargs (list): a list of stabilizer subsystem positions to apply the operator on.

        Returns:
            StabilizerState: the output stabilizer state.

        Raises:
            QiskitError: if other is not a StabilizerState.
            QiskitError: if the operator dimension does not match the
                         specified StabilizerState subsystem dimensions.
        """
        if not isinstance(other, StabilizerState):
            other = StabilizerState(other)
        ret = self.copy()
        ret._data = self.clifford.compose(other.clifford, qargs=qargs)
        return ret

    def expectation_value(self, oper: Pauli | SparsePauliOp, qargs: None | list = None) -> complex:
        """Compute the expectation value of a Pauli or SparsePauliOp operator.

        Args:
            oper: A Pauli or SparsePauliOp operator to evaluate the expectation value.
            qargs: Subsystems to apply the operator on.

        Returns:
            The expectation value.

        Raises:
            QiskitError: if oper is not a Pauli or SparsePauliOp operator.
        """
        if isinstance(oper, Pauli):
            return self._expectation_value_pauli(oper, qargs)

        if isinstance(oper, SparsePauliOp):
            return sum(
                coeff * self._expectation_value_pauli(Pauli((z, x)), qargs)
                for z, x, coeff in zip(oper.paulis.z, oper.paulis.x, oper.coeffs)
            )

        raise QiskitError( #✅ NOW COVERED
            "Operator for expectation value is not a Pauli or SparsePauliOp operator, " #✅ NOW COVERED
            f"but {type(oper)}." #✅ NOW COVERED
        ) #✅ NOW COVERED

    def _expectation_value_pauli(self, oper: Pauli, qargs: None | list = None) -> complex:
        """Compute the expectation value of a Pauli operator.

        Args:
            oper (Pauli): a Pauli operator to evaluate expval.
            qargs (None or list): subsystems to apply the operator on.

        Returns:
            complex: the expectation value (only 0 or 1 or -1 or i or -i).

        Raises:
            QiskitError: if oper is not a Pauli operator.
        """
        if not isinstance(oper, Pauli):
            raise QiskitError("Operator for expectation value is not a Pauli operator.")

        num_qubits = self.clifford.num_qubits
        if qargs is None:
            qubits = range(num_qubits)
        else:
            qubits = qargs

        # Construct Pauli on num_qubits
        pauli = Pauli(num_qubits * "I")
        phase = 0
        pauli_phase = (-1j) ** oper.phase if oper.phase else 1

        for pos, qubit in enumerate(qubits):
            pauli.x[qubit] = oper.x[pos]
            pauli.z[qubit] = oper.z[pos]
            phase += pauli.x[qubit] & pauli.z[qubit]

        # Check if there is a stabilizer that anti-commutes with an odd number of qubits
        # If so the expectation value is 0
        for p in range(num_qubits):
            num_anti = 0
            num_anti += np.count_nonzero(pauli.z & self.clifford.stab_x[p])
            num_anti += np.count_nonzero(pauli.x & self.clifford.stab_z[p])
            if num_anti % 2 == 1:
                return 0

        # Otherwise pauli is (-1)^a prod_j S_j^b_j for Clifford stabilizers
        # If pauli anti-commutes with D_j then b_j = 1.
        # Multiply pauli by stabilizers with anti-commuting destabilisers
        pauli_z = (pauli.z).copy()  # Make a copy of pauli.z
        for p in range(num_qubits):
            # Check if destabilizer anti-commutes
            num_anti = 0
            num_anti += np.count_nonzero(pauli.z & self.clifford.destab_x[p])

--------------------------------------------------------------------------------
```
## Test Patch
```diff
diff --git a/test/python/quantum_info/states/test_stabilizerstate.py b/test/python/quantum_info/states/test_stabilizerstate.py
index f76df1134..11e565bc3 100644
--- a/test/python/quantum_info/states/test_stabilizerstate.py
+++ b/test/python/quantum_info/states/test_stabilizerstate.py
@@ -28,6 +28,10 @@ from qiskit.circuit.library import IGate, XGate, HGate
 from qiskit.quantum_info.operators import Clifford, Pauli, Operator, SparsePauliOp
 from test import combine  # pylint: disable=wrong-import-order
 from test import QiskitTestCase  # pylint: disable=wrong-import-order
+from qiskit.quantum_info.operators import SparsePauliOp
+from qiskit.quantum_info.states import StabilizerState
+from qiskit.exceptions import QiskitError
+from qiskit.quantum_info.random import random_clifford
 
 
 logger = logging.getLogger(__name__)
@@ -1175,6 +1179,13 @@ class TestStabilizerStateExpectationValue(QiskitTestCase):
         stab = StabilizerState(clifford)
         _ = repr(stab)
 
+    def test_expectation_value_invalid_input(self):
+        stab = StabilizerState(random_clifford(2))
+        invalid_inputs = ['invalid_input', 123, None, 3.14, {}]
+        for invalid_input in invalid_inputs:
+            with self.assertRaises(QiskitError):
+                stab.expectation_value(invalid_input)
+
 
 if __name__ == "__main__":
     unittest.main()

```
## Fully Integrated Test
The new test is fully integrated into test file `test/python/quantum_info/states/test_stabilizerstate.py`.

To view the test file, navigate to `test.py`

To view the test file before new test is added on Github, click [here](https://github.com/ShellyGarion/qiskit-terra/blob/03d1d90588060c82a8e391d9e2a6f96eb5b97f83/test/python/quantum_info/states/test_stabilizerstate.py)
## Test Runtime Log
```log
============================= test session starts ==============================
platform linux -- Python 3.11.13, pytest-8.4.1, pluggy-1.6.0
rootdir: /opt/qiskit
configfile: pyproject.toml
plugins: cov-6.2.1, hypothesis-6.135.26
collected 1 item

../opt/qiskit/test/python/quantum_info/states/test_stabilizerstate.py .  [100%]

================================ tests coverage ================================
_______________ coverage: platform linux, python 3.11.13-final-0 _______________

Coverage XML written to file coverage.xml
============================== 1 passed in 35.31s ==============================

```