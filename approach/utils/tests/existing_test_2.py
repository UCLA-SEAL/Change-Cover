from itertools import product
from multiprocessing import Pool

import numpy as np
from numpy.linalg import norm
from numpy.testing import (assert_, assert_allclose,
                           assert_equal, suppress_warnings)
import pytest
from pytest import raises as assert_raises
from scipy.sparse import issparse, lil_array
from scipy.sparse.linalg import aslinearoperator

from scipy.optimize import least_squares, Bounds
from scipy.optimize._lsq.least_squares import IMPLEMENTED_LOSSES
from scipy.optimize._lsq.common import EPS, make_strictly_feasible, CL_scaling_vector

from scipy.optimize import OptimizeResult

def fun_trivial(x, a=0):
    return (x - a)**2 + 5.0


def jac_trivial(x, a=0.0):
    return 2 * (x - a)


class TestLM():
    method = 'lm'

    def test_bounds_not_supported(self):
        assert_raises(ValueError, least_squares, fun_trivial,
                      2.0, bounds=(-3.0, 3.0), method='lm')


    def test_jac_sparsity_not_supported(self):
        assert_raises(ValueError, least_squares, fun_trivial, 2.0,
                      jac_sparsity=[1], method='lm')

def test_basic():
    # test that 'method' arg is really optional
    res = least_squares(fun_trivial, 2.0)
    assert_allclose(res.x, 0, atol=1e-10)