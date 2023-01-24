from __future__ import annotations

from typing import Iterator, List, Tuple

import pytest

from chia.cmds.units import units
from chia.server.server import ChiaServer
from chia.simulator.block_tools import BlockTools
from chia.simulator.full_node_simulator import FullNodeSimulator, backoff_times
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint64
from chia.wallet.wallet_node import WalletNode


def test_backoff_yields_initial_first() -> None:
    backoff = backoff_times(initial=3, final=10)
    assert next(backoff) == 3


def test_backoff_yields_final_at_end() -> None:
    def clock(times: Iterator[int] = iter([0, 1])) -> float:
        return next(times)

    backoff = backoff_times(initial=2, final=7, time_to_final=1, clock=clock)
    next(backoff)
    assert next(backoff) == 7


def test_backoff_yields_half_at_halfway() -> None:
    def clock(times: Iterator[int] = iter([0, 1])) -> float:
        return next(times)

    backoff = backoff_times(initial=4, final=6, time_to_final=2, clock=clock)
    next(backoff)
    assert next(backoff) == 5


def test_backoff_saturates_at_final() -> None:
    def clock(times: Iterator[int] = iter([0, 2])) -> float:
        return next(times)

    backoff = backoff_times(initial=1, final=3, time_to_final=1, clock=clock)
    next(backoff)
    assert next(backoff) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(argnames="count", argvalues=[0, 1, 2, 5, 10])
@pytest.mark.parametrize(argnames="guarantee_transaction_blocks", argvalues=[False, True])
async def test_simulation_farm_blocks_to_puzzlehash(
    count: int,
    guarantee_transaction_blocks: bool,
    simulator_and_wallet: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
) -> None:
    [[full_node_api], _, _] = simulator_and_wallet

    # Starting at the beginning.
    assert full_node_api.full_node.blockchain.get_peak_height() is None

    await full_node_api.farm_blocks_to_puzzlehash(
        count=count, guarantee_transaction_blocks=guarantee_transaction_blocks
    )

    # The requested number of blocks had been processed.
    expected_height = None if count == 0 else count
    assert full_node_api.full_node.blockchain.get_peak_height() == expected_height


@pytest.mark.asyncio
@pytest.mark.parametrize(argnames="count", argvalues=[0, 1, 2, 5, 10])
async def test_simulation_farm_blocks_to_wallet(
    count: int,
    simulator_and_wallet: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
) -> None:
    [[full_node_api], [[wallet_node, wallet_server]], _] = simulator_and_wallet

    await wallet_server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)

    # Avoiding an attribute error below.
    assert wallet_node.wallet_state_manager is not None

    wallet = wallet_node.wallet_state_manager.main_wallet

    # Starting at the beginning.
    assert full_node_api.full_node.blockchain.get_peak_height() is None

    rewards = await full_node_api.farm_blocks_to_wallet(count=count, wallet=wallet)

    # The expected rewards have been received and confirmed.
    unconfirmed_balance = await wallet.get_unconfirmed_balance()
    confirmed_balance = await wallet.get_confirmed_balance()
    assert [unconfirmed_balance, confirmed_balance] == [rewards, rewards]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    argnames=["amount", "coin_count"],
    argvalues=[
        [0, 0],
        [1, 2],
        [(2 * units["chia"]) - 1, 2],
        [2 * units["chia"], 2],
        [(2 * units["chia"]) + 1, 4],
        [3 * units["chia"], 4],
        [10 * units["chia"], 10],
    ],
)
async def test_simulation_farm_rewards_to_wallet(
    amount: int,
    coin_count: int,
    simulator_and_wallet: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
) -> None:
    [[full_node_api], [[wallet_node, wallet_server]], _] = simulator_and_wallet

    await wallet_server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)

    # Avoiding an attribute error below.
    assert wallet_node.wallet_state_manager is not None

    wallet = wallet_node.wallet_state_manager.main_wallet

    rewards = await full_node_api.farm_rewards_to_wallet(amount=amount, wallet=wallet)

    # At least the requested amount was farmed.
    assert rewards >= amount

    # The rewards amount is both received and confirmed.
    unconfirmed_balance = await wallet.get_unconfirmed_balance()
    confirmed_balance = await wallet.get_confirmed_balance()
    assert [unconfirmed_balance, confirmed_balance] == [rewards, rewards]

    # The expected number of coins were received.
    all_coin_records = await wallet.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(wallet.id())
    assert len(all_coin_records) == coin_count


@pytest.mark.asyncio
async def test_wait_transaction_records_entered_mempool(
    simulator_and_wallet: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
) -> None:
    repeats = 50
    tx_amount = 1
    [[full_node_api], [[wallet_node, wallet_server]], _] = simulator_and_wallet

    await wallet_server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)

    # Avoiding an attribute hint issue below.
    assert wallet_node.wallet_state_manager is not None

    wallet = wallet_node.wallet_state_manager.main_wallet

    # generate some coins for repetitive testing
    await full_node_api.farm_rewards_to_wallet(amount=repeats * tx_amount, wallet=wallet)
    coins = await full_node_api.create_coins_with_amounts(amounts=[uint64(tx_amount)] * repeats, wallet=wallet)
    assert len(coins) == repeats

    # repeating just to try to expose any flakiness
    for coin in coins:
        tx = await wallet.generate_signed_transaction(
            amount=uint64(tx_amount),
            puzzle_hash=await wallet_node.wallet_state_manager.main_wallet.get_new_puzzlehash(),
            coins={coin},
        )
        await wallet.push_transaction(tx)

        await full_node_api.wait_transaction_records_entered_mempool(records=[tx])
        assert tx.spend_bundle is not None
        assert full_node_api.full_node.mempool_manager.get_spendbundle(tx.spend_bundle.name()) is not None


@pytest.mark.asyncio
async def test_process_transaction_records(
    simulator_and_wallet: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
) -> None:
    repeats = 50
    tx_amount = 1
    [[full_node_api], [[wallet_node, wallet_server]], _] = simulator_and_wallet

    await wallet_server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)

    # Avoiding an attribute hint issue below.
    assert wallet_node.wallet_state_manager is not None

    wallet = wallet_node.wallet_state_manager.main_wallet

    # generate some coins for repetitive testing
    await full_node_api.farm_rewards_to_wallet(amount=repeats * tx_amount, wallet=wallet)
    coins = await full_node_api.create_coins_with_amounts(amounts=[uint64(tx_amount)] * repeats, wallet=wallet)
    assert len(coins) == repeats

    # repeating just to try to expose any flakiness
    for coin in coins:
        tx = await wallet.generate_signed_transaction(
            amount=uint64(tx_amount),
            puzzle_hash=await wallet_node.wallet_state_manager.main_wallet.get_new_puzzlehash(),
            coins={coin},
        )
        await wallet.push_transaction(tx)

        await full_node_api.process_transaction_records(records=[tx])
        assert full_node_api.full_node.coin_store.get_coin_record(coin.name()) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    argnames="amounts",
    argvalues=[
        *[pytest.param([uint64(1)] * n, id=f"1 mojo x {n}") for n in [0, 1, 10, 49, 51, 103]],
        *[
            pytest.param(list(uint64(x) for x in range(1, n + 1)), id=f"incrementing x {n}")
            for n in [1, 10, 49, 51, 103]
        ],
    ],
)
async def test_create_coins_with_amounts(
    amounts: List[uint64],
    simulator_and_wallet: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
) -> None:
    [[full_node_api], [[wallet_node, wallet_server]], _] = simulator_and_wallet

    await wallet_server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)

    # Avoiding an attribute hint issue below.
    assert wallet_node.wallet_state_manager is not None

    wallet = wallet_node.wallet_state_manager.main_wallet

    await full_node_api.farm_rewards_to_wallet(amount=sum(amounts), wallet=wallet)
    # Get some more coins.  The creator helper doesn't get you all the coins you
    # need yet.
    await full_node_api.farm_blocks_to_wallet(count=2, wallet=wallet)
    coins = await full_node_api.create_coins_with_amounts(amounts=amounts, wallet=wallet)

    assert sorted(coin.amount for coin in coins) == sorted(amounts)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    argnames="amounts",
    argvalues=[
        [0],
        [5, -5],
        [4, 0],
    ],
    ids=lambda amounts: ", ".join(str(amount) for amount in amounts),
)
async def test_create_coins_with_invalid_amounts_raises(
    amounts: List[int],
    simulator_and_wallet: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
) -> None:
    [[full_node_api], [[wallet_node, wallet_server]], _] = simulator_and_wallet

    await wallet_server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)

    # Avoiding an attribute hint issue below.backoff_times
    assert wallet_node.wallet_state_manager is not None

    wallet = wallet_node.wallet_state_manager.main_wallet

    with pytest.raises(Exception, match="Coins must have a positive value"):
        # Passing integers since the point is to test invalid values including
        # negatives that will not fit in a uint64.
        await full_node_api.create_coins_with_amounts(
            amounts=amounts,  # type: ignore[arg-type]
            wallet=wallet,
        )
