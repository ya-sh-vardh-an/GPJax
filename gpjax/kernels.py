import abc
from lib2to3.pgen2.token import OP
from re import L
from typing import Callable, Dict, List, Optional, Tuple
from unicodedata import name

import jax.numpy as jnp
from chex import dataclass
from jax import vmap

from gpjax.types import Array


##########################################
# Abtract classes
##########################################
@dataclass(repr=False)
class Kernel:
    active_dims: Optional[List[int]] = None
    stationary: Optional[bool] = False
    spectral: Optional[bool] = False
    name: Optional[str] = "Kernel"
    _params: Optional[Dict] = None

    def __post_init__(self):
        self.ndims = 1 if not self.active_dims else len(self.active_dims)

    @abc.abstractmethod
    def __call__(self, x: Array, y: Array, params: dict) -> Array:
        raise NotImplementedError

    def slice_input(self, x: Array) -> Array:
        return x[..., self.active_dims]

    @property
    def ard(self):
        return True if self.ndims > 1 else False

    @property
    def params(self) -> dict:
        return self._params

    @params.setter
    def params(self, value):
        self._params = value


@dataclass
class CombinationKernel:
    kernel_set: List[Kernel]
    name: Optional[str] = "Combination kernel"
    combination_fn: Optional[Callable] = None

    @property
    def params(self) -> List[Dict]:
        return [kernel.params for kernel in self.kernel_set]

    def __call__(self, x: Array, y: Array, params: dict) -> Array:
        return self.combination_fn(jnp.stack([k(x, y, p) for k, p in zip(self.kernel_set, params)]))


@dataclass
class SumKernel(CombinationKernel):
    name: Optional[str] = "Sum kernel"
    combination_fn: Optional[Callable] = jnp.sum


@dataclass
class ProductKernel(CombinationKernel):
    name: Optional[str] = "Product kernel"
    combination_fn: Optional[Callable] = jnp.prod


##########################################
# Euclidean kernels
##########################################
@dataclass(repr=False)
class RBF(Kernel):
    name: Optional[str] = "Radial basis function kernel"

    def __post_init__(self):
        self.ndims = 1 if not self.active_dims else len(self.active_dims)
        self._params = {
            "lengthscale": jnp.array([1.0] * self.ndims),
            "variance": jnp.array([1.0]),
        }

    def __call__(self, x: jnp.DeviceArray, y: jnp.DeviceArray, params: dict) -> Array:
        x = self.slice_input(x) / params["lengthscale"]
        y = self.slice_input(y) / params["lengthscale"]
        K = params["variance"] * jnp.exp(-0.5 * squared_distance(x, y))
        return K.squeeze()


@dataclass(repr=False)
class Matern12(Kernel):
    name: Optional[str] = "Matern 1/2"

    def __post_init__(self):
        self.ndims = 1 if not self.active_dims else len(self.active_dims)
        self._params = {
            "lengthscale": jnp.array([1.0] * self.ndims),
            "variance": jnp.array([1.0]),
        }

    def __call__(self, x: jnp.DeviceArray, y: jnp.DeviceArray, params: dict) -> Array:
        x = self.slice_input(x) / params["lengthscale"]
        y = self.slice_input(y) / params["lengthscale"]
        K = params["variance"] * jnp.exp(-0.5 * euclidean_distance(x, y))
        return K.squeeze()


@dataclass(repr=False)
class Matern32(Kernel):
    name: Optional[str] = "Matern 3/2"

    def __post_init__(self):
        self.ndims = 1 if not self.active_dims else len(self.active_dims)
        self._params = {
            "lengthscale": jnp.array([1.0] * self.ndims),
            "variance": jnp.array([1.0]),
        }

    def __call__(self, x: jnp.DeviceArray, y: jnp.DeviceArray, params: dict) -> Array:
        x = self.slice_input(x) / params["lengthscale"]
        y = self.slice_input(y) / params["lengthscale"]
        tau = euclidean_distance(x, y)
        K = params["variance"] * (1.0 + jnp.sqrt(3.0) * tau) * jnp.exp(-jnp.sqrt(3.0) * tau)
        return K.squeeze()


@dataclass(repr=False)
class Matern52(Kernel):
    name: Optional[str] = "Matern 5/2"

    def __post_init__(self):
        self.ndims = 1 if not self.active_dims else len(self.active_dims)
        self._params = {
            "lengthscale": jnp.array([1.0] * self.ndims),
            "variance": jnp.array([1.0]),
        }

    def __call__(self, x: jnp.DeviceArray, y: jnp.DeviceArray, params: dict) -> Array:
        x = self.slice_input(x) / params["lengthscale"]
        y = self.slice_input(y) / params["lengthscale"]
        tau = euclidean_distance(x, y)
        K = (
            params["variance"]
            * (1.0 + jnp.sqrt(5.0) * tau + 5.0 / 3.0 * jnp.square(tau))
            * jnp.exp(-jnp.sqrt(5.0) * tau)
        )
        return K.squeeze()


@dataclass(repr=False)
class Polynomial(Kernel):
    name: Optional[str] = "Polynomial"
    degree: int = 1

    def __post_init__(self):
        self.ndims = 1 if not self.active_dims else len(self.active_dims)
        self._params = {
            "shift": jnp.array([1.0]),
            "variance": jnp.array([1.0] * self.ndims),
        }
        self.name = f"Polynomial Degree: {self.degree}"

    def __call__(self, x: jnp.DeviceArray, y: jnp.DeviceArray, params: dict) -> Array:
        x = self.slice_input(x).squeeze()
        y = self.slice_input(y).squeeze()
        K = jnp.power(params["shift"] + jnp.dot(x * params["variance"], y), self.degree)
        return K.squeeze()


##########################################
# Graph kernels
##########################################
@dataclass
class _EigenKernel:
    laplacian: Array


@dataclass
class GraphKernel(Kernel, _EigenKernel):
    name: Optional[str] = "Graph kernel"

    def __post_init__(self):
        self.ndims = 1
        self._params = {
            "lengthscale": jnp.array([1.0] * self.ndims),
            "variance": jnp.array([1.0]),
            "smoothness": jnp.array([1.0]),
        }
        evals, self.evecs = jnp.linalg.eigh(self.laplacian)
        self.evals = evals.reshape(-1, 1)
        self.num_vertex = self.laplacian.shape[0]

    def __call__(self, x: jnp.DeviceArray, y: jnp.DeviceArray, params: dict) -> Array:
        """Evaluate the graph kernel on a pair of vertices v_i, v_j.

        Args:
            x (jnp.DeviceArray): Index of the ith vertex
            y (jnp.DeviceArray): Index of the jth vertex
            params (dict): Parameter set for which the kernel should be evaluated on.

        Returns:
            Array: The value of k(v_i, v_j).
        """
        psi = jnp.power(
            2 * params["smoothness"] / params["lengthscale"] ** 2 + self.evals,
            -params["smoothness"],
        )
        psi *= self.num_vertex / jnp.sum(psi)
        x_evec = self.evecs[:, x]
        y_evec = self.evecs[:, y]
        kxy = params["variance"] * jnp.sum(
            jnp.prod(jnp.stack([psi, x_evec, y_evec]).squeeze(), axis=0)
        )
        return kxy.squeeze()


def squared_distance(x: Array, y: Array):
    return jnp.sum((x - y) ** 2)


def euclidean_distance(x: Array, y: Array):
    return jnp.sum(jnp.abs(x - y))


def gram(kernel: Kernel, inputs: Array, params: dict) -> Array:
    return vmap(lambda x1: vmap(lambda y1: kernel(x1, y1, params))(inputs))(inputs)


def cross_covariance(kernel: Kernel, x: Array, y: Array, params: dict) -> Array:
    return vmap(lambda x1: vmap(lambda y1: kernel(x1, y1, params))(x))(y)