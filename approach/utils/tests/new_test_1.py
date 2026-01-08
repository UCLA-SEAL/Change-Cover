import pytest
import numpy as np
from scipy import stats
from scipy._lib._array_api import xp_assert_close
marray = pytest.importorskip('marray')

def test_length_nonmasked_with_iterable_axis():
    mxp, marrays, _ = get_arrays(1, xp=np)
    with pytest.raises(NotImplementedError):
        stats._length_nonmasked(marrays[0], axis=[0, 1])

def get_arrays(n_arrays, *, dtype='float64', xp=np, shape=(7, 8), seed=84912165484321):
    mxp = marray._get_namespace(xp)
    rng = np.random.default_rng(seed)
    datas, masks = ([], [])
    for i in range(n_arrays):
        data = rng.random(size=shape)
        if dtype.startswith('complex'):
            data = 10 * data * 10j * rng.standard_normal(size=shape)
        data = data.astype(dtype)
        datas.append(data)
        mask = rng.random(size=shape) > 0.75
        masks.append(mask)
    marrays = []
    for array, mask in zip(datas, masks):
        marrays.append(mxp.asarray(array, mask=mask))
    return (mxp, marrays)
