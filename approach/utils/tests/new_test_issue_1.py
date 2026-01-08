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
import unittest
from qiskit.circuit import QuantumCircuit
from qiskit.circuit.library import CXGate
from qiskit.transpiler import PassManager
from qiskit.transpiler.passes import ConsolidateBlocks
from qiskit.transpiler.passes import Collect2qBlocks
from qiskit.transpiler import Target


@ddt
class TestConsolidateBlocks(QiskitTestCase):

    def test_kak_gate_consolidation(self):
        qc = QuantumCircuit(2)
        target = Target(num_qubits=2)
        kak_basis_gate = CXGate()  # Using CXGate as a substitute for KAK gate
        target.add_instruction(kak_basis_gate)
        qc.swap(0, 1)
        consolidate_block_pass = ConsolidateBlocks(
            target=target, kak_basis_gate=kak_basis_gate)
        pass_manager = PassManager()
        pass_manager.append(Collect2qBlocks())
        pass_manager.append(consolidate_block_pass)
        expected = QuantumCircuit(2)
        expected.unitary(
            np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]]), [0, 1])
        self.assertEqual(expected, pass_manager.run(qc))
