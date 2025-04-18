from __future__ import annotations

import dataclasses
from collections.abc import MutableMapping
from typing import Any, Generic, Optional, TypeVar

# TODO: is it a problem to not handle aliases and anchors that maybe 'attempt' to
#       reference across the layers?


class LayeredDictKeyError(KeyError):
    pass


K = TypeVar("K")
V = TypeVar("V", bound=Any)


@dataclasses.dataclass
# NOTE: the generic is presently mostly unused but reduces the code change to switch from dict
class LayeredDict(Generic[K, V]):
    """A dictionary composed of one or more dicts allowing any to provide a value
    when requested.
    """

    dicts: list[MutableMapping[K, V]]
    # TODO: is this still not used?
    path: list[K]
    # provides: bool

    # TODO: implement
    # def __contains__(self, item) -> bool:

    # TODO: implement
    # def update(self: Self, .......) -> Self:

    def __getitem__(self, key: K) -> Any:
        # candidates = []
        # for d in self.dicts:
        #     provides = False
        #     if isinstance(d, (dict, LayeredDict)):
        #         provides = key in d
        #     candidates.append(LayeredDict())
        candidates = [d[key] for d in self.dicts if key in d]
        if len(candidates) == 0:
            raise LayeredDictKeyError(key)

        # TODO: maybe just fail if the types (dict or not) are not consistent?
        maybe = candidates[0]
        if isinstance(maybe, dict):
            return LayeredDict(
                dicts=[candidate for candidate in candidates if isinstance(candidate, dict)],
                path=[*self.path, key],
            )

        return maybe

    def get(self, key: K, default: Optional[V] = None) -> Any:
        try:
            return self[key]
        except LayeredDictKeyError:
            return default

    def setdefault(self, key: K, default: V) -> Any:
        try:
            value = self[key]
        except LayeredDictKeyError:
            self[key] = default
            value = default

        return value

    def __setitem__(self, key: K, value: V) -> None:
        self.dicts[0][key] = value
