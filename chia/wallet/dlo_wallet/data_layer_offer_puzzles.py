import asyncio
from typing import List
from blspy import AugSchemeMPL
from chia.wallet.db_wallet.db_wallet_puzzles import create_offer_fullpuz
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.program import Program
from chia.util.ints import uint64
from chia.wallet.wallet import Wallet
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle


async def generate_datalayer_offer_spend(
    special_wallet: Wallet,
    input_list: List,
):

    amount: uint64 = input_list[0]
    leaf_reveal: bytes = input_list[1]
    host_genesis_id: bytes32 = input_list[2]
    claim_target: bytes32 = input_list[3]
    recovery_target: bytes32 = input_list[4]
    recovery_timelock: uint64 = input_list[5]

    full_puzzle: Program = create_offer_fullpuz(
        leaf_reveal, host_genesis_id, claim_target, recovery_target, recovery_timelock
    )
    tr = await special_wallet.standard_wallet.generate_signed_transaction(full_puzzle, amount)
    await special_wallet.wallet_state_manager.interested_store.add_interested_puzzle_hash(
        full_puzzle.get_tree_hash(), special_wallet.wallet_id, True
    )
    special_wallet.standard_wallet.push_transaction(tr)
    return tr


async def create_recover_dl_offer_spend(
    special_wallet: Wallet,
    input_list: List,
):
    coins = await special_wallet.select_coin(1)
    coin = coins.pop()
    solution = Program.to([0, coin.amount])
    leaf_reveal: bytes = input_list[0]
    host_genesis_id: bytes32 = input_list[1]
    claim_target: bytes32 = input_list[2]
    recovery_target: bytes32 = input_list[3]
    recovery_timelock: uint64 = input_list[4]

    full_puzzle: Program = create_offer_fullpuz(
        leaf_reveal, host_genesis_id, claim_target, recovery_target, recovery_timelock
    )
    coin_spend = CoinSpend(coin, full_puzzle, solution)
    sb = SpendBundle([coin_spend], AugSchemeMPL.aggregated([]))
    return sb
