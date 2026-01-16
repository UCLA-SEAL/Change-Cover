## PR Title: Add test cases for FullAdderSynthesisDefault to improve coverage

## PR Description: 
This pull request adds new test cases for the `FullAdderSynthesisDefault` class, enhancing the test coverage of the original PR #13530. The tests ensure that the synthesis method correctly handles both valid and invalid inputs, improving the robustness of the implementation. Specifically, it checks the behavior with an invalid input type, a valid `FullAdderGate`, and a non-gate input. This addition addresses previously uncovered lines in the synthesis plugin, ensuring better reliability and performance of the quantum circuit synthesis functionality.

## Lines Incremented by this Test
| File | Block | Permalink |
| ---- | ----- | --------- |
| qiskit/transpiler/passes/synthesis/hls_plugins.py | 1440 | [Here](https://github.com/alexanderivrii/qiskit-terra/blob/c39d08e0f6f91b1d80ddead3f15078b46219670a/qiskit/transpiler/passes/synthesis/hls_plugins.py#L1440) |
## Lines Increment Visualization
```python
--------------------------------------------------------------------------------
# qiskit/transpiler/passes/synthesis/hls_plugins.py
--------------------------------------------------------------------------------
class HalfAdderSynthesisV95(HighLevelSynthesisPlugin):
    """A ripple-carry adder with a carry-out bit.

    This plugin name is:``HalfAdder.ripple_v95`` which can be used as the key on
    an :class:`~.HLSConfig` object to use this method with :class:`~.HighLevelSynthesis`.

    For an adder on 2 registers with :math:`n` qubits each, this plugin requires at
    least :math:`n-1` clean auxiliary qubit.

    The plugin supports the following plugin-specific options:

    * ``num_clean_ancillas``: The number of clean auxiliary qubits available.
    """

    def run(self, high_level_object, coupling_map=None, target=None, qubits=None, **options):
        if not isinstance(high_level_object, HalfAdderGate):
            return None

        num_state_qubits = high_level_object.num_state_qubits

        # The synthesis method needs n-1 clean ancilla qubits
        if num_state_qubits - 1 > options.get("num_clean_ancillas", 0):
            return None

        return adder_ripple_v95(num_state_qubits, kind="half")


class HalfAdderSynthesisD00(HighLevelSynthesisPlugin):
    """A QFT-based adder with a carry-in and a carry-out bit.

    This plugin name is:``HalfAdder.qft_d00`` which can be used as the key on
    an :class:`~.HLSConfig` object to use this method with :class:`~.HighLevelSynthesis`.
    """

    def run(self, high_level_object, coupling_map=None, target=None, qubits=None, **options):
        if not isinstance(high_level_object, HalfAdderGate):
            return None

        return adder_qft_d00(high_level_object.num_state_qubits, kind="half")


class FullAdderSynthesisDefault(HighLevelSynthesisPlugin):
    """A ripple-carry adder with a carry-in and a carry-out bit.

    This plugin name is:``FullAdder.default`` which can be used as the key on
    an :class:`~.HLSConfig` object to use this method with :class:`~.HighLevelSynthesis`.
    """

    def run(self, high_level_object, coupling_map=None, target=None, qubits=None, **options):
        if not isinstance(high_level_object, FullAdderGate):
            return None #✅ NOW COVERED

        # FullAdderSynthesisC04 requires no ancilla qubits and returns better results
        # than FullAdderSynthesisV95 in all cases except for n=1.
        if high_level_object.num_state_qubits == 1:
            decomposition = FullAdderSynthesisV95().run(
                high_level_object, coupling_map, target, qubits, **options
            )
            if decomposition is not None:
                return decomposition

        return FullAdderSynthesisC04().run(
            high_level_object, coupling_map, target, qubits, **options
        )


class FullAdderSynthesisC04(HighLevelSynthesisPlugin):
    """A ripple-carry adder with a carry-in and a carry-out bit.

    This plugin name is:``FullAdder.ripple_c04`` which can be used as the key on
    an :class:`~.HLSConfig` object to use this method with :class:`~.HighLevelSynthesis`.

    This plugin requires no auxiliary qubits.
    """

    def run(self, high_level_object, coupling_map=None, target=None, qubits=None, **options):
        if not isinstance(high_level_object, FullAdderGate):
            return None

        return adder_ripple_c04(high_level_object.num_state_qubits, kind="full")


class FullAdderSynthesisV95(HighLevelSynthesisPlugin):
    """A ripple-carry adder with a carry-in and a carry-out bit.

    This plugin name is:``FullAdder.ripple_v95`` which can be used as the key on
    an :class:`~.HLSConfig` object to use this method with :class:`~.HighLevelSynthesis`.

    For an adder on 2 registers with :math:`n` qubits each, this plugin requires at
    least :math:`n-1` clean auxiliary qubits.

    The plugin supports the following plugin-specific options:

    * ``num_clean_ancillas``: The number of clean auxiliary qubits available.
    """

    def run(self, high_level_object, coupling_map=None, target=None, qubits=None, **options):
        if not isinstance(high_level_object, FullAdderGate):
            return None

        num_state_qubits = high_level_object.num_state_qubits

--------------------------------------------------------------------------------
```
## Test Patch
```diff
diff --git a/test/python/circuit/library/test_adders.py b/test/python/circuit/library/test_adders.py
index 5c960cedb..f33d838fa 100644
--- a/test/python/circuit/library/test_adders.py
+++ b/test/python/circuit/library/test_adders.py
@@ -29,6 +29,8 @@ from qiskit.circuit.library import (
 from qiskit.synthesis.arithmetic import adder_ripple_c04, adder_ripple_v95, adder_qft_d00
 from qiskit.transpiler.passes import HLSConfig, HighLevelSynthesis
 from test import QiskitTestCase  # pylint: disable=wrong-import-order
+from qiskit.circuit.library.arithmetic.adders import FullAdderGate
+from qiskit.transpiler.passes.synthesis.hls_plugins import FullAdderSynthesisDefault
 
 ADDERS = {
     "vbe": adder_ripple_v95,
@@ -304,6 +306,20 @@ class TestAdder(QiskitTestCase):
             ops = set(synth.count_ops().keys())
             self.assertTrue("MAJ" in ops)
 
+    def test_invalid_full_adder_input(self):
+        synthesis = FullAdderSynthesisDefault()
+        result = synthesis.run('invalid_input')
+        self.assertIsNone(result)
+    def test_valid_full_adder_input(self):
+        synthesis = FullAdderSynthesisDefault()
+        adder = FullAdderGate(2)
+        result = synthesis.run(adder)
+        self.assertIsNotNone(result)
+    def test_non_full_adder_input(self):
+        synthesis = FullAdderSynthesisDefault()
+        result = synthesis.run(123)  # Non-gate input
+        self.assertIsNone(result)  # Ensure it correctly returns None
+
 
 if __name__ == "__main__":
     unittest.main()

```
## Fully Integrated Test
The new test is fully integrated into test file `test/python/circuit/library/test_adders.py`.

To view the test file, navigate to `test.py`

To view the test file before new test is added on Github, click [here](https://github.com/alexanderivrii/qiskit-terra/blob/c39d08e0f6f91b1d80ddead3f15078b46219670a/test/python/circuit/library/test_adders.py)
## Test Runtime Log
```log
============================= test session starts ==============================
platform linux -- Python 3.11.13, pytest-8.4.1, pluggy-1.6.0
rootdir: /opt/qiskit
configfile: pyproject.toml
plugins: cov-6.2.1, hypothesis-6.135.29
collected 3 items

../opt/qiskit/test/python/circuit/library/test_adders.py ...             [100%]

================================ tests coverage ================================
_______________ coverage: platform linux, python 3.11.13-final-0 _______________

Coverage XML written to file coverage.xml
============================== 3 passed in 40.98s ==============================

```