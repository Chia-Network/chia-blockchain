import pytest

from dataclasses import replace

from blspy import G2Element

from chia.clvm.spend_sim import sim_and_client
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.errors import Err
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.vc_wallet.vc_drivers import (
    COVENANT_LAYER,
    create_covenant_layer,
    solve_covenant_layer,
    create_std_parent_morpher,
)


ACS: Program = Program.to(1)
ACS_PH: bytes32 = ACS.get_tree_hash()
MOCK_SINGLETON_MOD: Program = Program.to([2, 5, 11])
MOCK_SINGLETON_MOD_HASH: bytes32 = MOCK_SINGLETON_MOD.get_tree_hash()
MOCK_LAUNCHER_ID: bytes32 = bytes32([0] * 32)
MOCK_LAUNCHER_HASH: bytes32 = bytes32([1] * 32)
MOCK_SINGLETON: Program = MOCK_SINGLETON_MOD.curry(
    (MOCK_SINGLETON_MOD_HASH, (MOCK_LAUNCHER_ID, MOCK_LAUNCHER_HASH)),
    ACS,
)


@pytest.mark.asyncio
async def test_covenant_layer() -> None:
    async with sim_and_client() as (sim, client):
        # Create a puzzle that will not pass the initial covenant check
        FAKE_ACS: Program = Program.to([3, None, None, 1])
        # The output puzzle will be the same for both
        covenant_puzzle: Program = create_covenant_layer(ACS_PH, create_std_parent_morpher(ACS_PH), ACS)
        covenant_puzzle_hash: bytes32 = covenant_puzzle.get_tree_hash()

        # Farm both coins
        await sim.farm_block(FAKE_ACS.get_tree_hash())
        await sim.farm_block(ACS_PH)

        # Find and spend both
        fake_acs_coin: Coin = (
            await client.get_coin_records_by_puzzle_hashes([FAKE_ACS.get_tree_hash()], include_spent_coins=False)
        )[0].coin
        acs_coin: Coin = (await client.get_coin_records_by_puzzle_hashes([ACS_PH], include_spent_coins=False))[0].coin
        await client.push_tx(
            SpendBundle(
                [
                    CoinSpend(
                        fake_acs_coin,
                        FAKE_ACS,
                        Program.to([[51, covenant_puzzle.get_tree_hash(), fake_acs_coin.amount]]),
                    ),
                    CoinSpend(
                        acs_coin,
                        ACS,
                        Program.to([[51, covenant_puzzle.get_tree_hash(), acs_coin.amount]]),
                    ),
                ],
                G2Element(),
            )
        )
        await sim.farm_block()

        # Find the covenant coins with equal puzzles
        fake_acs_cov: Coin = (
            await client.get_coin_records_by_parent_ids([fake_acs_coin.name()], include_spent_coins=False)
        )[0].coin
        acs_cov: Coin = (await client.get_coin_records_by_parent_ids([acs_coin.name()], include_spent_coins=False))[
            0
        ].coin

        # With the honest coin, attempt to spend the non-eve case too soon
        result: Tuple[MempoolInclusionStatus, Optional[Err]] = await client.push_tx(SpendBundle(
            [
                CoinSpend(
                    acs_cov,
                    covenant_puzzle,
                    solve_covenant_layer(
                        LineageProof(parent_name=acs_coin.parent_coin_info, inner_puzzle_hash=ACS_PH, amount=acs_coin.amount),
                        Program.to([[51, covenant_puzzle.get_tree_hash(), acs_coin.amount]]),
                    ),
                ),
            ],
            G2Element(),
        ))
        assert result == (MempoolInclusionStatus.FAILED, Err.ASSERT_MY_PARENT_ID_FAILED)

        # Try the initial spend, which the fake origin coin should fail
        for parent, cov in ((fake_acs_coin, fake_acs_cov), (acs_coin, acs_cov)):
            result = await client.push_tx(
                SpendBundle(
                    [
                        CoinSpend(
                            cov,
                            covenant_puzzle,
                            solve_covenant_layer(
                                LineageProof(parent_name=parent.parent_coin_info, amount=parent.amount),
                                Program.to([[51, covenant_puzzle.get_tree_hash(), cov.amount]]),
                            ),
                        ),
                    ],
                    G2Element(),
                )
            )
            if parent == fake_acs_coin:
                assert result == (MempoolInclusionStatus.FAILED, Err.ASSERT_MY_PARENT_ID_FAILED)
            else:
                assert result == (MempoolInclusionStatus.SUCCESS, None)

        await sim.farm_block()

        new_acs_cov: Coin = (await client.get_coin_records_by_parent_ids([acs_cov.name()], include_spent_coins=False))[
            0
        ].coin

        result: Tuple[MempoolInclusionStatus, Optional[Err]] = await client.push_tx(SpendBundle(
            [
                CoinSpend(
                    new_acs_cov,
                    covenant_puzzle,
                    solve_covenant_layer(
                        LineageProof(parent_name=acs_cov.parent_coin_info, inner_puzzle_hash=ACS_PH, amount=acs_cov.amount),
                        Program.to([[51, covenant_puzzle.get_tree_hash(), new_acs_cov.amount]]),
                    ),
                ),
            ],
            G2Element(),
        ))
        assert result == (MempoolInclusionStatus.SUCCESS, None)


@pytest.mark.asyncio
async def test_did_tp() -> None:
    async with sim_and_client() as (sim, client):
        pass


@pytest.mark.asyncio
async def test_did_backdoor() -> None:
    async with sim_and_client() as (sim, client):
        pass


@pytest.mark.asyncio
async def test_p2_puzzle_or_hidden_puzzle() -> None:
    async with sim_and_client() as (sim, client):
        pass


@pytest.mark.asyncio
async def test_vc_lifecycle() -> None:
    async with sim_and_client() as (sim, client):
        pass
