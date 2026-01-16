## PR Title: Add test for invalid 'R' parameter in fclusterdata function

## PR Description:
This pull request introduces a new test in `test_hierarchy.py` to enhance coverage of the `fclusterdata` function in the `scipy.cluster.hierarchy` module. The test specifically checks for exceptions raised when invalid shapes of the `R` parameter are provided. This addition addresses uncovered lines from the original PR, ensuring that the function behaves correctly under erroneous input conditions. With this test, we aim to improve the robustness of the implementation and prevent future regressions.

## Lines Incremented by this Test
| File | Block | Permalink |
| ---- | ----- | --------- |
| scipy/cluster/hierarchy.py | 2772 | [Here](https://github.com/crusaderky/scipy/blob/5ed17470a9163ccce8784dfae23924a1ceb39373/scipy/cluster/hierarchy.py#L2772) |
## Lines Increment Visualization
```python
--------------------------------------------------------------------------------
# scipy/cluster/hierarchy.py
--------------------------------------------------------------------------------
    """
    fclusterdata : ndarray
        A vector of length n. T[i] is the flat cluster number to
        which original observation i belongs.

    See Also
    --------
    scipy.spatial.distance.pdist : pairwise distance metrics

    Notes
    -----
    This function is similar to the MATLAB function ``clusterdata``.

    Examples
    --------
    >>> from scipy.cluster.hierarchy import fclusterdata

    This is a convenience method that abstracts all the steps to perform in a
    typical SciPy's hierarchical clustering workflow.

    * Transform the input data into a condensed matrix with
      `scipy.spatial.distance.pdist`.

    * Apply a clustering method.

    * Obtain flat clusters at a user defined distance threshold ``t`` using
      `scipy.cluster.hierarchy.fcluster`.

    >>> X = [[0, 0], [0, 1], [1, 0],
    ...      [0, 4], [0, 3], [1, 4],
    ...      [4, 0], [3, 0], [4, 1],
    ...      [4, 4], [3, 4], [4, 3]]

    >>> fclusterdata(X, t=1)
    array([3, 3, 3, 4, 4, 4, 2, 2, 2, 1, 1, 1], dtype=int32)

    The output here (for the dataset ``X``, distance threshold ``t``, and the
    default settings) is four clusters with three data points each.

    """
    xp = array_namespace(X)
    X = _asarray(X, order='C', dtype=xp.float64, xp=xp)

    if X.ndim != 2:
        raise TypeError('The observation matrix X must be an n by m array.')

    Y = distance.pdist(X, metric=metric)
    Z = linkage(Y, method=method)
    if R is None:
        R = inconsistent(Z, d=depth)
    else:
        R = _asarray(R, order='C', xp=xp) #✅ NOW COVERED
    T = fcluster(Z, criterion=criterion, depth=depth, R=R, t=t)
    return T


def leaves_list(Z):
    """
    Return a list of leaf node ids.

    The return corresponds to the observation vector index as it appears
    in the tree from left to right. Z is a linkage matrix.

    Parameters
    ----------
    Z : ndarray
        The hierarchical clustering encoded as a matrix.  `Z` is
        a linkage matrix.  See `linkage` for more information.

    Returns
    -------
    leaves_list : ndarray
        The list of leaf node ids.

    See Also
    --------
    dendrogram : for information about dendrogram structure.

    Examples
    --------
    >>> from scipy.cluster.hierarchy import ward, dendrogram, leaves_list
    >>> from scipy.spatial.distance import pdist
    >>> from matplotlib import pyplot as plt

    >>> X = [[0, 0], [0, 1], [1, 0],
    ...      [0, 4], [0, 3], [1, 4],
    ...      [4, 0], [3, 0], [4, 1],
    ...      [4, 4], [3, 4], [4, 3]]

    >>> Z = ward(pdist(X))

    The linkage matrix ``Z`` represents a dendrogram, that is, a tree that
    encodes the structure of the clustering performed.
    `scipy.cluster.hierarchy.leaves_list` shows the mapping between
    indices in the ``X`` dataset and leaves in the dendrogram:

    >>> leaves_list(Z)
    array([ 2,  0,  1,  5,  3,  4,  8,  6,  7, 11,  9, 10], dtype=int32)

    >>> fig = plt.figure(figsize=(25, 10))
    >>> dn = dendrogram(Z)
    >>> plt.show()

--------------------------------------------------------------------------------
```
## Test Patch
```diff
diff --git a/scipy/cluster/tests/test_hierarchy.py b/scipy/cluster/tests/test_hierarchy.py
index 1eb4c0d8e..2638e1a18 100644
--- a/scipy/cluster/tests/test_hierarchy.py
+++ b/scipy/cluster/tests/test_hierarchy.py
@@ -53,6 +53,7 @@ from scipy._lib.array_api_extra.testing import lazy_xp_function
 from threading import Lock

 from . import hierarchy_test_data
+from scipy.cluster.hierarchy import fclusterdata

 class eager:
     # Bypass xpx.testing.lazy_xp_function when calling
@@ -317,6 +318,17 @@ class TestFclusterData:
         T = fclusterdata(X, criterion=criterion, t=t)
         assert is_isomorphic(T, expectedT)

+    @pytest.mark.parametrize('R, expected_exception', [
+        (np.array([[1, 2], [3, 4]]), ValueError),  # Incorrect dimensions
+        (np.array([1, 2, 3]), ValueError),  # Incorrect shape
+        (np.array([[1], [2], [3]]), ValueError)  # Another incorrect shape
+    ])
+    def test_fclusterdata_invalid_R(self, R, expected_exception):
+        X = np.random.rand(10, 2)  # Sample data
+        t = 1.0  # Providing a valid threshold value
+        with pytest.raises(expected_exception):
+            fclusterdata(X, R=R, t=t, criterion='inconsistent')
+

 @skip_xp_backends(cpu_only=True)
 class TestFcluster:

```
## Fully Integrated Test
The new test is fully integrated into test file `scipy/cluster/tests/test_hierarchy.py`.

To view the test file, navigate to `test.py`

To view the test file before new test is added on Github, click [here](https://github.com/crusaderky/scipy/blob/5ed17470a9163ccce8784dfae23924a1ceb39373/scipy/cluster/tests/test_hierarchy.py)
## Test Runtime Log
```log
============================= test session starts ==============================
platform linux -- Python 3.11.12, pytest-8.3.5, pluggy-1.6.0
rootdir: /opt/scipy
configfile: pytest.ini
plugins: hypothesis-6.131.28, cov-6.1.1, timeout-2.4.0, xdist-3.7.0, anyio-4.9.0
collected 3 items

../opt/scipy/scipy/cluster/tests/test_hierarchy.py ...                   [100%]

================================ tests coverage ================================
_______________ coverage: platform linux, python 3.11.12-final-0 _______________

Coverage XML written to file coverage.xml
========================= 3 passed in 61.95s (0:01:01) =========================

```