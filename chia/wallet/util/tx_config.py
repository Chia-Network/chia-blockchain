from __future__ import annotations

import dataclasses
from typing import Any

from chia_rs import ConsensusConstants
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64
from typing_extensions import NotRequired, Self, TypedDict, Unpack

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.util.streamable import Streamable, streamable


@dataclasses.dataclass(frozen=True)
class CoinSelectionConfig:
    min_coin_amount: uint64
    max_coin_amount: uint64
    excluded_coin_amounts: list[uint64]
    excluded_coin_ids: list[bytes32]
    included_coin_ids: list[bytes32]
    primary_coin: bytes32 | None

    def __post_init__(self) -> None:
        if set(self.included_coin_ids).intersection(self.excluded_coin_ids):
            raise ValueError("`included_coin_ids` and `excluded_coin_ids` must be disjoint")
        if self.primary_coin is not None and self.primary_coin in self.excluded_coin_ids:
            raise ValueError("`primary_coin` is also specified in `excluded_coin_ids`")

    def to_json_dict(self) -> dict[str, Any]:
        return CoinSelectionConfigLoader(
            self.min_coin_amount,
            self.max_coin_amount,
            self.excluded_coin_amounts,
            self.excluded_coin_ids,
            self.included_coin_ids,
            self.primary_coin,
        ).to_json_dict()

    # This function is purely for ergonomics
    def override(self, **kwargs: Any) -> CoinSelectionConfig:
        return dataclasses.replace(self, **kwargs)

    def filter_coins(self, coins: set[Coin]) -> set[Coin]:
        filtered_set = {
            coin
            for coin in coins
            if self.min_coin_amount <= coin.amount <= self.max_coin_amount
            and coin.amount not in self.excluded_coin_amounts
            and coin.name() not in self.excluded_coin_ids
        }
        if not set(*self.included_coin_ids, *([] if self.primary_coin is None else [self.primary_coin])).issubset(
            {coin.name() for coin in filtered_set}
        ):
            raise ValueError("Some coin selection restrictions eliminated coins specified for inclusion")
        return filtered_set


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
            self.included_coin_ids,
            self.primary_coin,
        )

    def to_json_dict(self) -> dict[str, Any]:
        return TXConfigLoader(
            self.min_coin_amount,
            self.max_coin_amount,
            self.excluded_coin_amounts,
            self.excluded_coin_ids,
            self.included_coin_ids,
            self.primary_coin,
            self.reuse_puzhash,
        ).to_json_dict()

    # This function is purely for ergonomics
    def override(self, **kwargs: Any) -> TXConfig:
        return dataclasses.replace(self, **kwargs)


class AutofillArgs(TypedDict):
    constants: ConsensusConstants
    config: NotRequired[dict[str, Any]]
    logged_in_fingerprint: NotRequired[int]


@streamable
@dataclasses.dataclass(frozen=True)
class CoinSelectionConfigLoader(Streamable):
    min_coin_amount: uint64 | None = None
    max_coin_amount: uint64 | None = None
    excluded_coin_amounts: list[uint64] | None = None
    excluded_coin_ids: list[bytes32] | None = None
    included_coin_ids: list[bytes32] | None = None
    primary_coin: bytes32 | None = None

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
            included_coin_ids=[] if self.included_coin_ids is None else self.included_coin_ids,
            primary_coin=self.primary_coin,
        )

    @classmethod
    def from_json_dict(cls, json_dict: dict[str, Any]) -> Self:
        if json_dict.get("excluded_coins") is not None:
            excluded_coins: list[Coin] = [Coin.from_json_dict(c) for c in json_dict["excluded_coins"]]
            excluded_coin_ids: list[str] = [c.name().hex() for c in excluded_coins]
            if "excluded_coin_ids" in json_dict:
                json_dict["excluded_coin_ids"] = [*excluded_coin_ids, *json_dict["excluded_coin_ids"]]
            else:
                json_dict["excluded_coin_ids"] = excluded_coin_ids
        return super().from_json_dict(json_dict)

    # This function is purely for ergonomics
    # But creates a small linting complication
    def override(self, **kwargs: Any) -> Self:
        return dataclasses.replace(self, **kwargs)


@streamable
@dataclasses.dataclass(frozen=True)
class TXConfigLoader(CoinSelectionConfigLoader):
    reuse_puzhash: bool | None = None

    def autofill(
        self,
        **kwargs: Unpack[AutofillArgs],
    ) -> TXConfig:
        constants: ConsensusConstants = kwargs["constants"]
        if self.reuse_puzhash is None:
            config: dict[str, Any] = kwargs.get("config", {})
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
            self.included_coin_ids,
            self.primary_coin,
        ).autofill(constants=constants)

        return TXConfig(
            autofilled_cs_config.min_coin_amount,
            autofilled_cs_config.max_coin_amount,
            autofilled_cs_config.excluded_coin_amounts,
            autofilled_cs_config.excluded_coin_ids,
            autofilled_cs_config.included_coin_ids,
            autofilled_cs_config.primary_coin,
            reuse_puzhash,
        )


DEFAULT_COIN_SELECTION_CONFIG = CoinSelectionConfig(
    uint64(0), uint64(DEFAULT_CONSTANTS.MAX_COIN_AMOUNT), [], [], [], None
)
DEFAULT_TX_CONFIG = TXConfig(
    DEFAULT_COIN_SELECTION_CONFIG.min_coin_amount,
    DEFAULT_COIN_SELECTION_CONFIG.max_coin_amount,
    DEFAULT_COIN_SELECTION_CONFIG.excluded_coin_amounts,
    DEFAULT_COIN_SELECTION_CONFIG.excluded_coin_ids,
    DEFAULT_COIN_SELECTION_CONFIG.included_coin_ids,
    DEFAULT_COIN_SELECTION_CONFIG.primary_coin,
    False,
)
