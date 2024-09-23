from __future__ import annotations

import dataclasses
from typing import List, Optional, Sequence

from chia.cmds.cmds_util import CMDTXConfigLoader, cli_confirm, get_wallet_client
from chia.cmds.param_types import CliAmount
from chia.cmds.wallet_funcs import get_mojo_per_unit, get_wallet_type
from chia.rpc.wallet_request_types import CombineCoins, SplitCoins
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.conditions import ConditionValidTimes
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.wallet_types import WalletType


async def async_combine(
    *,
    wallet_rpc_port: Optional[int],
    fingerprint: Optional[int],
    wallet_id: int,
    fee: uint64,
    max_coin_amount: CliAmount,
    min_coin_amount: CliAmount,
    excluded_amounts: Sequence[CliAmount],
    coins_to_exclude: Sequence[bytes32],
    reuse_puzhash: bool,
    number_of_coins: int,
    target_coin_amount: Optional[CliAmount],
    target_coin_ids: Sequence[bytes32],
    largest_first: bool,
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    async with get_wallet_client(wallet_rpc_port, fingerprint) as (wallet_client, fingerprint, config):
        try:
            wallet_type = await get_wallet_type(wallet_id=wallet_id, wallet_client=wallet_client)
            mojo_per_unit = get_mojo_per_unit(wallet_type)
        except LookupError:
            print(f"Wallet id: {wallet_id} not found.")
            return []
        if not await wallet_client.get_synced():
            print("Wallet not synced. Please wait.")
            return []

        tx_config = CMDTXConfigLoader(
            max_coin_amount=max_coin_amount,
            min_coin_amount=min_coin_amount,
            excluded_coin_amounts=list(excluded_amounts),
            excluded_coin_ids=list(coins_to_exclude),
            reuse_puzhash=reuse_puzhash,
        ).to_tx_config(mojo_per_unit, config, fingerprint)

        final_target_coin_amount = (
            None if target_coin_amount is None else target_coin_amount.convert_amount(mojo_per_unit)
        )

        combine_request = CombineCoins(
            wallet_id=uint32(wallet_id),
            target_coin_amount=final_target_coin_amount,
            number_of_coins=uint16(number_of_coins),
            target_coin_ids=list(target_coin_ids),
            largest_first=largest_first,
            fee=fee,
            push=False,
        )
        resp = await wallet_client.combine_coins(
            combine_request,
            tx_config,
            timelock_info=condition_valid_times,
        )

        print(f"Transactions would combine up to {number_of_coins} coins.")
        if push:
            cli_confirm("Would you like to Continue? (y/n): ")
            resp = await wallet_client.combine_coins(
                dataclasses.replace(combine_request, push=True),
                tx_config,
                timelock_info=condition_valid_times,
            )
            for tx in resp.transactions:
                print(f"Transaction sent: {tx.name}")
                print(f"To get status, use command: chia wallet get_transaction -f {fingerprint} -tx 0x{tx.name}")

        return resp.transactions


async def async_split(
    *,
    wallet_rpc_port: Optional[int],
    fingerprint: Optional[int],
    wallet_id: int,
    fee: uint64,
    number_of_coins: int,
    amount_per_coin: CliAmount,
    target_coin_id: bytes32,
    max_coin_amount: CliAmount,
    min_coin_amount: CliAmount,
    excluded_amounts: Sequence[CliAmount],
    coins_to_exclude: Sequence[bytes32],
    reuse_puzhash: bool,
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    async with get_wallet_client(wallet_rpc_port, fingerprint) as (wallet_client, fingerprint, config):
        try:
            wallet_type = await get_wallet_type(wallet_id=wallet_id, wallet_client=wallet_client)
            mojo_per_unit = get_mojo_per_unit(wallet_type)
        except LookupError:
            print(f"Wallet id: {wallet_id} not found.")
            return []
        if not await wallet_client.get_synced():
            print("Wallet not synced. Please wait.")
            return []

        final_amount_per_coin = amount_per_coin.convert_amount(mojo_per_unit)

        tx_config = CMDTXConfigLoader(
            max_coin_amount=max_coin_amount,
            min_coin_amount=min_coin_amount,
            excluded_coin_amounts=list(excluded_amounts),
            excluded_coin_ids=list(coins_to_exclude),
            reuse_puzhash=reuse_puzhash,
        ).to_tx_config(mojo_per_unit, config, fingerprint)

        transactions: List[TransactionRecord] = (
            await wallet_client.split_coins(
                SplitCoins(
                    wallet_id=uint32(wallet_id),
                    number_of_coins=uint16(number_of_coins),
                    amount_per_coin=uint64(final_amount_per_coin),
                    target_coin_id=target_coin_id,
                    fee=fee,
                    push=push,
                ),
                tx_config=tx_config,
                timelock_info=condition_valid_times,
            )
        ).transactions

        if push:
            for tx in transactions:
                print(f"Transaction sent: {tx.name}")
                print(f"To get status, use command: chia wallet get_transaction -f {fingerprint} -tx 0x{tx.name}")
        dust_threshold = config.get("xch_spam_amount", 1000000)  # min amount per coin in mojo
        spam_filter_after_n_txs = config.get("spam_filter_after_n_txs", 200)  # how many txs to wait before filtering
        if final_amount_per_coin < dust_threshold and wallet_type == WalletType.STANDARD_WALLET:
            print(
                f"WARNING: The amount per coin: {amount_per_coin.amount} is less than the dust threshold: "
                f"{dust_threshold / (1 if amount_per_coin.mojos else mojo_per_unit)}. Some or all of the Coins "
                f"{'will' if number_of_coins > spam_filter_after_n_txs else 'may'} not show up in your wallet unless "
                f"you decrease the dust limit to below {final_amount_per_coin} mojos or disable it by setting it to 0."
            )
        return transactions
