from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Callable, Optional, cast, final

from chia_rs.chia_rs import G1Element
from chia_rs.sized_bytes import bytes32

from chia.data_layer.singleton_record import SingletonRecord
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.util.action_scope import ActionScope
from chia.util.streamable import Streamable, streamable
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.signer_protocol import SigningResponse
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.tx_config import TXConfig
from chia.wallet.wallet_spend_bundle import WalletSpendBundle
from chia.wallet.wsm_apis import GetUnusedDerivationRecordResult, StreambleGetUnusedDerivationRecordResult

if TYPE_CHECKING:
    # Avoid a circular import here
    from chia.wallet.wallet_state_manager import WalletStateManager


@streamable
@dataclass(frozen=True)
class _StreamableWalletSideEffects(Streamable):
    transactions: list[TransactionRecord]
    signing_responses: list[SigningResponse]
    extra_spends: list[WalletSpendBundle]
    selected_coins: list[Coin]
    singleton_records: list[SingletonRecord]
    get_unused_derivation_record_result: Optional[StreambleGetUnusedDerivationRecordResult]


@dataclass
class WalletSideEffects:
    transactions: list[TransactionRecord] = field(default_factory=list)
    signing_responses: list[SigningResponse] = field(default_factory=list)
    extra_spends: list[WalletSpendBundle] = field(default_factory=list)
    selected_coins: list[Coin] = field(default_factory=list)
    singleton_records: list[SingletonRecord] = field(default_factory=list)
    get_unused_derivation_record_result: Optional[StreambleGetUnusedDerivationRecordResult] = None

    def __bytes__(self) -> bytes:
        return bytes(_StreamableWalletSideEffects(**self.__dict__))

    @classmethod
    def from_bytes(cls, blob: bytes) -> WalletSideEffects:
        return cls(**_StreamableWalletSideEffects.from_bytes(blob).__dict__)


@final
@dataclass(frozen=True)
class WalletActionConfig:
    push: bool
    merge_spends: bool
    sign: Optional[bool]
    additional_signing_responses: list[SigningResponse]
    extra_spends: list[WalletSpendBundle]
    tx_config: TXConfig
    puzzle_for_pk: Callable[[G1Element], Program]

    def adjust_for_side_effects(self, side_effects: WalletSideEffects) -> WalletActionConfig:
        return replace(
            self,
            tx_config=replace(
                self.tx_config,
                excluded_coin_ids=[*self.tx_config.excluded_coin_ids, *(c.name() for c in side_effects.selected_coins)],
            ),
        )


class WalletActionScope(ActionScope[WalletSideEffects, WalletActionConfig]):
    async def _get_unused_derivation_path(
        self, wallet_state_manager: WalletStateManager
    ) -> GetUnusedDerivationRecordResult:
        async with self.use() as interface:
            result = await wallet_state_manager._get_unused_derivation_record(
                wallet_state_manager.main_wallet.id(),
                previous_result=interface.side_effects.get_unused_derivation_record_result.to_standard()
                if interface.side_effects.get_unused_derivation_record_result is not None
                else None,
            )
            interface.side_effects.get_unused_derivation_record_result = (
                StreambleGetUnusedDerivationRecordResult.from_standard(result)
            )
        return result

    async def _get_new_puzzle(self, wallet_state_manager: WalletStateManager) -> Program:
        puzzle = self.config.puzzle_for_pk((await self._get_unused_derivation_path(wallet_state_manager)).record.pubkey)
        return puzzle

    async def _get_new_puzzle_hash(self, wallet_state_manager: WalletStateManager) -> bytes32:
        return (await self._get_unused_derivation_path(wallet_state_manager)).record.puzzle_hash

    async def get_puzzle(
        self, wallet_state_manager: WalletStateManager, override_reuse_puzhash_with: Optional[bool] = None
    ) -> Program:
        if (
            self.config.tx_config.reuse_puzhash or override_reuse_puzhash_with is True
        ) and override_reuse_puzhash_with is not False:
            record: Optional[DerivationRecord] = await wallet_state_manager.get_current_derivation_record_for_wallet(
                wallet_state_manager.main_wallet.id()
            )
            if record is None:
                return await self._get_new_puzzle(wallet_state_manager)  # pragma: no cover
            puzzle = self.config.puzzle_for_pk(record.pubkey)
            return puzzle
        else:
            return await self._get_new_puzzle(wallet_state_manager)

    async def get_puzzle_hash(
        self, wallet_state_manager: WalletStateManager, override_reuse_puzhash_with: Optional[bool] = None
    ) -> bytes32:
        if (
            self.config.tx_config.reuse_puzhash or override_reuse_puzhash_with is True
        ) and override_reuse_puzhash_with is not False:
            record: Optional[DerivationRecord] = await wallet_state_manager.get_current_derivation_record_for_wallet(
                wallet_state_manager.main_wallet.id()
            )
            if record is None:
                return await self._get_new_puzzle_hash(wallet_state_manager)  # pragma: no cover
            return record.puzzle_hash
        else:
            return await self._get_new_puzzle_hash(wallet_state_manager)


@contextlib.asynccontextmanager
async def new_wallet_action_scope(
    wallet_state_manager: WalletStateManager,
    tx_config: TXConfig,
    push: bool = False,
    merge_spends: bool = True,
    sign: Optional[bool] = None,
    additional_signing_responses: list[SigningResponse] = [],
    extra_spends: list[WalletSpendBundle] = [],
    puzzle_for_pk: Optional[Callable[[G1Element], Program]] = None,
) -> AsyncIterator[WalletActionScope]:
    if puzzle_for_pk is None:
        puzzle_for_pk = wallet_state_manager.main_wallet.puzzle_for_pk
    assert puzzle_for_pk is not None
    async with WalletActionScope.new_scope(
        WalletSideEffects,
        WalletActionConfig(
            push, merge_spends, sign, additional_signing_responses, extra_spends, tx_config, puzzle_for_pk
        ),
    ) as self:
        self = cast(WalletActionScope, self)
        async with self.use() as interface:
            interface.side_effects.signing_responses = additional_signing_responses.copy()
            interface.side_effects.extra_spends = extra_spends.copy()

        yield self

    self.side_effects.transactions = await wallet_state_manager.add_pending_transactions(
        self.side_effects.transactions,
        push=push,
        merge_spends=merge_spends,
        sign=sign,
        additional_signing_responses=self.side_effects.signing_responses,
        extra_spends=self.side_effects.extra_spends,
        singleton_records=self.side_effects.singleton_records,
    )
    if push and self.side_effects.get_unused_derivation_record_result is not None:
        await self.side_effects.get_unused_derivation_record_result.to_standard().commit(wallet_state_manager)
