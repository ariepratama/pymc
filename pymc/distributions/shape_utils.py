#   Copyright 2021 The PyMC Developers
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

# -*- coding: utf-8 -*-
"""
A collection of common shape operations needed for broadcasting
samples from probability distributions for stochastic nodes in PyMC.
"""

import warnings

from typing import Optional, Sequence, Tuple, Union

import numpy as np

from aesara.graph.basic import Variable
from aesara.tensor.var import TensorVariable

from pymc.aesaraf import change_rv_size, pandas_to_array
from pymc.exceptions import ShapeError, ShapeWarning

__all__ = [
    "to_tuple",
    "shapes_broadcasting",
    "broadcast_dist_samples_shape",
    "get_broadcastable_dist_samples",
    "broadcast_distribution_samples",
    "broadcast_dist_samples_to",
]


def to_tuple(shape):
    """Convert ints, arrays, and Nones to tuples

    Parameters
    ----------
    shape: None, int or array-like
        Represents the shape to convert to tuple.

    Returns
    -------
    If `shape` is None, returns an empty tuple. If it's an int, (shape,) is
    returned. If it is array-like, tuple(shape) is returned.
    """
    if shape is None:
        return tuple()
    temp = np.atleast_1d(shape)
    if temp.size == 0:
        return tuple()
    else:
        return tuple(temp)


def _check_shape_type(shape):
    out = []
    try:
        shape = np.atleast_1d(shape)
        for s in shape:
            if isinstance(s, np.ndarray) and s.ndim > 0:
                raise TypeError(f"Value {s} is not a valid integer")
            o = int(s)
            if o != s:
                raise TypeError(f"Value {s} is not a valid integer")
            out.append(o)
    except Exception:
        raise TypeError(f"Supplied value {shape} does not represent a valid shape")
    return tuple(out)


def shapes_broadcasting(*args, raise_exception=False):
    """Return the shape resulting from broadcasting multiple shapes.
    Represents numpy's broadcasting rules.

    Parameters
    ----------
    *args: array-like of int
        Tuples or arrays or lists representing the shapes of arrays to be
        broadcast.
    raise_exception: bool (optional)
        Controls whether to raise an exception or simply return `None` if
        the broadcasting fails.

    Returns
    -------
    Resulting shape. If broadcasting is not possible and `raise_exception` is
    False, then `None` is returned. If `raise_exception` is `True`, a
    `ValueError` is raised.
    """
    x = list(_check_shape_type(args[0])) if args else ()
    for arg in args[1:]:
        y = list(_check_shape_type(arg))
        if len(x) < len(y):
            x, y = y, x
        if len(y) > 0:
            x[-len(y) :] = [
                j if i == 1 else i if j == 1 else i if i == j else 0
                for i, j in zip(x[-len(y) :], y)
            ]
        if not all(x):
            if raise_exception:
                raise ValueError(
                    "Supplied shapes {} do not broadcast together".format(
                        ", ".join([f"{a}" for a in args])
                    )
                )
            else:
                return None
    return tuple(x)


def broadcast_dist_samples_shape(shapes, size=None):
    """Apply shape broadcasting to shape tuples but assuming that the shapes
    correspond to draws from random variables, with the `size` tuple possibly
    prepended to it. The `size` prepend is ignored to consider if the supplied
    `shapes` can broadcast or not. It is prepended to the resulting broadcasted
    `shapes`, if any of the shape tuples had the `size` prepend.

    Parameters
    ----------
    shapes: Iterable of tuples holding the distribution samples shapes
    size: None, int or tuple (optional)
        size of the sample set requested.

    Returns
    -------
    tuple of the resulting shape

    Examples
    --------
    .. code-block:: python

        size = 100
        shape0 = (size,)
        shape1 = (size, 5)
        shape2 = (size, 4, 5)
        out = broadcast_dist_samples_shape([shape0, shape1, shape2],
                                           size=size)
        assert out == (size, 4, 5)

    .. code-block:: python

        size = 100
        shape0 = (size,)
        shape1 = (5,)
        shape2 = (4, 5)
        out = broadcast_dist_samples_shape([shape0, shape1, shape2],
                                           size=size)
        assert out == (size, 4, 5)

    .. code-block:: python

        size = 100
        shape0 = (1,)
        shape1 = (5,)
        shape2 = (4, 5)
        out = broadcast_dist_samples_shape([shape0, shape1, shape2],
                                           size=size)
        assert out == (4, 5)
    """
    if size is None:
        broadcasted_shape = shapes_broadcasting(*shapes)
        if broadcasted_shape is None:
            raise ValueError(
                "Cannot broadcast provided shapes {} given size: {}".format(
                    ", ".join([f"{s}" for s in shapes]), size
                )
            )
        return broadcasted_shape
    shapes = [_check_shape_type(s) for s in shapes]
    _size = to_tuple(size)
    # samples shapes without the size prepend
    sp_shapes = [s[len(_size) :] if _size == s[: min([len(_size), len(s)])] else s for s in shapes]
    try:
        broadcast_shape = shapes_broadcasting(*sp_shapes, raise_exception=True)
    except ValueError:
        raise ValueError(
            "Cannot broadcast provided shapes {} given size: {}".format(
                ", ".join([f"{s}" for s in shapes]), size
            )
        )
    broadcastable_shapes = []
    for shape, sp_shape in zip(shapes, sp_shapes):
        if _size == shape[: len(_size)]:
            # If size prepends the shape, then we have to add broadcasting axis
            # in the middle
            p_shape = (
                shape[: len(_size)]
                + (1,) * (len(broadcast_shape) - len(sp_shape))
                + shape[len(_size) :]
            )
        else:
            p_shape = shape
        broadcastable_shapes.append(p_shape)
    return shapes_broadcasting(*broadcastable_shapes, raise_exception=True)


def get_broadcastable_dist_samples(
    samples, size=None, must_bcast_with=None, return_out_shape=False
):
    """Get a view of the samples drawn from distributions which adds new axises
    in between the `size` prepend and the distribution's `shape`. These views
    should be able to broadcast the samples from the distrubtions taking into
    account the `size` (i.e. the number of samples) of the draw, which is
    prepended to the sample's `shape`. Optionally, one can supply an extra
    `must_bcast_with` to try to force samples to be able to broadcast with a
    given shape. A `ValueError` is raised if it is not possible to broadcast
    the provided samples.

    Parameters
    ----------
    samples: Iterable of ndarrays holding the sampled values
    size: None, int or tuple (optional)
        size of the sample set requested.
    must_bcast_with: None, int or tuple (optional)
        Tuple shape to which the samples must be able to broadcast
    return_out_shape: bool (optional)
        If `True`, this function also returns the output's shape and not only
        samples views.

    Returns
    -------
    broadcastable_samples: List of the broadcasted sample arrays
    broadcast_shape: If `return_out_shape` is `True`, the resulting broadcast
        shape is returned.

    Examples
    --------
    .. code-block:: python

        must_bcast_with = (3, 1, 5)
        size = 100
        sample0 = np.random.randn(size)
        sample1 = np.random.randn(size, 5)
        sample2 = np.random.randn(size, 4, 5)
        out = broadcast_dist_samples_to(
            [sample0, sample1, sample2],
            size=size,
            must_bcast_with=must_bcast_with,
        )
        assert out[0].shape == (size, 1, 1, 1)
        assert out[1].shape == (size, 1, 1, 5)
        assert out[2].shape == (size, 1, 4, 5)
        assert np.all(sample0[:, None, None, None] == out[0])
        assert np.all(sample1[:, None, None] == out[1])
        assert np.all(sample2[:, None] == out[2])

    .. code-block:: python

        size = 100
        must_bcast_with = (3, 1, 5)
        sample0 = np.random.randn(size)
        sample1 = np.random.randn(5)
        sample2 = np.random.randn(4, 5)
        out = broadcast_dist_samples_to(
            [sample0, sample1, sample2],
            size=size,
            must_bcast_with=must_bcast_with,
        )
        assert out[0].shape == (size, 1, 1, 1)
        assert out[1].shape == (5,)
        assert out[2].shape == (4, 5)
        assert np.all(sample0[:, None, None, None] == out[0])
        assert np.all(sample1 == out[1])
        assert np.all(sample2 == out[2])
    """
    samples = [np.asarray(p) for p in samples]
    _size = to_tuple(size)
    must_bcast_with = to_tuple(must_bcast_with)
    # Raw samples shapes
    p_shapes = [p.shape for p in samples] + [_check_shape_type(must_bcast_with)]
    out_shape = broadcast_dist_samples_shape(p_shapes, size=size)
    # samples shapes without the size prepend
    sp_shapes = [
        s[len(_size) :] if _size == s[: min([len(_size), len(s)])] else s for s in p_shapes
    ]
    broadcast_shape = shapes_broadcasting(*sp_shapes, raise_exception=True)
    broadcastable_samples = []
    for param, p_shape, sp_shape in zip(samples, p_shapes, sp_shapes):
        if _size == p_shape[: min([len(_size), len(p_shape)])]:
            # If size prepends the shape, then we have to add broadcasting axis
            # in the middle
            slicer_head = [slice(None)] * len(_size)
            slicer_tail = [np.newaxis] * (len(broadcast_shape) - len(sp_shape)) + [
                slice(None)
            ] * len(sp_shape)
        else:
            # If size does not prepend the shape, then we have leave the
            # parameter as is
            slicer_head = []
            slicer_tail = [slice(None)] * len(sp_shape)
        broadcastable_samples.append(param[tuple(slicer_head + slicer_tail)])
    if return_out_shape:
        return broadcastable_samples, out_shape
    else:
        return broadcastable_samples


def broadcast_distribution_samples(samples, size=None):
    """Broadcast samples drawn from distributions taking into account the
    size (i.e. the number of samples) of the draw, which is prepended to
    the sample's shape.

    Parameters
    ----------
    samples: Iterable of ndarrays holding the sampled values
    size: None, int or tuple (optional)
        size of the sample set requested.

    Returns
    -------
    List of broadcasted sample arrays

    Examples
    --------
    .. code-block:: python

        size = 100
        sample0 = np.random.randn(size)
        sample1 = np.random.randn(size, 5)
        sample2 = np.random.randn(size, 4, 5)
        out = broadcast_distribution_samples([sample0, sample1, sample2],
                                             size=size)
        assert all((o.shape == (size, 4, 5) for o in out))
        assert np.all(sample0[:, None, None] == out[0])
        assert np.all(sample1[:, None, :] == out[1])
        assert np.all(sample2 == out[2])

    .. code-block:: python

        size = 100
        sample0 = np.random.randn(size)
        sample1 = np.random.randn(5)
        sample2 = np.random.randn(4, 5)
        out = broadcast_distribution_samples([sample0, sample1, sample2],
                                             size=size)
        assert all((o.shape == (size, 4, 5) for o in out))
        assert np.all(sample0[:, None, None] == out[0])
        assert np.all(sample1 == out[1])
        assert np.all(sample2 == out[2])
    """
    return np.broadcast_arrays(*get_broadcastable_dist_samples(samples, size=size))


def broadcast_dist_samples_to(to_shape, samples, size=None):
    """Broadcast samples drawn from distributions to a given shape, taking into
    account the size (i.e. the number of samples) of the draw, which is
    prepended to the sample's shape.

    Parameters
    ----------
    to_shape: Tuple shape onto which the samples must be able to broadcast
    samples: Iterable of ndarrays holding the sampled values
    size: None, int or tuple (optional)
        size of the sample set requested.

    Returns
    -------
    List of the broadcasted sample arrays

    Examples
    --------
    .. code-block:: python

        to_shape = (3, 1, 5)
        size = 100
        sample0 = np.random.randn(size)
        sample1 = np.random.randn(size, 5)
        sample2 = np.random.randn(size, 4, 5)
        out = broadcast_dist_samples_to(
            to_shape,
            [sample0, sample1, sample2],
            size=size
        )
        assert np.all((o.shape == (size, 3, 4, 5) for o in out))
        assert np.all(sample0[:, None, None, None] == out[0])
        assert np.all(sample1[:, None, None] == out[1])
        assert np.all(sample2[:, None] == out[2])

    .. code-block:: python

        size = 100
        to_shape = (3, 1, 5)
        sample0 = np.random.randn(size)
        sample1 = np.random.randn(5)
        sample2 = np.random.randn(4, 5)
        out = broadcast_dist_samples_to(
            to_shape,
            [sample0, sample1, sample2],
            size=size
        )
        assert np.all((o.shape == (size, 3, 4, 5) for o in out))
        assert np.all(sample0[:, None, None, None] == out[0])
        assert np.all(sample1 == out[1])
        assert np.all(sample2 == out[2])
    """
    samples, to_shape = get_broadcastable_dist_samples(
        samples, size=size, must_bcast_with=to_shape, return_out_shape=True
    )
    return [np.broadcast_to(o, to_shape) for o in samples]


# User-provided can be lazily specified as scalars
Shape = Union[int, TensorVariable, Sequence[Union[int, TensorVariable, type(Ellipsis)]]]
Dims = Union[str, Sequence[Union[str, None, type(Ellipsis)]]]
Size = Union[int, TensorVariable, Sequence[Union[int, TensorVariable]]]

# After conversion to vectors
WeakShape = Union[TensorVariable, Tuple[Union[int, TensorVariable, type(Ellipsis)], ...]]
WeakDims = Tuple[Union[str, None, type(Ellipsis)], ...]

# After Ellipsis were substituted
StrongShape = Union[TensorVariable, Tuple[Union[int, TensorVariable], ...]]
StrongDims = Sequence[Union[str, None]]
StrongSize = Union[TensorVariable, Tuple[Union[int, TensorVariable], ...]]


def convert_dims(dims: Dims) -> Optional[WeakDims]:
    """Process a user-provided dims variable into None or a valid dims tuple."""
    if dims is None:
        return None

    if isinstance(dims, str):
        dims = (dims,)
    elif isinstance(dims, (list, tuple)):
        dims = tuple(dims)
    else:
        raise ValueError(f"The `dims` parameter must be a tuple, str or list. Actual: {type(dims)}")

    if any(d == Ellipsis for d in dims[:-1]):
        raise ValueError(f"Ellipsis in `dims` may only appear in the last position. Actual: {dims}")

    return dims


def convert_shape(shape: Shape) -> Optional[WeakShape]:
    """Process a user-provided shape variable into None or a valid shape object."""
    if shape is None:
        return None

    if isinstance(shape, int) or (isinstance(shape, TensorVariable) and shape.ndim == 0):
        shape = (shape,)
    elif isinstance(shape, (list, tuple)):
        shape = tuple(shape)
    else:
        raise ValueError(
            f"The `shape` parameter must be a tuple, TensorVariable, int or list. Actual: {type(shape)}"
        )

    if isinstance(shape, tuple) and any(s == Ellipsis for s in shape[:-1]):
        raise ValueError(
            f"Ellipsis in `shape` may only appear in the last position. Actual: {shape}"
        )

    return shape


def convert_size(size: Size) -> Optional[StrongSize]:
    """Process a user-provided size variable into None or a valid size object."""
    if size is None:
        return None

    if isinstance(size, int) or (isinstance(size, TensorVariable) and size.ndim == 0):
        size = (size,)
    elif isinstance(size, (list, tuple)):
        size = tuple(size)
    else:
        raise ValueError(
            f"The `size` parameter must be a tuple, TensorVariable, int or list. Actual: {type(size)}"
        )

    if isinstance(size, tuple) and Ellipsis in size:
        raise ValueError(f"The `size` parameter cannot contain an Ellipsis. Actual: {size}")

    return size


def resize_from_dims(
    dims: WeakDims, ndim_implied: int, model
) -> Tuple[int, StrongSize, StrongDims]:
    """Determines a potential resize shape from a `dims` tuple.

    Parameters
    ----------
    dims : array-like
        A vector of dimension names, None or Ellipsis.
    ndim_implied : int
        Number of RV dimensions that were implied from its inputs alone.
    model : pm.Model
        The current model on stack.

    Returns
    -------
    ndim_resize : int
        Number of dimensions that should be added through resizing.
    resize_shape : array-like
        The shape of the new dimensions.
    """
    if Ellipsis in dims:
        # Auto-complete the dims tuple to the full length.
        # We don't have a way to know the names of implied
        # dimensions, so they will be `None`.
        dims = (*dims[:-1], *[None] * ndim_implied)

    ndim_resize = len(dims) - ndim_implied

    # All resize dims must be known already (numerically or symbolically).
    unknowndim_resize_dims = set(dims[:ndim_resize]) - set(model.dim_lengths)
    if unknowndim_resize_dims:
        raise KeyError(
            f"Dimensions {unknowndim_resize_dims} are unknown to the model and cannot be used to specify a `size`."
        )

    # The numeric/symbolic resize tuple can be created using model.RV_dim_lengths
    resize_shape = tuple(model.dim_lengths[dname] for dname in dims[:ndim_resize])
    return ndim_resize, resize_shape, dims


def resize_from_observed(
    observed, ndim_implied: int
) -> Tuple[int, StrongSize, Union[np.ndarray, Variable]]:
    """Determines a potential resize shape from observations.

    Parameters
    ----------
    observed : scalar, array-like
        The value of the `observed` kwarg to the RV creation.
    ndim_implied : int
        Number of RV dimensions that were implied from its inputs alone.

    Returns
    -------
    ndim_resize : int
        Number of dimensions that should be added through resizing.
    resize_shape : array-like
        The shape of the new dimensions.
    observed : scalar, array-like
        Observations as numpy array or `Variable`.
    """
    if not hasattr(observed, "shape"):
        observed = pandas_to_array(observed)
    ndim_resize = observed.ndim - ndim_implied
    resize_shape = tuple(observed.shape[d] for d in range(ndim_resize))
    return ndim_resize, resize_shape, observed


def find_size(shape=None, size=None, ndim_supp=None):
    """Determines the size keyword argument for creating a Distribution.

    Parameters
    ----------
    shape : tuple
        A tuple specifying the final shape of a distribution
    size : tuple
        A tuple specifying the size of a distribution
    ndim_supp : int
        The support dimension of the distribution.
        0 if a univariate distribution, 1 if a multivariate distribution.

    Returns
    -------
    create_size : int
        The size argument to be passed to the distribution
    ndim_expected : int
        Number of dimensions expected after distribution was created
    ndim_batch : int
        Number of batch dimensions
    ndim_supp : int
        Number of support dimensions
    """

    ndim_expected = None
    ndim_batch = None
    create_size = None

    if shape is not None:
        if Ellipsis in shape:
            # Ellipsis short-hands all implied dimensions. Therefore
            # we don't know how many dimensions to expect.
            ndim_expected = ndim_batch = None
            # Create the RV with its implied shape and resize later
            create_size = None
        else:
            ndim_expected = len(tuple(shape))
            ndim_batch = ndim_expected - ndim_supp
            create_size = tuple(shape)[:ndim_batch]
    elif size is not None:
        ndim_expected = ndim_supp + len(tuple(size))
        ndim_batch = ndim_expected - ndim_supp
        create_size = size

    return create_size, ndim_expected, ndim_batch, ndim_supp


def maybe_resize(
    rv_out,
    rv_op,
    dist_params,
    ndim_expected,
    ndim_batch,
    ndim_supp,
    shape,
    size,
    **kwargs,
):
    """Resize a distribution if necessary.

    Parameters
    ----------
    rv_out : RandomVariable
        The RandomVariable to be resized if necessary
    rv_op : RandomVariable.__class__
        The RandomVariable class to recreate it
    dist_params : dict
        Input parameters to recreate the RandomVariable
    ndim_expected : int
        Number of dimensions expected after distribution was created
    ndim_batch : int
        Number of batch dimensions
    ndim_supp : int
        The support dimension of the distribution.
        0 if a univariate distribution, 1 if a multivariate distribution.
    shape : tuple
        A tuple specifying the final shape of a distribution
    size : tuple
        A tuple specifying the size of a distribution

    Returns
    -------
    rv_out : int
        The size argument to be passed to the distribution
    """
    ndim_actual = rv_out.ndim
    ndims_unexpected = ndim_actual != ndim_expected

    if shape is not None and ndims_unexpected:
        if Ellipsis in shape:
            # Resize and we're done!
            rv_out = change_rv_size(rv_var=rv_out, new_size=shape[:-1], expand=True)
        else:
            # This is rare, but happens, for example, with MvNormal(np.ones((2, 3)), np.eye(3), shape=(2, 3)).
            # Recreate the RV without passing `size` to created it with just the implied dimensions.
            rv_out = rv_op(*dist_params, size=None, **kwargs)

            # Now resize by any remaining "extra" dimensions that were not implied from support and parameters
            if rv_out.ndim < ndim_expected:
                expand_shape = shape[: ndim_expected - rv_out.ndim]
                rv_out = change_rv_size(rv_var=rv_out, new_size=expand_shape, expand=True)
            if not rv_out.ndim == ndim_expected:
                raise ShapeError(
                    f"Failed to create the RV with the expected dimensionality. "
                    f"This indicates a severe problem. Please open an issue.",
                    actual=ndim_actual,
                    expected=ndim_batch + ndim_supp,
                )

    # Warn about the edge cases where the RV Op creates more dimensions than
    # it should based on `size` and `RVOp.ndim_supp`.
    if size is not None and ndims_unexpected:
        warnings.warn(
            f"You may have expected a ({len(tuple(size))}+{ndim_supp})-dimensional RV, but the resulting RV will be {ndim_actual}-dimensional."
            ' To silence this warning use `warnings.simplefilter("ignore", pm.ShapeWarning)`.',
            ShapeWarning,
        )

    return rv_out
