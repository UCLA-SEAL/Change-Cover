# GeneratorBase
import pytest
import numpy as np
from scipy.optimize import root_scalar

class Test_muller:

    @pytest.mark.parametrize("mismatched_arg", [1, 2, 3, 4, 
                                      5, 6, 7, 8, 9, 10])
    def test_root_scalar_muller(self, mismatched_arg):
        def func(x):
            return x ** 2 - 2
        # Testing root_scalar with 'muller' method
        result = root_scalar(func, method='muller', x0=0, x1=1, x2=2)
        assert result.converged, "Muller's method did not converge"
        assert np.isclose(result.root, np.sqrt(2), atol=1e-6), "The root found is not correct"