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
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.vc_wallet.vc_drivers import (
    create_covenant_layer,
    match_covenant_layer,
    solve_covenant_layer,
    create_did_tp,
    match_did_tp,
    solve_did_tp,
    create_did_backdoor,
    match_did_backdoor,
    solve_did_backdoor,
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
async def test_did_backdoor() -> None:
    async with sim_and_client() as (sim, client):
        # Create it with mock singleton info
        brick_hash: bytes32 = bytes32([0] * 32)
        brick_condition: Program = Program.to([51, brick_hash, 0])
        yoink_puz: Program = create_did_backdoor(
            MOCK_LAUNCHER_ID, [brick_condition], MOCK_SINGLETON_MOD_HASH, MOCK_LAUNCHER_HASH
        )
        assert match_did_backdoor(uncurry_puzzle(yoink_puz)) == (MOCK_LAUNCHER_ID, [brick_condition])

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
                        solve_did_backdoor(
                            bad_data,
                            my_coin_id,
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
            Program.to([[[62, std_hash(b"brick" + my_coin_id)]]]),
        )

        # Try to pass the wrong coin id
        result = await client.push_tx(
            SpendBundle(
                [
                    CoinSpend(
                        yoink_coin,
                        yoink_puz,
                        solve_did_backdoor(
                            provider_innerpuzhash,
                            bad_data,
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
                    solve_did_backdoor(
                        provider_innerpuzhash,
                        my_coin_id,
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
async def test_p2_puzzle_or_hidden_puzzle() -> None:
    async with sim_and_client() as (sim, client):
        pass


@pytest.mark.asyncio
async def test_vc_lifecycle() -> None:
    async with sim_and_client() as (sim, client):
        pass
