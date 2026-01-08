# GeneratorBase
import numpy as np
from pytest import mark
from scipy.sparse import csc_matrix
from sksparse.cholmod import cholesky
import warnings

@mark.parametrize("matrix, expected_warning", [
    (csc_matrix([[1, 2], [0, 0]]), "CholmodTypeConversionWarning"),
])
def test_warning_suppression(matrix, expected_warning):
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')  # Always trigger warnings
        cholesky(matrix)
        assert any(expected_warning in str(warn.message) for warn in w)  # check warning is raised
