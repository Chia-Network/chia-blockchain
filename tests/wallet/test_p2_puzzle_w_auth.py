import pytest

from typing import Optional, Tuple

from blspy import G2Element

from chia.clvm.spend_sim import sim_and_client
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.errors import Err
from chia.util.hash import std_hash
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.puzzles.p2_puzzle_w_auth import (
    create_p2_puzzle_w_auth,
    match_p2_puzzle_w_auth,
    solve_p2_puzzle_w_auth,
    create_did_puzzle_authorizer,
    match_did_puzzle_authorizer,
    solve_did_puzzle_authorizer,
)

ACS: Program = Program.to([3, (1, "entropy"), 1, None])
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
async def test_p2_puzzle_w_auth() -> None:
    async with sim_and_client() as (sim, client):
        # Create it with mock singleton info
        brick_hash: bytes32 = bytes32([0] * 32)
        delegated_puzzle: Program = Program.to([4, [4, (1, 51), [4, 1, [1, None]]], None])  # return a CC with solved ph
        did_auth_puz: Program = create_did_puzzle_authorizer(
            MOCK_LAUNCHER_ID, MOCK_SINGLETON_MOD_HASH, MOCK_LAUNCHER_HASH
        )
        assert match_did_puzzle_authorizer(uncurry_puzzle(did_auth_puz)) == (MOCK_LAUNCHER_ID,)
        yoink_puz: Program = create_p2_puzzle_w_auth(did_auth_puz, delegated_puzzle)
        assert match_p2_puzzle_w_auth(uncurry_puzzle(yoink_puz)) == (did_auth_puz, delegated_puzzle)

        await sim.farm_block(yoink_puz.get_tree_hash())
        yoink_coin: Coin = (
            await client.get_coin_records_by_puzzle_hashes([yoink_puz.get_tree_hash()], include_spent_coins=False)
        )[0].coin

        # Define parameters for next few spend attempts
        provider_innerpuzhash: bytes32 = ACS_PH
        my_coin_id: bytes32 = yoink_coin.name()
        bad_data: bytes32 = bytes32([0] * 32)

        # Try to yoink without any announcement
        result: Tuple[MempoolInclusionStatus, Optional[Err]] = await client.push_tx(
            SpendBundle(
                [
                    CoinSpend(
                        yoink_coin,
                        yoink_puz,
                        solve_p2_puzzle_w_auth(
                            solve_did_puzzle_authorizer(
                                bad_data,
                                my_coin_id,
                            ),
                            Program.to(brick_hash),
                        ),
                    )
                ],
                G2Element(),
            )
        )
        assert result == (MempoolInclusionStatus.FAILED, Err.ASSERT_ANNOUNCE_CONSUMED_FAILED)

        # Create the "DID" now
        await sim.farm_block(MOCK_SINGLETON.get_tree_hash())
        did_coin: Coin = (
            await client.get_coin_records_by_puzzle_hashes([MOCK_SINGLETON.get_tree_hash()], include_spent_coins=False)
        )[0].coin
        did_authorization_spend: CoinSpend = CoinSpend(
            did_coin,
            MOCK_SINGLETON,
            Program.to([[[62, std_hash(my_coin_id + delegated_puzzle.get_tree_hash())]]]),
        )

        # Try to pass the wrong coin id
        result = await client.push_tx(
            SpendBundle(
                [
                    CoinSpend(
                        yoink_coin,
                        yoink_puz,
                        solve_p2_puzzle_w_auth(
                            solve_did_puzzle_authorizer(
                                provider_innerpuzhash,
                                bad_data,
                            ),
                            Program.to(brick_hash),
                        ),
                    ),
                    did_authorization_spend,
                ],
                G2Element(),
            )
        )
        assert result == (MempoolInclusionStatus.FAILED, Err.ASSERT_MY_COIN_ID_FAILED)

        # Actually use announcement
        successful_spend: SpendBundle = SpendBundle(
            [
                CoinSpend(
                    yoink_coin,
                    yoink_puz,
                    solve_p2_puzzle_w_auth(
                        solve_did_puzzle_authorizer(
                            provider_innerpuzhash,
                            my_coin_id,
                        ),
                        Program.to(brick_hash),
                    ),
                ),
                did_authorization_spend,
            ],
            G2Element(),
        )
        result = await client.push_tx(successful_spend)
        assert result == (MempoolInclusionStatus.SUCCESS, None)

        await sim.farm_block()

        assert len(await client.get_coin_records_by_puzzle_hashes([brick_hash], include_spent_coins=False)) > 0
