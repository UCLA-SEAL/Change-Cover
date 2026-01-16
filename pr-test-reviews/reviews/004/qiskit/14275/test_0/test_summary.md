## PR Title: Add test for unsupported backend in InstructionDurations.from_backend()

## PR Description:
This pull request adds a new test to enhance coverage for the `InstructionDurations.from_backend()` method in the Qiskit repository. The test specifically checks for TypeErrors when unsupported backend types are passed. This addition covers an uncovered line in the original PR, improving overall test coverage and ensuring that the code behaves correctly under erroneous conditions. The previous coverage was 87.86%, and this new test addresses the uncovered scenarios, contributing to better code reliability.

## Lines Incremented by this Test
| File | Block | Permalink |
| ---- | ----- | --------- |
| qiskit/transpiler/instruction_durations.py | 82 | [Here](https://github.com/mtreinish/qiskit-core/blob/c6c53c42a002d89f7486accbcebc97c9837ceb97/qiskit/transpiler/instruction_durations.py#L82) |
## Lines Increment Visualization
```python
--------------------------------------------------------------------------------
# qiskit/transpiler/instruction_durations.py
--------------------------------------------------------------------------------
    """
    instruction (given by name), the qubits, and optionally the parameters of the instruction.
    Note that these fields are used as keys in dictionaries that are used to retrieve the
    instruction durations. Therefore, users must use the exact same parameter value to retrieve
    an instruction duration as the value with which it was added.
    """

    def __init__(
        self, instruction_durations: "InstructionDurationsType" | None = None, dt: float = None
    ):
        self.duration_by_name: dict[str, tuple[float, str]] = {}
        self.duration_by_name_qubits: dict[tuple[str, tuple[int, ...]], tuple[float, str]] = {}
        self.duration_by_name_qubits_params: dict[
            tuple[str, tuple[int, ...], tuple[float, ...]], tuple[float, str]
        ] = {}
        self.dt = dt
        if instruction_durations:
            self.update(instruction_durations)

    def __str__(self):
        """Return a string representation of all stored durations."""
        string = ""
        for k, v in self.duration_by_name.items():
            string += k
            string += ": "
            string += str(v[0]) + " " + v[1]
            string += "\n"
        for k, v in self.duration_by_name_qubits.items():
            string += k[0] + str(k[1])
            string += ": "
            string += str(v[0]) + " " + v[1]
            string += "\n"
        return string

    @classmethod
    def from_backend(cls, backend: Backend):
        """Construct an :class:`InstructionDurations` object from the backend.

        Args:
            backend: backend from which durations (gate lengths) and dt are extracted.

        Returns:
            InstructionDurations: The InstructionDurations constructed from backend.

        Raises:
            TranspilerError: If dt and dtm is different in the backend.
            TypeError: If the backend is the wrong type
        """
        # All durations in seconds in gate_length
        if isinstance(backend, BackendV2):
            return backend.target.durations()
        raise TypeError("Unsupported backend type: {backend}") #✅ NOW COVERED

    def update(self, inst_durations: "InstructionDurationsType" | None, dt: float = None):
        """Update self with inst_durations (inst_durations overwrite self).

        Args:
            inst_durations: Instruction durations to be merged into self (overwriting self).
            dt: Sampling duration in seconds of the target backend.

        Returns:
            InstructionDurations: The updated InstructionDurations.

        Raises:
            TranspilerError: If the format of instruction_durations is invalid.
        """
        if dt:
            self.dt = dt

        if inst_durations is None:
            return self

        if isinstance(inst_durations, InstructionDurations):
            self.duration_by_name.update(inst_durations.duration_by_name)
            self.duration_by_name_qubits.update(inst_durations.duration_by_name_qubits)
            self.duration_by_name_qubits_params.update(
                inst_durations.duration_by_name_qubits_params
            )
        else:
            for i, items in enumerate(inst_durations):
                if not isinstance(items[-1], str):
                    items = (*items, "dt")  # set default unit

                if len(items) == 4:  # (inst_name, qubits, duration, unit)
                    inst_durations[i] = (*items[:3], None, items[3])
                else:
                    inst_durations[i] = items

                # assert (inst_name, qubits, duration, parameters, unit)
                if len(inst_durations[i]) != 5:
                    raise TranspilerError(
                        "Each entry of inst_durations dictionary must be "
                        "(inst_name, qubits, duration) or "
                        "(inst_name, qubits, duration, unit) or"
                        "(inst_name, qubits, duration, parameters) or"
                        "(inst_name, qubits, duration, parameters, unit) "
                        f"received {inst_durations[i]}."
                    )

                if inst_durations[i][2] is None:
                    raise TranspilerError(f"None duration for {inst_durations[i]}.")


--------------------------------------------------------------------------------
```
## Test Patch
```diff
diff --git a/test/python/transpiler/test_instruction_durations.py b/test/python/transpiler/test_instruction_durations.py
index 0dfe20e3d..56738530a 100644
--- a/test/python/transpiler/test_instruction_durations.py
+++ b/test/python/transpiler/test_instruction_durations.py
@@ -19,6 +19,7 @@ from qiskit.providers.fake_provider import GenericBackendV2
 from qiskit.transpiler.exceptions import TranspilerError
 from qiskit.transpiler.instruction_durations import InstructionDurations
 from test import QiskitTestCase  # pylint: disable=wrong-import-order
+import unittest


 class TestInstructionDurationsClass(QiskitTestCase):
@@ -78,3 +79,9 @@ class TestInstructionDurationsClass(QiskitTestCase):
         inst_durations = InstructionDurations.from_backend(backend)
         self.assertEqual(inst_durations, backend.target.durations())
         self.assertIsInstance(inst_durations, InstructionDurations)
+
+    def test_from_duration_with_unsupported_backend(self):
+        unsupported_backends = [None, 'InvalidBackend', 123]
+        for unsupported_backend in unsupported_backends:
+            with self.assertRaises(TypeError):
+                InstructionDurations.from_backend(unsupported_backend)

```
## Fully Integrated Test
The new test is fully integrated into test file `test/python/transpiler/test_instruction_durations.py`.

To view the test file, navigate to `test.py`

To view the test file before new test is added on Github, click [here](https://github.com/mtreinish/qiskit-core/blob/c6c53c42a002d89f7486accbcebc97c9837ceb97/test/python/transpiler/test_instruction_durations.py)
## Test Runtime Log
```log
============================= test session starts ==============================
platform linux -- Python 3.11.13, pytest-8.4.1, pluggy-1.6.0
rootdir: /opt/qiskit
configfile: pyproject.toml
plugins: cov-6.2.1, hypothesis-6.135.29
collected 1 item

../opt/qiskit/test/python/transpiler/test_instruction_durations.py .     [100%]

================================ tests coverage ================================
_______________ coverage: platform linux, python 3.11.13-final-0 _______________

Coverage XML written to file coverage.xml
============================== 1 passed in 36.40s ==============================

```