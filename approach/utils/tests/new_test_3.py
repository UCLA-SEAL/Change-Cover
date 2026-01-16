from scipy.optimize import least_squares
from numpy.testing import suppress_warnings
import pytest

def fun_trivial(x, a=0):
    return (x - a)**2 + 5.0

def jac_trivial(x, a=0.0):
    return 2 * (x - a)

class TestLM:

    @skip_xp_backends(cpu_only=True, reason="PyTorch doesn't have `betainc`.")
    @pytest.mark.xslow
    @pytest.mark.parametrize("arg1", [1, 2, 3, 4, 
                                      5, 6, 7, 8, 9, 10])
    def test_dummy(self, arg1):
        x0 = [1.0]
        a = 2.0
        res = least_squares(fun_trivial, x0, args=(a,))
        assert(res.success)