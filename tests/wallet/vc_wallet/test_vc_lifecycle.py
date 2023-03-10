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
from chia.util.ints import uint64
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.singleton_top_layer_v1_1 import launch_conditions_and_coinsol
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.vc_wallet.vc_drivers import (
    VerifiedCredential,
    create_covenant_layer,
    match_covenant_layer,
    solve_covenant_layer,
    create_did_tp,
    match_did_tp,
    solve_did_tp,
    create_p2_puzzle_w_auth,
    match_p2_puzzle_w_auth,
    solve_p2_puzzle_w_auth,
    create_did_puzzle_authorizer,
    match_did_puzzle_authorizer,
    solve_did_puzzle_authorizer,
    create_viral_backdoor,
    match_viral_backdoor,
    solve_viral_backdoor,
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
        assert match_covenant_layer(uncurry_puzzle(covenant_puzzle)) == (ACS_PH, create_std_parent_morpher(ACS_PH), ACS)
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
                        Program.to([[51, covenant_puzzle_hash, fake_acs_coin.amount]]),
                    ),
                    CoinSpend(
                        acs_coin,
                        ACS,
                        Program.to([[51, covenant_puzzle_hash, acs_coin.amount]]),
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
        result: Tuple[MempoolInclusionStatus, Optional[Err]] = await client.push_tx(
            SpendBundle(
                [
                    CoinSpend(
                        acs_cov,
                        covenant_puzzle,
                        solve_covenant_layer(
                            LineageProof(
                                parent_name=acs_coin.parent_coin_info,
                                inner_puzzle_hash=ACS_PH,
                                amount=uint64(acs_coin.amount),
                            ),
                            None,
                            Program.to([[51, covenant_puzzle_hash, acs_coin.amount]]),
                        ),
                    ),
                ],
                G2Element(),
            )
        )
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
                                LineageProof(parent_name=parent.parent_coin_info, amount=uint64(parent.amount)),
                                None,
                                Program.to([[51, covenant_puzzle_hash, cov.amount]]),
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

        result = await client.push_tx(
            SpendBundle(
                [
                    CoinSpend(
                        new_acs_cov,
                        covenant_puzzle,
                        solve_covenant_layer(
                            LineageProof(
                                parent_name=acs_cov.parent_coin_info,
                                inner_puzzle_hash=ACS_PH,
                                amount=uint64(acs_cov.amount),
                            ),
                            None,
                            Program.to([[51, covenant_puzzle_hash, new_acs_cov.amount]]),
                        ),
                    ),
                ],
                G2Element(),
            )
        )
        assert result == (MempoolInclusionStatus.SUCCESS, None)


@pytest.mark.asyncio
async def test_did_tp() -> None:
    async with sim_and_client() as (sim, client):
        # Make a mock ownership layer
        # Prepends new metadata and new transfer program as REMARK condition to conditions of TP
        # (mod (METADATA TP solution) (a (q . (c (c (q . 1) (c 2 (c 5 ()))) 11)) (a TP (list METADATA () solution))))
        # (a (q 4 (c (q . 1) (c 2 (c 5 ()))) 11) (a 5 (c 2 (c () (c 11 ())))))
        MOCK_OWNERSHIP_LAYER: Program = Program.fromhex(
            "ff02ffff01ff04ffff04ffff0101ffff04ff02ffff04ff05ff80808080ff0b80ffff02ff05ffff04ff02ffff04ff80ffff04ff0bff808080808080"  # noqa: E501
        )
        # Create it with mock singleton info
        transfer_program: Program = create_did_tp(MOCK_LAUNCHER_ID, MOCK_SINGLETON_MOD_HASH, MOCK_LAUNCHER_HASH)
        assert match_did_tp(uncurry_puzzle(transfer_program)) == (MOCK_LAUNCHER_ID,)
        ownership_puzzle: Program = MOCK_OWNERSHIP_LAYER.curry(None, transfer_program)

        await sim.farm_block(ownership_puzzle.get_tree_hash())
        ownership_coin: Coin = (
            await client.get_coin_records_by_puzzle_hashes(
                [ownership_puzzle.get_tree_hash()], include_spent_coins=False
            )
        )[0].coin

        # Define parameters for next few spend attempts
        provider_innerpuzhash: bytes32 = ACS_PH
        my_coin_id: bytes32 = ownership_coin.name()
        new_metadata: Program = Program.to("SUCCESS")
        new_tp: Program = Program.to("NEW TP")
        bad_data: bytes32 = bytes32([0] * 32)

        # Try to update metadata and tp without any announcement
        result: Tuple[MempoolInclusionStatus, Optional[Err]] = await client.push_tx(
            SpendBundle(
                [
                    CoinSpend(
                        ownership_coin,
                        ownership_puzzle,
                        Program.to(
                            [
                                solve_did_tp(
                                    bad_data,
                                    my_coin_id,
                                    new_metadata,
                                    new_tp,
                                )
                            ]
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
            Program.to([[[62, std_hash(my_coin_id + new_metadata.get_tree_hash() + new_tp.get_tree_hash())]]]),
        )

        # Try to pass the wrong coin id
        result = await client.push_tx(
            SpendBundle(
                [
                    CoinSpend(
                        ownership_coin,
                        ownership_puzzle,
                        Program.to(
                            [
                                solve_did_tp(
                                    provider_innerpuzhash,
                                    bad_data,
                                    new_metadata,
                                    new_tp,
                                )
                            ]
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
                    ownership_coin,
                    ownership_puzzle,
                    Program.to(
                        [
                            solve_did_tp(
                                provider_innerpuzhash,
                                my_coin_id,
                                new_metadata,
                                new_tp,
                            )
                        ]
                    ),
                ),
                did_authorization_spend,
            ],
            G2Element(),
        )
        result = await client.push_tx(successful_spend)
        assert result == (MempoolInclusionStatus.SUCCESS, None)

        remark_condition: Program = next(
            condition
            for condition in successful_spend.coin_spends[0]
            .puzzle_reveal.to_program()
            .run(successful_spend.coin_spends[0].solution.to_program())
            .as_iter()
            if condition.first() == Program.to(1)
        )
        assert remark_condition == Program.to([1, new_metadata, new_tp])


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


@pytest.mark.asyncio
async def test_viral_backdoor() -> None:
    async with sim_and_client() as (sim, client):
        # Setup and farm the puzzle
        hidden_puzzle: Program = Program.to((1, [[61, 1]]))  # assert a coin announcement that the solution tells us
        hidden_puzzle_hash: bytes32 = hidden_puzzle.get_tree_hash()
        p2_either_puzzle: Program = create_viral_backdoor(hidden_puzzle_hash, ACS)
        assert match_viral_backdoor(uncurry_puzzle(p2_either_puzzle)) == (hidden_puzzle_hash, ACS)

        await sim.farm_block(p2_either_puzzle.get_tree_hash())
        p2_either_coin: Coin = (
            await client.get_coin_records_by_puzzle_hashes(
                [p2_either_puzzle.get_tree_hash()], include_spent_coins=False
            )
        )[0].coin

        # Reveal the wrong puzzle
        result: Tuple[MempoolInclusionStatus, Optional[Err]] = await client.push_tx(
            SpendBundle(
                [
                    CoinSpend(
                        p2_either_coin,
                        p2_either_puzzle,
                        solve_viral_backdoor(
                            Program.to(None),
                            hidden_puzzle_reveal=ACS,
                        ),
                    )
                ],
                G2Element(),
            )
        )
        assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)

        # Spend the hidden puzzle (make announcement fail)
        result = await client.push_tx(
            SpendBundle(
                [
                    CoinSpend(
                        p2_either_coin,
                        p2_either_puzzle,
                        solve_viral_backdoor(
                            Program.to(bytes32([0] * 32)),
                            hidden_puzzle_reveal=hidden_puzzle,
                        ),
                    )
                ],
                G2Element(),
            )
        )
        assert result == (MempoolInclusionStatus.FAILED, Err.ASSERT_ANNOUNCE_CONSUMED_FAILED)

        # Spend the inner puzzle
        brick_hash: bytes32 = bytes32([0] * 32)
        wrapped_brick_hash: bytes32 = create_viral_backdoor(hidden_puzzle_hash, brick_hash).get_tree_hash_precalc(brick_hash)
        result = await client.push_tx(
            SpendBundle(
                [
                    CoinSpend(
                        p2_either_coin,
                        p2_either_puzzle,
                        solve_viral_backdoor(
                            Program.to([[51, brick_hash, 0]]),
                        ),
                    )
                ],
                G2Element(),
            )
        )
        assert result == (MempoolInclusionStatus.SUCCESS, None)

        await sim.farm_block()

        assert len(await client.get_coin_records_by_puzzle_hashes([wrapped_brick_hash], include_spent_coins=False)) > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("test_syncing", [True, False])
async def test_vc_lifecycle(test_syncing: bool) -> None:
    async with sim_and_client() as (sim, client):
        RUN_PUZ_PUZ: Program = Program.to([2, 1, None])  # (a 1 ()) takes a puzzle as its solution and runs it with ()
        RUN_PUZ_PUZ_PH: bytes32 = RUN_PUZ_PUZ.get_tree_hash()
        await sim.farm_block(RUN_PUZ_PUZ_PH)
        vc_fund_coin: Coin = (
            await client.get_coin_records_by_puzzle_hashes([RUN_PUZ_PUZ_PH], include_spent_coins=False)
        )[0].coin
        did_fund_coin: Coin = (
            await client.get_coin_records_by_puzzle_hashes([RUN_PUZ_PUZ_PH], include_spent_coins=False)
        )[1].coin

        # Gotta make a DID first
        conditions, coin_spend = launch_conditions_and_coinsol(
            did_fund_coin,
            ACS,
            [],
            uint64(1),
        )
        await client.push_tx(
            SpendBundle(
                [
                    CoinSpend(
                        did_fund_coin,
                        ACS,
                        Program.to((1, conditions)),
                    ),
                    coin_spend,
                ],
                G2Element(),
            )
        )
        await sim.farm_block()

        # Now let's launch the VC
        vc: VerifiedCredential
        dpuz, coin_spends, vc = VerifiedCredential.launch(
            vc_fund_coin,
            coin_spend.coin.name(),
            ACS_PH,
            bytes32([0] * 32),
        )
        result: Tuple[MempoolInclusionStatus, Optional[Err]] = await client.push_tx(
            SpendBundle(
                [
                    CoinSpend(
                        vc_fund_coin,
                        RUN_PUZ_PUZ,
                        dpuz,
                    ),
                    *coin_spends,
                ],
                G2Element(),
            )
        )
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        if test_syncing:
            vc = VerifiedCredential.get_next_from_coin_spend(coin_spends[1])
        assert vc.construct_puzzle(ACS).get_tree_hash() == vc.coin.puzzle_hash
