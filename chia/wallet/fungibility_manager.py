from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from chia_rs import Coin
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint16, uint32, uint64

from chia.util.streamable import UInt32Range, UInt64Range
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.conditions import Condition, CreateCoin
from chia.wallet.util.query_filter import FilterMode, HashFilter
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_action_scope import WalletActionScope
from chia.wallet.wallet_coin_store import CoinRecordOrder, WalletCoinStore

if TYPE_CHECKING:
    from chia.wallet.wallet_state_manager import WalletStateManager


@dataclass(frozen=True, kw_only=True)
class FungibilityManager:
    coin_store: WalletCoinStore
    # TODO: this is only a dependency because of the puzzle hash generation
    wallet_state_manager: WalletStateManager

    def get_fungible_wallet(self, wallet_id: uint32) -> Wallet | CATWallet:
        if (wallet := self.wallet_state_manager.wallets.get(wallet_id)) is None or not isinstance(
            wallet, (Wallet, CATWallet)
        ):
            raise ValueError(f"Wallet {wallet_id} is not eligible for coin splitting")
        return wallet

    async def split_coins(
        self,
        *,
        action_scope: WalletActionScope,
        wallet: Wallet | CATWallet,
        target_coin_id: bytes32,
        amount_per_coin: uint64,
        number_of_coins: uint16,
        fee: uint64,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> None:
        optional_coin = await self.coin_store.get_coin_record(target_coin_id)
        if optional_coin is None:
            raise ValueError(f"Could not find coin with ID {target_coin_id}")
        else:
            coin = optional_coin.coin

        total_amount = amount_per_coin * number_of_coins

        if coin.amount < total_amount:
            raise ValueError(f"Coin amount: {coin.amount} is less than the total amount of the split: {total_amount}.")

        outputs = [
            CreateCoin(
                await action_scope.get_puzzle_hash(self.wallet_state_manager, override_reuse_puzhash_with=False),
                amount_per_coin,
            )
            for _ in range(number_of_coins)
        ]

        if wallet.type() == WalletType.STANDARD_WALLET and coin.amount < total_amount + fee:
            async with action_scope.use() as interface:
                interface.side_effects.selected_coins.append(coin)
            coins = await wallet.select_coins(
                uint64(total_amount + fee - coin.amount),
                action_scope,
            )
            coins.add(coin)
        else:
            coins = {coin}

        await wallet.generate_signed_transaction(
            [output.amount for output in outputs],
            [output.puzzle_hash for output in outputs],
            action_scope,
            fee,
            coins=coins,
            extra_conditions=extra_conditions,
        )

    async def combine_coins(
        self,
        *,
        action_scope: WalletActionScope,
        wallet: Wallet | CATWallet,
        number_of_coins: uint16,
        largest_first: bool,
        fee: uint64,
        target_coin_amount: uint64 | None = None,
        target_coin_ids: list[bytes32] | None = None,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> None:
        coins: list[Coin] = []

        # First get the coin IDs specified
        if target_coin_ids is not None:
            target_records = (
                await self.coin_store.get_coin_records(
                    wallet_id=wallet.id(),
                    coin_id_filter=HashFilter(target_coin_ids, mode=uint8(FilterMode.include.value)),
                )
            ).records
            spent_ids = [cr.coin.name() for cr in target_records if cr.spent]
            if spent_ids:
                raise ValueError(f"Cannot combine already-spent coins: {', '.join(c.hex() for c in spent_ids)}")
            coins.extend(cr.coin for cr in target_records)

        async with action_scope.use() as interface:
            interface.side_effects.selected_coins.extend(coins)

        # Next let's select enough coins to meet the target + fee if there is one
        fungible_amount_needed = uint64(0) if target_coin_amount is None else target_coin_amount
        if isinstance(wallet, Wallet):
            fungible_amount_needed = uint64(fungible_amount_needed + fee)
        amount_selected = sum(c.amount for c in coins)
        if amount_selected < fungible_amount_needed:  # implicit fungible_amount_needed > 0 here
            coins.extend(
                await wallet.select_coins(
                    amount=uint64(fungible_amount_needed - amount_selected), action_scope=action_scope
                )
            )

        if len(coins) > number_of_coins:
            raise ValueError(
                f"Options specified cannot be met without selecting more coins than specified: {len(coins)}"
            )

        # Now let's select enough coins to get to the target number to combine
        if len(coins) < number_of_coins:
            coin_selection_config = action_scope.config.tx_config.coin_selection_config
            async with action_scope.use() as interface:
                coins.extend(
                    cr.coin
                    for cr in (
                        await self.coin_store.get_coin_records(
                            wallet_id=wallet.id(),
                            limit=uint32(number_of_coins - len(coins)),
                            order=CoinRecordOrder.amount,
                            coin_id_filter=HashFilter(
                                [c.name() for c in interface.side_effects.selected_coins],
                                mode=uint8(FilterMode.exclude.value),
                            ),
                            reverse=largest_first,
                            spent_range=UInt32Range(stop=uint32(0)),
                            amount_range=UInt64Range(
                                start=coin_selection_config.min_coin_amount,
                                stop=coin_selection_config.max_coin_amount,
                            ),
                        )
                    ).records
                )

        async with action_scope.use() as interface:
            interface.side_effects.selected_coins.extend(coins)

        primary_output_amount = (
            uint64(sum(c.amount for c in coins)) if target_coin_amount is None else target_coin_amount
        )
        if isinstance(wallet, Wallet):
            primary_output_amount = uint64(primary_output_amount - fee)

        await wallet.generate_signed_transaction(
            [primary_output_amount],
            [await action_scope.get_puzzle_hash(self.wallet_state_manager)],
            action_scope,
            fee,
            coins=set(coins),
            extra_conditions=extra_conditions,
        )
