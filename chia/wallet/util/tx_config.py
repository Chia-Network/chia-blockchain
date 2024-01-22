from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional, Type, TypeVar

from typing_extensions import NotRequired, TypedDict, Unpack

from chia.consensus.constants import ConsensusConstants
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable


@dataclasses.dataclass(frozen=True)
class CoinSelectionConfig:
    min_coin_amount: uint64
    max_coin_amount: uint64
    excluded_coin_amounts: List[uint64]
    excluded_coin_ids: List[bytes32]

    def to_json_dict(self) -> Dict[str, Any]:
        return CoinSelectionConfigLoader(
            self.min_coin_amount,
            self.max_coin_amount,
            self.excluded_coin_amounts,
            self.excluded_coin_ids,
        ).to_json_dict()

    # This function is purely for ergonomics
    def override(self, **kwargs: Any) -> CoinSelectionConfig:
        return dataclasses.replace(self, **kwargs)


@dataclasses.dataclass(frozen=True)
class TXConfig(CoinSelectionConfig):
    reuse_puzhash: bool

    @property
    def coin_selection_config(self) -> CoinSelectionConfig:
        return CoinSelectionConfig(
            self.min_coin_amount,
            self.max_coin_amount,
            self.excluded_coin_amounts,
            self.excluded_coin_ids,
        )

    def to_json_dict(self) -> Dict[str, Any]:
        return TXConfigLoader(
            self.min_coin_amount,
            self.max_coin_amount,
            self.excluded_coin_amounts,
            self.excluded_coin_ids,
            self.reuse_puzhash,
        ).to_json_dict()

    # This function is purely for ergonomics
    def override(self, **kwargs: Any) -> TXConfig:
        return dataclasses.replace(self, **kwargs)


class AutofillArgs(TypedDict):
    constants: ConsensusConstants
    config: NotRequired[Dict[str, Any]]
    logged_in_fingerprint: NotRequired[int]


_T_CoinSelectionConfigLoader = TypeVar("_T_CoinSelectionConfigLoader", bound="CoinSelectionConfigLoader")


@streamable
@dataclasses.dataclass(frozen=True)
class CoinSelectionConfigLoader(Streamable):
    min_coin_amount: Optional[uint64] = None
    max_coin_amount: Optional[uint64] = None
    excluded_coin_amounts: Optional[List[uint64]] = None
    excluded_coin_ids: Optional[List[bytes32]] = None

    def autofill(
        self,
        **kwargs: Unpack[AutofillArgs],
    ) -> CoinSelectionConfig:
        constants: ConsensusConstants = kwargs["constants"]
        return CoinSelectionConfig(
            min_coin_amount=uint64(0) if self.min_coin_amount is None else self.min_coin_amount,
            max_coin_amount=uint64(constants.MAX_COIN_AMOUNT) if self.max_coin_amount is None else self.max_coin_amount,
            excluded_coin_amounts=[] if self.excluded_coin_amounts is None else self.excluded_coin_amounts,
            excluded_coin_ids=[] if self.excluded_coin_ids is None else self.excluded_coin_ids,
        )

    @classmethod
    def from_json_dict(
        cls: Type[_T_CoinSelectionConfigLoader], json_dict: Dict[str, Any]
    ) -> _T_CoinSelectionConfigLoader:
        if "excluded_coins" in json_dict:
            excluded_coins: List[Coin] = [Coin.from_json_dict(c) for c in json_dict["excluded_coins"]]
            excluded_coin_ids: List[str] = [c.name().hex() for c in excluded_coins]
            if "excluded_coin_ids" in json_dict:
                json_dict["excluded_coin_ids"] = [*excluded_coin_ids, *json_dict["excluded_coin_ids"]]
            else:
                json_dict["excluded_coin_ids"] = excluded_coin_ids
        return super().from_json_dict(json_dict)

    # This function is purely for ergonomics
    def override(self, **kwargs: Any) -> CoinSelectionConfigLoader:
        return dataclasses.replace(self, **kwargs)


@streamable
@dataclasses.dataclass(frozen=True)
class TXConfigLoader(CoinSelectionConfigLoader):
    reuse_puzhash: Optional[bool] = None

    def autofill(
        self,
        **kwargs: Unpack[AutofillArgs],
    ) -> TXConfig:
        constants: ConsensusConstants = kwargs["constants"]
        if self.reuse_puzhash is None:
            config: Dict[str, Any] = kwargs.get("config", {})
            logged_in_fingerprint: int = kwargs.get("logged_in_fingerprint", -1)
            reuse_puzhash_config = config.get("reuse_public_key_for_change", None)
            if reuse_puzhash_config is None:
                reuse_puzhash = False
            else:
                reuse_puzhash = reuse_puzhash_config.get(str(logged_in_fingerprint), False)
        else:
            reuse_puzhash = self.reuse_puzhash

        autofilled_cs_config = CoinSelectionConfigLoader(
            self.min_coin_amount,
            self.max_coin_amount,
            self.excluded_coin_amounts,
            self.excluded_coin_ids,
        ).autofill(constants=constants)

        return TXConfig(
            autofilled_cs_config.min_coin_amount,
            autofilled_cs_config.max_coin_amount,
            autofilled_cs_config.excluded_coin_amounts,
            autofilled_cs_config.excluded_coin_ids,
            reuse_puzhash,
        )

    # This function is purely for ergonomics
    def override(self, **kwargs: Any) -> TXConfigLoader:
        return dataclasses.replace(self, **kwargs)


DEFAULT_COIN_SELECTION_CONFIG = CoinSelectionConfig(uint64(0), uint64(DEFAULT_CONSTANTS.MAX_COIN_AMOUNT), [], [])
DEFAULT_TX_CONFIG = TXConfig(
    DEFAULT_COIN_SELECTION_CONFIG.min_coin_amount,
    DEFAULT_COIN_SELECTION_CONFIG.max_coin_amount,
    DEFAULT_COIN_SELECTION_CONFIG.excluded_coin_amounts,
    DEFAULT_COIN_SELECTION_CONFIG.excluded_coin_ids,
    False,
)
