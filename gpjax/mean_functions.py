from typing import Optional

import jax.numpy as jnp
from chex import dataclass
from multipledispatch import dispatch

from .types import Array


@dataclass
class MeanFunction:
    name: Optional[str] = "Mean Function"

    def __call__(self, x: Array) -> Array:
        raise NotImplementedError


@dataclass
class Zero(MeanFunction):
    name: Optional[str] = "Zero mean"

    def __call__(self, x: Array) -> Array:
        return jnp.zeros_like(x)


@dispatch(Zero)
def initialise(meanf: Zero) -> dict:
    return {}
