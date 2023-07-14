from __future__ import annotations

from typing import List, Optional, Tuple

import pytest
from blspy import G2Element

from chia.clvm.spend_sim import CostLogger, sim_and_client
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.spend_bundle import SpendBundle
from chia.util.errors import Err
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.payment import Payment
from chia.wallet.puzzles.singleton_top_layer_v1_1 import (
    launch_conditions_and_coinsol,
    puzzle_for_singleton,
    solution_for_singleton,
)
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.vc_wallet.cr_cat_drivers import CRCAT, ProofsChecker
from chia.wallet.vc_wallet.vc_drivers import (
    ACS_TRANSFER_PROGRAM,
    VerifiedCredential,
    construct_exigent_metadata_layer,
    create_covenant_layer,
    create_did_tp,
    create_std_parent_morpher,
    create_viral_backdoor,
    match_covenant_layer,
    match_did_tp,
    match_viral_backdoor,
    solve_covenant_layer,
    solve_did_tp,
    solve_viral_backdoor,
)

ACS: Program = Program.to([3, (1, "entropy"), 1, None])
ACS_2: Program = Program.to([3, (1, "entropy2"), 1, None])
ACS_PH: bytes32 = ACS.get_tree_hash()
ACS_2_PH: bytes32 = ACS_2.get_tree_hash()
MOCK_SINGLETON_MOD: Program = Program.to([2, 5, 11])
MOCK_SINGLETON_MOD_HASH: bytes32 = MOCK_SINGLETON_MOD.get_tree_hash()
MOCK_LAUNCHER_ID: bytes32 = bytes32([0] * 32)
MOCK_LAUNCHER_HASH: bytes32 = bytes32([1] * 32)
MOCK_SINGLETON: Program = MOCK_SINGLETON_MOD.curry(
    (MOCK_SINGLETON_MOD_HASH, (MOCK_LAUNCHER_ID, MOCK_LAUNCHER_HASH)),
    ACS,
)


@pytest.mark.asyncio
async def test_covenant_layer(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        # Create a puzzle that will not pass the initial covenant check
        FAKE_ACS: Program = Program.to([3, (1, "fake"), 1, None])
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
            cost_logger.add_cost(
                "2x ACS spends - create one coin",
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
                ),
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
                            Program.to(None),
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
                cost_logger.add_cost(
                    "Covenant layer eve spend - one create coin",
                    SpendBundle(
                        [
                            CoinSpend(
                                cov,
                                covenant_puzzle,
                                solve_covenant_layer(
                                    LineageProof(parent_name=parent.parent_coin_info, amount=uint64(parent.amount)),
                                    Program.to(None),
                                    Program.to([[51, covenant_puzzle_hash, cov.amount]]),
                                ),
                            ),
                        ],
                        G2Element(),
                    ),
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
            cost_logger.add_cost(
                "Covenant layer non-eve spend - one create coin",
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
                                Program.to(None),
                                Program.to([[51, covenant_puzzle_hash, new_acs_cov.amount]]),
                            ),
                        ),
                    ],
                    G2Element(),
                ),
            )
        )
        assert result == (MempoolInclusionStatus.SUCCESS, None)


@pytest.mark.asyncio
async def test_did_tp(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        # Make a mock exigent metadata layer
        # Prepends new metadata and new transfer program as REMARK condition to conditions of TP
        # (mod (METADATA TP solution) (a (q . (c (c (q . 1) (c 2 (c 5 ()))) 11)) (a TP (list METADATA () solution))))
        # (a (q 4 (c (q . 1) (c 2 (c 5 ()))) 11) (a 5 (c 2 (c () (c 11 ())))))
        MOCK_OWNERSHIP_LAYER: Program = Program.fromhex(
            "ff02ffff01ff04ffff04ffff0101ffff04ff02ffff04ff05ff80808080ff0b80ffff02ff05ffff04ff02ffff04ff80ffff04ff0bff808080808080"  # noqa: E501
        )
        # Create it with mock singleton info
        transfer_program: Program = create_did_tp(MOCK_SINGLETON_MOD_HASH, MOCK_LAUNCHER_HASH)
        assert match_did_tp(uncurry_puzzle(transfer_program)) == ()
        eml_puzzle: Program = MOCK_OWNERSHIP_LAYER.curry((MOCK_LAUNCHER_ID, None), transfer_program)

        await sim.farm_block(eml_puzzle.get_tree_hash())
        eml_coin: Coin = (
            await client.get_coin_records_by_puzzle_hashes([eml_puzzle.get_tree_hash()], include_spent_coins=False)
        )[0].coin

        # Define parameters for next few spend attempts
        provider_innerpuzhash: bytes32 = ACS_PH
        my_coin_id: bytes32 = eml_coin.name()
        new_metadata: Program = Program.to("SUCCESS")
        new_tp_hash: Program = Program.to("NEW TP").get_tree_hash()
        bad_data: bytes32 = bytes32([0] * 32)

        # Try to update metadata and tp without any announcement
        result: Tuple[MempoolInclusionStatus, Optional[Err]] = await client.push_tx(
            SpendBundle(
                [
                    CoinSpend(
                        eml_coin,
                        eml_puzzle,
                        Program.to(
                            [
                                solve_did_tp(
                                    bad_data,
                                    my_coin_id,
                                    new_metadata,
                                    new_tp_hash,
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
            Program.to([[[62, std_hash(my_coin_id + new_metadata.get_tree_hash() + new_tp_hash)]]]),
        )

        # Try to pass the wrong coin id
        result = await client.push_tx(
            SpendBundle(
                [
                    CoinSpend(
                        eml_coin,
                        eml_puzzle,
                        Program.to(
                            [
                                solve_did_tp(
                                    provider_innerpuzhash,
                                    bad_data,
                                    new_metadata,
                                    new_tp_hash,
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
        successful_spend: SpendBundle = cost_logger.add_cost(
            "Fake Ownership Layer - NFT DID TP",
            SpendBundle(
                [
                    CoinSpend(
                        eml_coin,
                        eml_puzzle,
                        Program.to(
                            [
                                solve_did_tp(
                                    provider_innerpuzhash,
                                    my_coin_id,
                                    new_metadata,
                                    new_tp_hash,
                                )
                            ]
                        ),
                    ),
                    did_authorization_spend,
                ],
                G2Element(),
            ),
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
        assert remark_condition == Program.to([1, (MOCK_LAUNCHER_ID, new_metadata), new_tp_hash])


@pytest.mark.asyncio
async def test_viral_backdoor(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        # Setup and farm the puzzle
        hidden_puzzle: Program = Program.to((1, [[61, 1]]))  # assert a coin announcement that the solution tells us
        hidden_puzzle_hash: bytes32 = hidden_puzzle.get_tree_hash()
        p2_either_puzzle: Program = create_viral_backdoor(hidden_puzzle_hash, ACS_PH)
        assert match_viral_backdoor(uncurry_puzzle(p2_either_puzzle)) == (hidden_puzzle_hash, ACS_PH)

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
                            ACS,
                            Program.to(None),
                            hidden=True,
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
                            hidden_puzzle,
                            Program.to(bytes32([0] * 32)),
                            hidden=True,
                        ),
                    )
                ],
                G2Element(),
            )
        )
        assert result == (MempoolInclusionStatus.FAILED, Err.ASSERT_ANNOUNCE_CONSUMED_FAILED)

        # Spend the inner puzzle
        brick_hash: bytes32 = bytes32([0] * 32)
        wrapped_brick_hash: bytes32 = create_viral_backdoor(
            hidden_puzzle_hash,
            brick_hash,
        ).get_tree_hash()
        result = await client.push_tx(
            cost_logger.add_cost(
                "Viral backdoor spend - one create coin",
                SpendBundle(
                    [
                        CoinSpend(
                            p2_either_coin,
                            p2_either_puzzle,
                            solve_viral_backdoor(
                                ACS,
                                Program.to([[51, brick_hash, 0]]),
                            ),
                        )
                    ],
                    G2Element(),
                ),
            )
        )
        assert result == (MempoolInclusionStatus.SUCCESS, None)

        await sim.farm_block()

        assert len(await client.get_coin_records_by_puzzle_hashes([wrapped_brick_hash], include_spent_coins=False)) > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("test_syncing", [True, False])
async def test_vc_lifecycle(test_syncing: bool, cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        RUN_PUZ_PUZ: Program = Program.to([2, 1, None])  # (a 1 ()) takes a puzzle as its solution and runs it with ()
        RUN_PUZ_PUZ_PH: bytes32 = RUN_PUZ_PUZ.get_tree_hash()
        await sim.farm_block(RUN_PUZ_PUZ_PH)
        await sim.farm_block(RUN_PUZ_PUZ_PH)
        vc_fund_coin: Coin = (
            await client.get_coin_records_by_puzzle_hashes([RUN_PUZ_PUZ_PH], include_spent_coins=False)
        )[0].coin
        did_fund_coin: Coin = (
            await client.get_coin_records_by_puzzle_hashes([RUN_PUZ_PUZ_PH], include_spent_coins=False)
        )[1].coin
        other_did_fund_coin: Coin = (
            await client.get_coin_records_by_puzzle_hashes([RUN_PUZ_PUZ_PH], include_spent_coins=False)
        )[2].coin

        # Gotta make some DIDs first
        launcher_id: bytes32
        lineage_proof: LineageProof
        did: Coin
        other_launcher_id: bytes32
        other_lineage_proof: LineageProof
        other_did: Coin
        for fund_coin in (did_fund_coin, other_did_fund_coin):
            conditions, launcher_spend = launch_conditions_and_coinsol(
                fund_coin,
                ACS,
                [],
                uint64(1),
            )
            await client.push_tx(
                SpendBundle(
                    [
                        CoinSpend(
                            fund_coin,
                            RUN_PUZ_PUZ,
                            Program.to((1, conditions)),
                        ),
                        launcher_spend,
                    ],
                    G2Element(),
                )
            )
            await sim.farm_block()
            if fund_coin == did_fund_coin:
                launcher_id = launcher_spend.coin.name()
                lineage_proof = LineageProof(
                    parent_name=launcher_spend.coin.parent_coin_info,
                    amount=uint64(launcher_spend.coin.amount),
                )
                did = (await client.get_coin_records_by_parent_ids([launcher_id], include_spent_coins=False))[0].coin
            else:
                other_launcher_id = launcher_spend.coin.name()
                other_lineage_proof = LineageProof(
                    parent_name=launcher_spend.coin.parent_coin_info,
                    amount=uint64(launcher_spend.coin.amount),
                )
                other_did = (
                    await client.get_coin_records_by_parent_ids([other_launcher_id], include_spent_coins=False)
                )[0].coin

        # Now let's launch the VC
        vc: VerifiedCredential
        dpuz, coin_spends, vc = VerifiedCredential.launch(
            vc_fund_coin,
            launcher_id,
            ACS_PH,
            [bytes32([0] * 32)],
        )
        result: Tuple[MempoolInclusionStatus, Optional[Err]] = await client.push_tx(
            cost_logger.add_cost(
                "Launch VC",
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
                ),
            )
        )
        await sim.farm_block()
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        if test_syncing:
            vc = VerifiedCredential.get_next_from_coin_spend(coin_spends[1])
            assert VerifiedCredential.is_vc(uncurry_puzzle(coin_spends[1].puzzle_reveal.to_program()))[0]
        assert vc.construct_puzzle().get_tree_hash() == vc.coin.puzzle_hash
        assert len(await client.get_coin_records_by_puzzle_hashes([vc.coin.puzzle_hash], include_spent_coins=False)) > 0

        # Update the proofs with a proper announcement
        NEW_PROOFS: Program = Program.to((("test", True), ("test2", True)))
        MALICIOUS_PROOFS: Program = Program.to(("malicious", True))
        NEW_PROOF_HASH: bytes32 = NEW_PROOFS.get_tree_hash()
        expected_announcement, update_spend, vc = vc.do_spend(
            ACS,
            Program.to([[51, ACS_2_PH, vc.coin.amount], vc.magic_condition_for_new_proofs(NEW_PROOF_HASH, ACS_PH)]),
            new_proof_hash=NEW_PROOF_HASH,
        )
        for use_did, correct_did in ((False, None), (True, False), (True, True)):
            result = await client.push_tx(
                cost_logger.add_cost(
                    "Update VC proofs (eve covenant spend) - DID providing announcement",
                    SpendBundle(
                        [
                            *(
                                [
                                    CoinSpend(
                                        did if correct_did else other_did,
                                        puzzle_for_singleton(
                                            launcher_id if correct_did else other_launcher_id,
                                            ACS,
                                        ),
                                        solution_for_singleton(
                                            lineage_proof if correct_did else other_lineage_proof,
                                            uint64(did.amount) if correct_did else uint64(other_did.amount),
                                            Program.to(
                                                [
                                                    [51, ACS_PH, did.amount if correct_did else other_did.amount],
                                                    [62, expected_announcement],
                                                ]
                                            ),
                                        ),
                                    )
                                ]
                                if use_did
                                else []
                            ),
                            update_spend,
                        ],
                        G2Element(),
                    ),
                )
            )
            if use_did:
                if correct_did:
                    assert result == (MempoolInclusionStatus.SUCCESS, None)
                else:
                    assert result == (MempoolInclusionStatus.FAILED, Err.ASSERT_ANNOUNCE_CONSUMED_FAILED)
            else:
                assert result == (MempoolInclusionStatus.FAILED, Err.ASSERT_ANNOUNCE_CONSUMED_FAILED)
        await sim.farm_block()
        if test_syncing:
            vc = VerifiedCredential.get_next_from_coin_spend(update_spend)
            assert VerifiedCredential.is_vc(uncurry_puzzle(update_spend.puzzle_reveal.to_program()))[0]

        # Now lets farm a funds for some CR-CATs
        await sim.farm_block(RUN_PUZ_PUZ_PH)
        await sim.farm_block(RUN_PUZ_PUZ_PH)
        cr_fund_coin_1: Coin = (
            await client.get_coin_records_by_puzzle_hashes([RUN_PUZ_PUZ_PH], include_spent_coins=False)
        )[0].coin
        cr_fund_coin_2: Coin = (
            await client.get_coin_records_by_puzzle_hashes([RUN_PUZ_PUZ_PH], include_spent_coins=False)
        )[1].coin
        cr_fund_coin_3: Coin = (
            await client.get_coin_records_by_puzzle_hashes([RUN_PUZ_PUZ_PH], include_spent_coins=False)
        )[2].coin
        cr_fund_coin_4: Coin = (
            await client.get_coin_records_by_puzzle_hashes([RUN_PUZ_PUZ_PH], include_spent_coins=False)
        )[3].coin

        # Launch the CR-CATs
        malicious_cr_1: CRCAT
        malicious_cr_2: CRCAT
        for cr_coin_1, cr_coin_2 in ((cr_fund_coin_1, cr_fund_coin_2), (cr_fund_coin_3, cr_fund_coin_4)):
            if cr_coin_1 == cr_fund_coin_1:
                proofs = ["malicious"]
            else:
                proofs = ["test", "test2"]
            proofs_checker: ProofsChecker = ProofsChecker(proofs)
            AUTHORIZED_PROVIDERS: List[bytes32] = [launcher_id]
            dpuz_1, launch_crcat_spend_1, cr_1 = CRCAT.launch(
                cr_coin_1,
                Payment(ACS_PH, uint64(cr_coin_1.amount), []),
                Program.to(None),
                Program.to(None),
                AUTHORIZED_PROVIDERS,
                proofs_checker.as_program(),
            )
            dpuz_2, launch_crcat_spend_2, cr_2 = CRCAT.launch(
                cr_coin_2,
                Payment(ACS_PH, uint64(cr_coin_2.amount), []),
                Program.to(None),
                Program.to(None),
                AUTHORIZED_PROVIDERS,
                proofs_checker.as_program(),
            )
            result = await client.push_tx(
                SpendBundle(
                    [
                        CoinSpend(
                            cr_coin_1,
                            RUN_PUZ_PUZ,
                            dpuz_1,
                        ),
                        CoinSpend(
                            cr_coin_2,
                            RUN_PUZ_PUZ,
                            dpuz_2,
                        ),
                        launch_crcat_spend_1,
                        launch_crcat_spend_2,
                    ],
                    G2Element(),
                )
            )
            assert result == (MempoolInclusionStatus.SUCCESS, None)
            await sim.farm_block()
            if test_syncing:
                cr_1 = CRCAT.get_next_from_coin_spend(launch_crcat_spend_1)[0]
                cr_2 = CRCAT.get_next_from_coin_spend(launch_crcat_spend_2)[0]
            assert len(await client.get_coin_records_by_names([cr_1.coin.name()], include_spent_coins=False)) > 0
            assert len(await client.get_coin_records_by_names([cr_2.coin.name()], include_spent_coins=False)) > 0
            if cr_coin_1 == cr_fund_coin_1:
                malicious_cr_1 = cr_1
                malicious_cr_2 = cr_2

        for error in (
            "forget_vc",
            "make_banned_announcement",
            "use_malicious_cats",
            "attempt_honest_cat_piggyback",
            None,
        ):
            # The CR-CAT coin spends
            expected_announcements, cr_cat_spends, new_crcats = CRCAT.spend_many(
                [
                    (
                        cr_1 if error != "use_malicious_cats" else malicious_cr_1,
                        ACS,
                        Program.to(
                            [
                                [
                                    51,
                                    ACS_PH,
                                    cr_1.coin.amount if error != "use_malicious_cats" else malicious_cr_1.coin.amount,
                                ],
                                *([[60, b"\xcd" + bytes(32)]] if error == "make_banned_announcement" else []),
                            ]
                        ),
                    ),
                    (
                        cr_2 if error != "use_malicious_cats" else malicious_cr_2,
                        ACS,
                        Program.to(
                            [
                                [
                                    51,
                                    ACS_PH,
                                    cr_2.coin.amount if error != "use_malicious_cats" else malicious_cr_2.coin.amount,
                                ]
                            ]
                        ),
                    ),
                ],
                NEW_PROOFS if error != "use_malicious_cats" else MALICIOUS_PROOFS,
                Program.to(None),
                launcher_id,
                vc.launcher_id,
                vc.wrap_inner_with_backdoor().get_tree_hash(),
            )

            # Try to spend the coin to ourselves
            _, auth_spend, new_vc = vc.do_spend(
                ACS_2,
                Program.to(
                    [
                        [51, ACS_PH, vc.coin.amount],
                        [
                            62,
                            cr_1.expected_announcement()
                            if error not in ["use_malicious_cats", "attempt_honest_cat_piggyback"]
                            else malicious_cr_1.expected_announcement(),
                        ],
                        [
                            62,
                            cr_2.expected_announcement()
                            if error not in ["use_malicious_cats", "attempt_honest_cat_piggyback"]
                            else malicious_cr_2.expected_announcement(),
                        ],
                        *([61, a] for a in expected_announcements),
                        vc.standard_magic_condition(),
                    ]
                ),
            )

            result = await client.push_tx(
                cost_logger.add_cost(
                    "CR-CATx2 w/ VC announcement, Standard Proof Checker (2 flags)",
                    SpendBundle(
                        [
                            *cr_cat_spends,
                            *([auth_spend] if error != "forget_vc" else []),
                        ],
                        G2Element(),
                    ),
                )
            )
            if error is None:
                assert result == (MempoolInclusionStatus.SUCCESS, None)
                if test_syncing:
                    assert all(
                        CRCAT.is_cr_cat(uncurry_puzzle(spend.puzzle_reveal.to_program())) for spend in cr_cat_spends
                    )
                    new_crcats = [crcat for spend in cr_cat_spends for crcat in CRCAT.get_next_from_coin_spend(spend)]
                    vc = VerifiedCredential.get_next_from_coin_spend(auth_spend)
                else:
                    vc = new_vc
                await sim.farm_block()
            elif error in ["forget_vc", "use_malicious_cats", "attempt_honest_cat_piggyback"]:
                assert result == (MempoolInclusionStatus.FAILED, Err.ASSERT_ANNOUNCE_CONSUMED_FAILED)
            elif error == "make_banned_announcement":
                assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)

        save_point: uint32 = sim.block_height
        # Yoink the coin away from the inner puzzle
        for correct_did in (False, True):
            new_did = (
                (await client.get_coin_records_by_parent_ids([did.name()], include_spent_coins=False))[0].coin
                if correct_did
                else other_did
            )
            expected_announcement, yoink_spend = vc.activate_backdoor(ACS_PH)
            result = await client.push_tx(
                cost_logger.add_cost(
                    "VC yoink by DID provider",
                    SpendBundle(
                        [
                            CoinSpend(
                                new_did,
                                puzzle_for_singleton(
                                    launcher_id if correct_did else other_launcher_id,
                                    ACS,
                                ),
                                solution_for_singleton(
                                    LineageProof(
                                        parent_name=did.parent_coin_info,
                                        inner_puzzle_hash=ACS_PH,
                                        amount=uint64(did.amount),
                                    )
                                    if correct_did
                                    else other_lineage_proof,
                                    uint64(new_did.amount),
                                    Program.to([[51, ACS_PH, new_did.amount], [62, expected_announcement]]),
                                ),
                            ),
                            yoink_spend,
                        ],
                        G2Element(),
                    ),
                )
            )
            if correct_did:
                assert result == (MempoolInclusionStatus.SUCCESS, None)
                await sim.farm_block()
                if test_syncing:
                    with pytest.raises(ValueError):
                        VerifiedCredential.get_next_from_coin_spend(yoink_spend)
            else:
                assert result == (MempoolInclusionStatus.FAILED, Err.ASSERT_ANNOUNCE_CONSUMED_FAILED)

        # Verify the end state
        new_singletons_puzzle_reveal: Program = puzzle_for_singleton(
            vc.launcher_id,
            construct_exigent_metadata_layer(
                None,
                ACS_TRANSFER_PROGRAM,
                ACS,
            ),
        )

        assert (
            len(
                await client.get_coin_records_by_puzzle_hashes(
                    [new_singletons_puzzle_reveal.get_tree_hash()], include_spent_coins=False
                )
            )
            > 0
        )
        assert (
            len(
                await client.get_coin_records_by_names(
                    [crcat.coin.name() for crcat in new_crcats], include_spent_coins=False
                )
            )
            == 2
        )

        # Rewind to pre-yoink state
        await sim.rewind(save_point)

        _, clear_spend, _ = vc.do_spend(
            ACS,
            Program.to(
                [
                    [51, ACS_PH, vc.coin.amount],
                    [
                        -10,
                        vc.eml_lineage_proof.to_program(),
                        [
                            Program.to(vc.eml_lineage_proof.parent_proof_hash),
                            vc.launcher_id,
                        ],
                        ACS_TRANSFER_PROGRAM.get_tree_hash(),
                    ],
                ]
            ),
        )
        result = await client.push_tx(
            cost_logger.add_cost(
                "VC clear by user",
                SpendBundle(
                    [clear_spend],
                    G2Element(),
                ),
            )
        )
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()
        if test_syncing:
            with pytest.raises(ValueError):
                VerifiedCredential.get_next_from_coin_spend(clear_spend)

        # Verify the end state
        cleared_singletons_puzzle_reveal: Program = puzzle_for_singleton(
            vc.launcher_id,
            construct_exigent_metadata_layer(
                None,
                ACS_TRANSFER_PROGRAM,
                vc.wrap_inner_with_backdoor(),
            ),
        )

        assert (
            len(
                await client.get_coin_records_by_puzzle_hashes(
                    [cleared_singletons_puzzle_reveal.get_tree_hash()], include_spent_coins=False
                )
            )
            > 0
        )
