from __future__ import annotations

from typing import Protocol, TypeVar

from chia.util.observation_root import ObservationRoot

_T_ObservationRoot = TypeVar("_T_ObservationRoot", bound=ObservationRoot, covariant=True)


class SecretInfo(Protocol[_T_ObservationRoot]):
    def public_key(self) -> _T_ObservationRoot: ...
    def derive_hardened(self: _T_SecretInfo, index: int) -> _T_SecretInfo: ...
    def derive_unhardened(self: _T_SecretInfo, index: int) -> _T_SecretInfo: ...


_T_SecretInfo = TypeVar("_T_SecretInfo", bound=SecretInfo[ObservationRoot])
