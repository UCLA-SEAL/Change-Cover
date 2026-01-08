# MERGED using ADD mode
# /opt/qiskit/test/python/transpiler/test_consolidate_blocks.py
# This code is part of Qiskit.
#
# (C) Copyright IBM 2017, 2019.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""
Tests for the ConsolidateBlocks transpiler pass.
"""

import numpy as np
from ddt import ddt, data

from qiskit.circuit import QuantumCircuit, QuantumRegister, IfElseOp, Gate, Parameter
from qiskit.circuit.library import (
    U2Gate,
    SwapGate,
    CXGate,
    CZGate,
    ECRGate,
    UnitaryGate,
    SXGate,
    XGate,
    RZGate,
    RZZGate,
)
from qiskit.converters import circuit_to_dag
from qiskit.quantum_info.operators import Operator
from qiskit.quantum_info.operators.measures import process_fidelity
from qiskit.transpiler import PassManager, Target, generate_preset_pass_manager
from qiskit.transpiler.passes import ConsolidateBlocks, Collect1qRuns, Collect2qBlocks
from test import QiskitTestCase  # pylint: disable=wrong-import-order


@ddt
class TestConsolidateBlocks(QiskitTestCase):
    """
    Tests to verify that consolidating blocks of gates into unitaries
    works correctly.
    """

    """
    NOTE: Many functions are OMITTED
    """

    @data(CXGate, CZGate, ECRGate)
    def test_rzz_collection(self, basis_gate):
        """Test that a parameterized gate outside the target is consolidated."""
        phi = Parameter("phi")
        target = Target(num_qubits=2)
        target.add_instruction(SXGate(), {(0,): None, (1,): None})
        target.add_instruction(XGate(), {(0,): None, (1,): None})
        target.add_instruction(RZGate(phi), {(0,): None, (1,): None})
        target.add_instruction(basis_gate(), {(0, 1): None, (1, 0): None})
        consolidate_pass = ConsolidateBlocks(target=target)

        for angle in [np.pi / 2, np.pi]:
            qc = QuantumCircuit(2)
            qc.rzz(angle, 0, 1)
            res = consolidate_pass(qc)
            expected = QuantumCircuit(2)
            expected.unitary(np.asarray(RZZGate(angle)), [0, 1])
            self.assertEqual(res, expected)
