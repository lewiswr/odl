# Copyright 2014, 2015 The ODL development group
#
# This file is part of ODL.
#
# ODL is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# ODL is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with ODL.  If not, see <http://www.gnu.org/licenses/>.

# pylint: disable=abstract-method

# Imports for common Python 2/3 codebase
from __future__ import print_function, division, absolute_import

from future import standard_library
standard_library.install_aliases()
from builtins import super, str, zip
from future.utils import with_metaclass

# External imports
from abc import ABCMeta
import numpy as np
from scipy.interpolate import RegularGridInterpolator
from scipy.interpolate.interpnd import _ndim_coords_from_arrays

# ODL imports
from odl.discr.grid import TensorGrid
from odl.operator.operator import Operator
from odl.space.base_ntuples import NtuplesBase, FnBase
from odl.space.fspace import FunctionSet, FunctionSpace
from odl.set.domain import IntervalProd


__all__ = ('FunctionSetMapping',
           'GridCollocation', 'NearestInterpolation', 'LinearInterpolation')


class FunctionSetMapping(Operator):

    """Abstract base class for function set discretization mappings."""

    def __init__(self, map_type, fset, grid, dspace, order='C', linear=False):
        """Initialize a new instance.

        Parameters
        ----------
        map_type : {'restriction', 'extension'}
            The type of operator
        fset : `FunctionSet`
            The undiscretized (abstract) set of functions to be
            discretized
        grid : `TensorGrid`
            The grid on which to evaluate. Must be contained in
            the common domain of the function set.
        dspace : `NtuplesBase`
            Data space providing containers for the values of a
            discretized object. Its dimension must be equal to the
            total number of grid points.
        order : {'C', 'F'}, optional
            Ordering of the values in the flat data arrays. 'C'
            means the first grid axis varies fastest, the last most
            slowly, 'F' vice versa.
        linear : bool
            Create a linear operator if `True`, otherwise a non-linear
            operator.
        """
        map_type_ = str(map_type).lower()
        if map_type_ not in ('restriction', 'extension'):
            raise ValueError('mapping type {!r} not understood.'
                             ''.format(map_type))
        if not isinstance(fset, FunctionSet):
            raise TypeError('function set {} is not a `FunctionSet` instance.'
                            ''.format(fset))
        if not isinstance(grid, TensorGrid):
            raise TypeError('grid {} is not a `TensorGrid` instance.'
                            ''.format(grid))
        if not isinstance(dspace, NtuplesBase):
            raise TypeError('data space {!r} is not an `NtuplesBase` instance.'
                            ''.format(dspace))

        # TODO: this method is expected to exist, which is the case for
        # interval products. It could be a general optional `Set` method
        if not fset.domain.contains_set(grid):
            raise ValueError('grid {} not contained in the domain {} of the '
                             'function set {}.'.format(grid, fset.domain,
                                                       fset))

        if dspace.size != grid.ntotal:
            raise ValueError('size {} of the data space {} not equal '
                             'to the total number {} of grid points.'
                             ''.format(dspace.size, dspace, grid.ntotal))

        self._order = str(order).upper()
        if self._order not in ('C', 'F'):
            raise ValueError('ordering {!r} not understood.'.format(order))

        dom = fset if map_type_ == 'restriction' else dspace
        ran = dspace if map_type_ == 'restriction' else fset
        super().__init__(dom, ran, linear=linear)
        self._grid = grid

        if self.is_linear:
            if not isinstance(fset, FunctionSpace):
                raise TypeError('function space {} is not a `FunctionSpace` '
                                'instance.'.format(fset))
            if not isinstance(dspace, FnBase):
                raise TypeError('data space {} is not an `FnBase` instance.'
                                ''.format(dspace))
            if fset.field != dspace.field:
                raise ValueError('field {} of the function space and field {} '
                                 'of the data space are not equal.'
                                 ''.format(fset.field, dspace.field))

    def __eq__(self, other):
        return (isinstance(other, type(self)) and
                isinstance(self, type(other)) and
                self.domain == other.domain and
                self.range == other.range and
                self.grid == other.grid and
                self.order == other.order)

    @property
    def grid(self):
        """The sampling grid."""
        return self._grid

    @property
    def order(self):
        """The axis ordering."""
        return self._order


class GridCollocation(FunctionSetMapping):

    """Function evaluation at grid points.

    This is the default 'restriction' used by all core discretization classes.
    """

    def __init__(self, ip_fset, grid, dspace, order='C'):
        """Initialize a new instance.

        Parameters
        ----------
        ip_fset : `FunctionSet`
            The undiscretized (abstract) set of functions to be
            discretized. The function domain must be an
            `IntervalProd`.
        grid : `TensorGrid`
            The grid on which to evaluate. It must be contained in
            the common domain of the function set.
        dspace : `NtuplesBase`
            Data space providing containers for the values of a
            discretized object. Its size must be equal to the
            total number of grid points.
        order : {'C', 'F'}, optional
            Ordering of the values in the flat data arrays. 'C'
            means the first grid axis varies fastest, the last most
            slowly, 'F' vice versa.
        """
        if isinstance(ip_fset, FunctionSpace):
            linear = True
        else:
            linear = False
        # TODO: how about the IntervalProd check for ip_fset.domain?
        super().__init__('restriction', ip_fset, grid, dspace, order,
                         linear=linear)

    # TODO: Implement _apply()

    def _call(self, x):
        """The raw `call` method for out-of-place evaluation.

        Parameters
        ----------
        x : `FunctionSet.Vector`
            The function to be evaluated. It must accept point
            coordinates in list form (`f(x, y, z)` rather than
            `f(point)`) and return either a NumPy array of the correct
            type (defined by the `Ntuples` instance) or a single value.

        Returns
        -------
        out : `Ntuples.Vector`
            The function values at the grid points.

        Note
        ----
        The code of this call tries to make use of vectorization of
        the input function, which makes execution much faster and
        memory-saving. If this fails, it falls back to a slow
        loop-based variant.

        Write your function such that every variable occurs -
        otherwise, the values will not be broadcasted to the correct
        size (see example below).

        Avoid using the `numpy.vectorize` function - it is merely a
        convenience function and will not give any speed benefit.

        See also
        --------
        See the `meshgrid` method of `TensorGrid` in `odl.discr.grid`
        or the `numpy.meshgrid` function for an explanation of
        meshgrids.

        Examples
        --------
        Define the grid:

        >>> from odl import TensorGrid
        >>> grid = TensorGrid([1, 2], [3, 4, 5], as_midp=True)

        The `dspace` backend is `Rn`:

        >>> from odl import Rn
        >>> rn = Rn(grid.ntotal)

        Define a set of functions from the convex hull of the grid
        to the real numbers:

        >>> from odl import FunctionSet, RealNumbers
        >>> funcset = FunctionSet(grid.convex_hull(), RealNumbers())

        Finally create the operator:

        >>> coll_op = GridCollocation(funcset, grid, rn)

        We define an example function with meshgrid vectorization:

        >>> def func(mg_tuple):
        ...     x1, x2 = mg_tuple  # unwrap the coordinate arrays
        ...     return x1 - x2
        >>> func_elem = funcset.element(func, vectorization='meshgrid')
        >>> coll_op(func_elem)
        Rn(6).element([-2.0, -3.0, -4.0, -1.0, -2.0, -3.0])

        Array vectorization (slower):
        >>> def func(array):
        ...     x1, x2 = array[:, 0], array[:, 1]  # views
        ...     return x1 - x2
        >>> func_elem = funcset.element(func, vectorization='array')
        >>> coll_op(func_elem)
        Rn(6).element([-2.0, -3.0, -4.0, -1.0, -2.0, -3.0])

        Or, if we want Fortran ordering:

        >>> coll_op = GridCollocation(funcset, grid, rn, order='F')
        >>> coll_op(func_elem)
        Rn(6).element([-2.0, -1.0, -3.0, -2.0, -4.0, -3.0])
        """
        if x.vectorization == 'meshgrid':
            mg_tuple = self.grid.meshgrid()
            values = x(mg_tuple).ravel(order=self.order)
        else:
            points = self.grid.points(order=self.order)
            if x.vectorization == 'array':
                values = x(points)
            else:
                values = np.empty(points.shape[0], dtype=self.range.dtype)
                for i, point in enumerate(points):
                    values[i] = x(point)
        return self.range.element(values)


class NearestInterpolation(FunctionSetMapping):

    """Nearest neighbor interpolation as an `Operator`."""

    def __init__(self, ip_fset, grid, dspace, order='C'):
        """Initialize a new `NearestInterpolation` instance.

        Parameters
        ----------
        ip_fset : `FunctionSet`
            The undiscretized (abstract) set of functions to be
            discretized. The function domain must be an
            `IntervalProd`.
        grid : `TensorGrid`
            The grid on which to evaluate. Must be contained in
            the common domain of the function set.
        dspace : `NtuplesBase`
            Data space providing containers for the values of a
            discretized object. Its size must be equal to the
            total number of grid points.
        order : {'C', 'F'}, optional
            Ordering of the values in the flat data arrays. 'C'
            means the first grid axis varies fastest, the last most
            slowly, 'F' vice versa.
        """
        if isinstance(ip_fset, FunctionSpace):
            linear = True
        else:
            linear = False
        super().__init__('extension', ip_fset, grid, dspace, order,
                         linear=linear)

    # TODO: Implement _apply()

    def _call(self, x, vectorization='meshgrid'):
        """The raw `call` method for out-of-place evaluation.

        Parameters
        ----------
        x : `Ntuples.Vector`
            The array of numbers to be interpolated
        vectorization : {'none', 'array', 'meshgrid'}
            Vectorization type of the returned function.

            'none' : no vectorized evaluation

            'array' : vectorized evaluation on an array of
            domain elements

            'meshgrid' : vectorized evaluation on a meshgrid
            tuple of arrays

        Returns
        -------
        out : `FunctionSet.Vector`
            A function (nearest-neighbor) interpolating at a given
            point or array of points. It is vectorized according to
            the given parameter.

        Examples
        --------
        Let's define a set of functions from the unit rectangle to
        one-character strings:

        >>> from __future__ import unicode_literals, print_function
        >>> from odl import Rectangle, Strings
        >>> rect = Rectangle([0, 0], [1, 1])
        >>> strings = Strings(1)  # 1-char strings

        Initialize the space

        >>> from odl import FunctionSet
        >>> space = FunctionSet(rect, strings)

        The grid is defined by uniform sampling (`as_midp` indicates
        that the points will be cell midpoints instead of corners).

        >>> from odl import uniform_sampling, Ntuples
        >>> grid = uniform_sampling(rect, [4, 2], as_midp=True)
        >>> grid.coord_vectors
        (array([ 0.125,  0.375,  0.625,  0.875]), array([ 0.25,  0.75]))

        >>> dspace = Ntuples(grid.ntotal, dtype='U1')

        Now initialize the operator:

        >>> interp_op = NearestInterpolation(space, grid, dspace,
        ...                                  order='C')

        We test some simple values:

        >>> import numpy as np
        >>> val_arr = np.array([c for c in 'mystring'])
        >>> values = dspace.element(val_arr)
        >>> function = interp_op(values, vectorization='none')
        >>> val = function([0.3, 0.6])  # closest to index (1, 1) -> 3
        >>> print(val)
        t
        """
        def nn_novec(arg):
            """Interpolating function, no vectorization."""
            # Make a (1, 1) array
            arg = np.atleast_2d(arg)
            interp = _NearestPointwiseInterpolator(
                self.grid.coord_vectors,
                x.data.reshape(self.grid.shape, order=self.order))
            return interp(arg)[0]

        def nn_array(arg):
            """Interpolating function, array vectorization."""
            interp = _NearestPointwiseInterpolator(
                self.grid.coord_vectors,
                x.data.reshape(self.grid.shape, order=self.order))
            return interp(arg)

        def nn_mg(arg):
            """Interpolating function, meshgrid vectorization."""
            interp = _NearestMeshgridInterpolator(
                self.grid.coord_vectors,
                x.data.reshape(self.grid.shape, order=self.order))
            return interp(arg)

        if vectorization == 'none':
            func = nn_novec
        elif vectorization == 'array':
            func = nn_array
        elif vectorization == 'meshgrid':
            func = nn_mg
        else:
            raise ValueError('vectorization {!r} not understood.'
                             ''.format(vectorization))

        return self.range.element(func, vectorization=vectorization)


class LinearInterpolation(FunctionSetMapping):

    """Linear interpolation interpolation as a `LinearOperator`."""

    def __init__(self, ip_fspace, grid, dspace, order='C'):
        """Initialize a new `NearestInterpolation` instance.

        Parameters
        ----------
        fspace : `FunctionSpace`
            The undiscretized (abstract) space of functions to be
            discretized. Its field must be the same as that of data
            space. Its `domain` must be an `IntervalProd`.
        grid : `TensorGrid`
            The grid on which to evaluate. Must be contained in
            the common domain of the function set.
        dspace : `FnBase`
            Data space providing containers for the values of a
            discretized object. Its size must be equal to the
            total number of grid points. Its field must be the same
            as that of the function space.
        order : {'C', 'F'}, optional
            Ordering of the values in the flat data arrays. 'C'
            means the first grid axis varies fastest, the last most
            slowly, 'F' vice versa.
        """
        if not isinstance(ip_fspace, FunctionSpace):
            raise TypeError('function space {!r} is not a `FunctionSpace` '
                            'instance.'.format(ip_fspace))
        if not isinstance(ip_fspace.domain, IntervalProd):
            raise TypeError('function space domain {!r} is not an '
                            '`IntervalProd` instance.'.format(ip_fspace))

        super().__init__(self, 'extension', ip_fspace, grid, dspace,
                         order, linear=True)

    # TODO: Implement _apply()

    def _call(self, x):
        """The raw `call` method for out-of-place evaluation.

        Parameters
        ----------
        x : `Ntuples.Vector`
            The array of numbers to be interpolated

        Returns
        -------
        out : `FunctionSet.Vector`
            A function (nearest-neighbor) interpolating at a given
            point or array of points.

        Examples
        --------
        TODO: implement an example!
        """
        raise NotImplementedError


class _NearestPointwiseInterpolator(RegularGridInterpolator):

    """Own version of SciPy's grid interpolator by point.

    We want to support non-numerical values for nearest neighbor
    interpolation and in-place evaluation.
    """

    def __init__(self, coord_vecs, values):
        """Initialize a new instance."""

        # Provide values for some attributes
        self.method = 'nearest'
        self.bounds_error = False
        self.fill_value = None

        if not hasattr(values, 'ndim'):
            # allow reasonable duck-typed values
            values = np.asarray(values)

        if len(coord_vecs) > values.ndim:
            raise ValueError('There are {} point arrays, but `values` has {} '
                             'dimensions.'.format(len(coord_vecs),
                                                  values.ndim))

        # Cast to floating point was removed here

        for i, p in enumerate(coord_vecs):
            if not np.all(np.diff(p) > 0.):
                raise ValueError('The points in dimension {} must be strictly '
                                 'ascending'.format(i))
            if not np.asarray(p).ndim == 1:
                raise ValueError('The points in dimension {} must be '
                                 '1-dimensional'.format(i))
            if not values.shape[i] == len(p):
                raise ValueError('There are {} points and {} values in '
                                 'dimension {}'.format(len(p),
                                                       values.shape[i], i))
        self.grid = tuple([np.asarray(p) for p in coord_vecs])
        self.values = values

    def __call__(self, xi, out=None):
        """Do the interpolation.

        Modified for in-place evaluation support and without method
        choice. Evaluation points are to be given as an array with
        shape (n, dim), where n is the number of points.
        """
        ndim = len(self.grid)
        if xi.ndim != 2:
            raise ValueError('`xi` has {} axes instead of 2.'.format(xi.ndim))

        if xi.shape[1] != ndim:
            raise ValueError('`xi` has axis 1 with length {} instead '
                             'of the grid dimension {}.'.format(xi.shape[1],
                                                                ndim))
        if out is not None:
            if not isinstance(out, np.ndarray):
                raise TypeError('`out` {!r} not a `numpy.ndarray` '
                                'instance.'.format(out))
            if out.shape != (xi.shape[0],):
                raise ValueError('Output shape {} not equal to (n,), where '
                                 'n={} is the total number of evaluation '
                                 'points.'.format(out.shape, xi.shape[0]))

        xi = _ndim_coords_from_arrays(xi, ndim=ndim)
        if xi.shape[-1] != ndim:
            raise ValueError('The requested sample points xi have dimension '
                             '{}, but this _NearestInterpolator has '
                             'dimension {}.'.format(xi.shape[-1], ndim))

        indices, norm_distances = self._find_indices(xi.T)
        return self._evaluate_nearest(indices, norm_distances, out)

    def _evaluate_nearest(self, indices, norm_distances, out=None):
        """Evaluate nearest interpolation. Modified for in-place."""
        idx_res = []
        for i, yi in zip(indices, norm_distances):
            idx_res.append(np.where(yi <= .5, i, i + 1))
        if out is not None:
            out[:] = self.values[idx_res]
            return out
        else:
            return self.values[idx_res]

    def _find_indices(self, xi):
        """Modified version without out-of-bounds check."""
        # find relevant edges between which xi are situated
        indices = []
        # compute distance to lower edge in unity units
        norm_distances = []
        # iterate through dimensions
        for x, grid in zip(xi, self.grid):
            i = np.searchsorted(grid, x) - 1
            i[i < 0] = 0
            i[i > grid.size - 2] = grid.size - 2
            indices.append(i)
            norm_distances.append((x - grid[i]) /
                                  (grid[i + 1] - grid[i]))
        return indices, norm_distances


class _NearestMeshgridInterpolator(_NearestPointwiseInterpolator):

    """Own version of SciPy's grid interpolator for meshgrids.

    We want to support non-numerical values for nearest neighbor
    interpolation and in-place evaluation.
    """

    def __call__(self, xi, out=None):
        """Do the interpolation.

        Modified for in-place evaluation support and without method
        choice. Evaluation points are to be given as a list of arrays
        which can be broadcast against each other.
        """
        if len(xi) != len(self.grid):
            raise ValueError('number of vectors in `xi` is {} instead of {}, '
                             'the grid dimension.'.format(xi.shape[1],
                                                          len(self.grid)))
        ntotal = np.prod(np.broadcast(*xi).shape)
        if out is not None:
            if not isinstance(out, np.ndarray):
                raise TypeError('`out` {!r} not a `numpy.ndarray` '
                                'instance.'.format(out))
            if out.shape != (ntotal,):
                raise ValueError('Output shape {} not equal to (n,), where '
                                 'n={} is the total number of evaluation '
                                 'points.'.format(out.shape, ntotal))

        indices, norm_distances = self._find_indices(xi)
        return self._evaluate_nearest(indices, norm_distances, out)

    def _evaluate_nearest(self, indices, norm_distances, out=None):
        """Evaluate nearest interpolation.

        Modified for in-place evaluation.
        """
        idx_res = []
        for i, yi in zip(indices, norm_distances):
            idx_res.append(np.where(yi <= .5, i, i + 1))
        if out is not None:
            out[:] = self.values[idx_res]
            return out
        else:
            return self.values[idx_res]

if __name__ == '__main__':
    from doctest import testmod, NORMALIZE_WHITESPACE
    testmod(optionflags=NORMALIZE_WHITESPACE)
