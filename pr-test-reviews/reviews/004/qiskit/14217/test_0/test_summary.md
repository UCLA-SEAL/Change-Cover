## PR Title: Add unit test for 180-degree rotation axis in Solovay-Kitaev decomposition

## PR Description: 
This pull request introduces a new unit test that enhances coverage for the Solovay-Kitaev decomposition implementation by validating the computed rotation axes for 180-degree rotations. The test checks the correctness of the `_compute_rotation_axis` function, which was previously uncovered. By asserting that the results for X, Y, and Z rotation matrices meet expected values, we ensure the accuracy of the decomposition algorithm. This addition contributes to the ongoing efforts to improve test coverage and maintain the integrity of the Qiskit library.

## Lines Incremented by this Test
| File | Block | Permalink |
| ---- | ----- | --------- |
| qiskit/synthesis/discrete_basis/commutator_decompose.py | 67-68 | [Here](https://github.com/alexanderivrii/qiskit-terra/blob/cea0a0e96dd20b409a21d3c6e4d454eccf450735/qiskit/synthesis/discrete_basis/commutator_decompose.py#L67-L68) |
| qiskit/synthesis/discrete_basis/commutator_decompose.py | 70-77 | [Here](https://github.com/alexanderivrii/qiskit-terra/blob/cea0a0e96dd20b409a21d3c6e4d454eccf450735/qiskit/synthesis/discrete_basis/commutator_decompose.py#L70-L77) |
| qiskit/synthesis/discrete_basis/commutator_decompose.py | 79-81 | [Here](https://github.com/alexanderivrii/qiskit-terra/blob/cea0a0e96dd20b409a21d3c6e4d454eccf450735/qiskit/synthesis/discrete_basis/commutator_decompose.py#L79-L81) |
## Lines Increment Visualization
```python
--------------------------------------------------------------------------------
# qiskit/synthesis/discrete_basis/commutator_decompose.py
--------------------------------------------------------------------------------
import math
import numpy as np
from qiskit.quantum_info.operators.predicates import is_identity_matrix
from .gate_sequence import _check_is_so3, GateSequence


def _compute_trace_so3(matrix: np.ndarray) -> float:
    """Computes trace of an SO(3)-matrix.

    Args:
        matrix: an SO(3)-matrix

    Returns:
        Trace of ``matrix``.

    Raises:
        ValueError: if ``matrix`` is not an SO(3)-matrix.
    """
    _check_is_so3(matrix)

    trace = np.matrix.trace(matrix)
    trace_rounded = min(trace, 3)
    return trace_rounded


def _compute_rotation_axis(matrix: np.ndarray) -> np.ndarray:
    """Computes rotation axis of SO(3)-matrix.

    Args:
        matrix: The SO(3)-matrix for which rotation angle needs to be computed.

    Returns:
        The rotation axis of the SO(3)-matrix ``matrix``.

    Raises:
        ValueError: if ``matrix`` is not an SO(3)-matrix.
    """
    _check_is_so3(matrix)

    # If theta represents the rotation angle, then trace = 1 + 2cos(theta).
    trace = _compute_trace_so3(matrix)

    if trace >= 3 - 1e-10:
        # The matrix is the identity (rotation by 0)
        x = 1.0
        y = 0.0
        z = 0.0

    elif trace <= -1 + 1e-10:
        # The matrix is the 180-degree rotation
        squares = (1 + np.diagonal(matrix)) / 2 #✅ NOW COVERED
        index_of_max = np.argmax(squares) #✅ NOW COVERED

        if index_of_max == 0: #✅ NOW COVERED
            x = math.sqrt(squares[0]) #✅ NOW COVERED
            y = matrix[0][1] / (2 * x) #✅ NOW COVERED
            z = matrix[0][2] / (2 * x) #✅ NOW COVERED
        elif index_of_max == 1: #✅ NOW COVERED
            y = math.sqrt(squares[1]) #✅ NOW COVERED
            x = matrix[0][1] / (2 * y) #✅ NOW COVERED
            z = matrix[1][2] / (2 * y) #✅ NOW COVERED
        else:
            z = math.sqrt(squares[2]) #✅ NOW COVERED
            x = matrix[0][2] / (2 * z) #✅ NOW COVERED
            y = matrix[1][2] / (2 * z) #✅ NOW COVERED

    else:
        # The matrix is the rotation by theta with sin(theta)!=0
        theta = math.acos(0.5 * (trace - 1))
        x = 1 / (2 * math.sin(theta)) * (matrix[2][1] - matrix[1][2])
        y = 1 / (2 * math.sin(theta)) * (matrix[0][2] - matrix[2][0])
        z = 1 / (2 * math.sin(theta)) * (matrix[1][0] - matrix[0][1])

    return np.array([x, y, z])


def _solve_decomposition_angle(matrix: np.ndarray) -> float:
    """Computes angle for balanced commutator of SO(3)-matrix ``matrix``.

    Computes angle a so that the SO(3)-matrix ``matrix`` can be decomposed
    as commutator [v,w] where v and w are both rotations of a about some axis.
    The computation is done by solving a trigonometric equation using scipy.optimize.fsolve.

    Args:
        matrix: The SO(3)-matrix for which the decomposition angle needs to be computed.

    Returns:
        Angle a so that matrix = [v,w] with v and w rotations of a about some axis.

    Raises:
        ValueError: if ``matrix`` is not an SO(3)-matrix.
    """
    from scipy.optimize import fsolve

    _check_is_so3(matrix)

    trace = _compute_trace_so3(matrix)
    angle = math.acos((1 / 2) * (trace - 1))

    lhs = math.sin(angle / 2)

    def objective(phi):
        sin_sq = math.sin(phi.item() / 2) ** 2
        return 2 * sin_sq * math.sqrt(1 - sin_sq**2) - lhs

    decomposition_angle = fsolve(objective, angle)[0]
    return decomposition_angle


def _compute_rotation_from_angle_and_axis(angle: float, axis: np.ndarray) -> np.ndarray:
    """Computes the SO(3)-matrix corresponding to the rotation of ``angle`` about ``axis``.

    Args:
        angle: The angle of the rotation.
        axis: The axis of the rotation.

--------------------------------------------------------------------------------
```
## Test Patch
```diff
diff --git a/test/python/transpiler/test_solovay_kitaev.py b/test/python/transpiler/test_solovay_kitaev.py
index da3a0840e..95e432bab 100644
--- a/test/python/transpiler/test_solovay_kitaev.py
+++ b/test/python/transpiler/test_solovay_kitaev.py
@@ -37,6 +37,7 @@ from qiskit.transpiler import PassManager
 from qiskit.transpiler.passes import UnitarySynthesis, Collect1qRuns, ConsolidateBlocks
 from qiskit.transpiler.passes.synthesis import SolovayKitaev, SolovayKitaevSynthesis
 from test import QiskitTestCase  # pylint: disable=wrong-import-order
+from qiskit.synthesis.discrete_basis.commutator_decompose import _compute_rotation_axis
 
 
 def _trace_distance(circuit1, circuit2):
@@ -479,3 +480,32 @@ class TestSolovayKitaevUtils(QiskitTestCase):
 
 if __name__ == "__main__":
     unittest.main()
+
+class TestRotationAxis:
+    def test_180_degree_rotation(self):
+        def is_so3_matrix(matrix):
+            return np.allclose(np.dot(matrix, matrix.T), np.eye(3)) and np.isclose(np.linalg.det(matrix), 1)
+
+        x_rotation = np.array([[1, 0, 0], [0, -1, 0], [0, 0, -1]])  # 180-degree X rotation
+        y_rotation = np.array([[-1, 0, 0], [0, 1, 0], [0, 0, -1]])  # 180-degree Y rotation
+        z_rotation = np.array([[-1, 0, 0], [0, -1, 0], [0, 0, 1]])  # 180-degree Z rotation
+
+        assert is_so3_matrix(x_rotation), 'X Rotation is not a valid SO(3) matrix'
+        assert is_so3_matrix(y_rotation), 'Y Rotation is not a valid SO(3) matrix'
+        assert is_so3_matrix(z_rotation), 'Z Rotation is not a valid SO(3) matrix'
+
+        # Validate the computed rotation axes
+        x_axis, y_axis, z_axis = _compute_rotation_axis(x_rotation)
+        assert math.isclose(x_axis, 1.0)
+        assert math.isclose(y_axis, 0.0)
+        assert math.isclose(z_axis, 0.0)
+
+        x_axis, y_axis, z_axis = _compute_rotation_axis(y_rotation)
+        assert math.isclose(x_axis, 0.0)
+        assert math.isclose(y_axis, 1.0)
+        assert math.isclose(z_axis, 0.0)
+
+        x_axis, y_axis, z_axis = _compute_rotation_axis(z_rotation)
+        assert math.isclose(x_axis, 0.0)
+        assert math.isclose(y_axis, 0.0)
+        assert math.isclose(z_axis, 1.0)

```
## Fully Integrated Test
The new test is fully integrated into test file `test/python/transpiler/test_solovay_kitaev.py`.

To view the test file, navigate to `test.py`

To view the test file before new test is added on Github, click [here](https://github.com/alexanderivrii/qiskit-terra/blob/cea0a0e96dd20b409a21d3c6e4d454eccf450735/test/python/transpiler/test_solovay_kitaev.py)
## Test Runtime Log
```log
============================= test session starts ==============================
platform linux -- Python 3.11.13, pytest-8.4.1, pluggy-1.6.0
rootdir: /opt/qiskit
configfile: pyproject.toml
plugins: cov-6.2.1, hypothesis-6.135.29
collected 1 item

../opt/qiskit/test/python/transpiler/test_solovay_kitaev.py .            [100%]

================================ tests coverage ================================
_______________ coverage: platform linux, python 3.11.13-final-0 _______________

Coverage XML written to file coverage.xml
============================== 1 passed in 32.16s ==============================

```