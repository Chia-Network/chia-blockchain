from __future__ import annotations

import re

import pytest
from chia_rs import AugSchemeMPL, G2Element
from chia_rs.sized_ints import uint64

from chia._tests.util.spend_sim import CostLogger, sim_and_client
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import make_spend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.errors import Err
from chia.util.hash import std_hash
from chia.wallet.conditions import CreateCoinAnnouncement
from chia.wallet.puzzles.custody.custody_architecture import (
    DelegatedPuzzleAndSolution,
    MemberHint,
    PuzzleWithRestrictions,
)
from chia.wallet.puzzles.custody.member_puzzles import (
    BLSWithTaprootMember,
    FixedPuzzleMember,
    SingletonMember,
)
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    calculate_synthetic_public_key,
    puzzle_for_synthetic_public_key,
)
from chia.wallet.singleton import SINGLETON_LAUNCHER_PUZZLE, SINGLETON_LAUNCHER_PUZZLE_HASH, SINGLETON_TOP_LAYER_MOD
from chia.wallet.wallet_spend_bundle import WalletSpendBundle


@pytest.mark.anyio
async def test_bls_with_taproot_member(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        delegated_puzzle = Program.to(1)
        delegated_puzzle_hash = delegated_puzzle.get_tree_hash()
        sk = AugSchemeMPL.key_gen(bytes.fromhex(str(0) * 64))

        bls_with_taproot_member = BLSWithTaprootMember(public_key=sk.public_key(), hidden_puzzle=delegated_puzzle)
        bls_puzzle = PuzzleWithRestrictions(nonce=0, restrictions=[], puzzle=bls_with_taproot_member)
        memo = MemberHint(
            puzhash=bls_puzzle.puzzle.puzzle_hash(0),
            memo=bls_puzzle.puzzle.memo(0),
        )

        assert bls_puzzle.memo() == Program.to(
            (
                bls_puzzle.spec_namespace,
                [
                    bls_puzzle.nonce,
                    [],
                    0,
                    memo.to_program(),
                ],
            )
        )

        # Farm and find coin
        await sim.farm_block(bls_puzzle.puzzle_hash())
        coin = (await client.get_coin_records_by_puzzle_hashes([bls_puzzle.puzzle_hash()], include_spent_coins=False))[
            0
        ].coin
        block_height = sim.block_height

        # Create an announcements to be asserted in the delegated puzzle
        announcement = CreateCoinAnnouncement(msg=b"foo", coin_id=coin.name())

        # test non-taproot spend
        sb = WalletSpendBundle(
            [
                make_spend(
                    coin,
                    bls_puzzle.puzzle_reveal(),
                    bls_puzzle.solve(
                        [],
                        [],
                        bls_with_taproot_member.solve(),
                        DelegatedPuzzleAndSolution(
                            puzzle=delegated_puzzle,
                            solution=Program.to(
                                [
                                    announcement.to_program(),
                                    announcement.corresponding_assertion().to_program(),
                                ]
                            ),
                        ),
                    ),
                )
            ],
            bls_with_taproot_member.sign_with_synthetic_secret_key(
                sk, delegated_puzzle_hash + coin.name() + DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA
            ),
        )
        result = await client.push_tx(
            cost_logger.add_cost(
                "BLSTaprootMember spendbundle",
                sb,
            )
        )
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()
        await sim.rewind(block_height)

        # test taproot spend
        sb = WalletSpendBundle(
            [
                make_spend(
                    coin,
                    bls_puzzle.puzzle_reveal(),
                    bls_puzzle.solve(
                        [],
                        [],
                        bls_with_taproot_member.solve(True),
                        DelegatedPuzzleAndSolution(
                            puzzle=delegated_puzzle,
                            solution=Program.to(
                                [
                                    announcement.to_program(),
                                    announcement.corresponding_assertion().to_program(),
                                ]
                            ),
                        ),
                    ),
                )
            ],
            G2Element(),  # no signature required in our test hidden_puzzle
        )
        result = await client.push_tx(
            cost_logger.add_cost(
                "BLSTaprootMember spendbundle",
                sb,
            )
        )
        assert result == (MempoolInclusionStatus.SUCCESS, None)

        # test invalid taproot spend
        illegal_taproot_puzzle = Program.to([1, [51, Program.to(1).get_tree_hash(), 1]])
        assert illegal_taproot_puzzle.run([]) == Program.to([[51, Program.to(1).get_tree_hash(), 1]])
        bls_with_taproot_member = BLSWithTaprootMember(public_key=sk.public_key(), hidden_puzzle=illegal_taproot_puzzle)
        bls_puzzle = PuzzleWithRestrictions(nonce=0, restrictions=[], puzzle=bls_with_taproot_member)
        memo = MemberHint(
            puzhash=bls_puzzle.puzzle.puzzle_hash(0),
            memo=bls_puzzle.puzzle.memo(0),
        )

        assert bls_puzzle.memo() == Program.to(
            (
                bls_puzzle.spec_namespace,
                [
                    bls_puzzle.nonce,
                    [],
                    0,
                    memo.to_program(),
                ],
            )
        )

        # Farm and find coin
        await sim.farm_block(bls_puzzle.puzzle_hash())
        coin = (await client.get_coin_records_by_puzzle_hashes([bls_puzzle.puzzle_hash()], include_spent_coins=False))[
            0
        ].coin
        block_height = sim.block_height

        sb = WalletSpendBundle(
            [
                make_spend(
                    coin,
                    bls_puzzle.puzzle_reveal(),
                    bls_puzzle.solve(
                        [],
                        [],
                        bls_with_taproot_member.solve(True),
                        DelegatedPuzzleAndSolution(
                            puzzle=delegated_puzzle,
                            solution=Program.to(
                                [
                                    announcement.to_program(),
                                    announcement.corresponding_assertion().to_program(),
                                ]
                            ),
                        ),
                    ),
                )
            ],
            G2Element(),  # no signature required in our test hidden_puzzle
        )
        result = await client.push_tx(
            cost_logger.add_cost(
                "BLSTaprootMember spendbundle",
                sb,
            )
        )
        assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)
        assert bls_with_taproot_member.hidden_puzzle is not None
        assert bls_with_taproot_member.public_key is not None
        synthetic_public_key = calculate_synthetic_public_key(
            bls_with_taproot_member.public_key, bls_with_taproot_member.hidden_puzzle.get_tree_hash()
        )
        bls_with_taproot_member_synthetic = BLSWithTaprootMember(synthetic_key=synthetic_public_key)
        assert bls_with_taproot_member.puzzle(0) == bls_with_taproot_member_synthetic.puzzle(0)

        # test some errors
        with pytest.raises(
            ValueError, match=re.escape("Must specify either the synthetic key or public key and hidden puzzle")
        ):
            BLSWithTaprootMember(public_key=sk.public_key())

        with pytest.raises(
            ValueError, match=re.escape("Hidden puzzle must be specified to sign with synthetic secret key")
        ):
            BLSWithTaprootMember(synthetic_key=sk.public_key()).sign_with_synthetic_secret_key(
                original_secret_key=sk, message=b""
            )

        with pytest.raises(ValueError, match=re.escape("Hidden puzzle or original key are unknown")):
            BLSWithTaprootMember(synthetic_key=sk.public_key()).solve(use_hidden_puzzle=True)


@pytest.mark.anyio
async def test_singleton_member(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        delegated_puzzle = Program.to(1)

        sk = AugSchemeMPL.key_gen(bytes.fromhex(str(0) * 64))
        pk = sk.public_key()
        puz = puzzle_for_synthetic_public_key(pk)
        # Farm and find coin
        await sim.farm_block(puz.get_tree_hash())
        coin = (await client.get_coin_records_by_puzzle_hashes([puz.get_tree_hash()], include_spent_coins=False))[
            0
        ].coin

        launcher_coin = Coin(coin.name(), SINGLETON_LAUNCHER_PUZZLE_HASH, uint64(1))
        singleton_member = SingletonMember(singleton_id=launcher_coin.name())
        singleton_member_puzzle = PuzzleWithRestrictions(nonce=0, restrictions=[], puzzle=singleton_member)

        singleton_struct = (
            SINGLETON_TOP_LAYER_MOD.get_tree_hash(),
            (launcher_coin.name(), SINGLETON_LAUNCHER_PUZZLE_HASH),
        )
        singleton_innerpuz = Program.to(1)
        singleton_puzzle = SINGLETON_TOP_LAYER_MOD.curry(singleton_struct, singleton_innerpuz)
        launcher_solution = Program.to([singleton_puzzle.get_tree_hash(), 1, 0])

        conditions_list = [
            [51, SINGLETON_LAUNCHER_PUZZLE_HASH, 1],
            [61, std_hash(launcher_coin.name() + launcher_solution.get_tree_hash())],
        ]
        solution = Program.to([0, (1, conditions_list), 0])

        msg = (
            bytes(solution.rest().first().get_tree_hash()) + coin.name() + DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA
        )
        sig = sk.sign(msg)
        sb = WalletSpendBundle(
            [
                make_spend(coin, puz, solution),
                make_spend(launcher_coin, SINGLETON_LAUNCHER_PUZZLE, launcher_solution),
            ],
            sig,
        )
        result = await client.push_tx(
            cost_logger.add_cost(
                "BLSMember spendbundle",
                sb,
            )
        )
        assert result == (MempoolInclusionStatus.SUCCESS, None)

        await sim.farm_block()

        singleton_coin = (
            await client.get_coin_records_by_puzzle_hashes(
                [singleton_puzzle.get_tree_hash()], include_spent_coins=False
            )
        )[0].coin

        memo = MemberHint(
            puzhash=singleton_member_puzzle.puzzle.puzzle_hash(0),
            memo=singleton_member_puzzle.puzzle.memo(0),
        )

        assert singleton_member_puzzle.memo() == Program.to(
            (
                singleton_member_puzzle.spec_namespace,
                [
                    singleton_member_puzzle.nonce,
                    [],
                    0,
                    memo.to_program(),
                ],
            )
        )

        # Farm and find coin
        await sim.farm_block(singleton_member_puzzle.puzzle_hash())
        coin = (
            await client.get_coin_records_by_puzzle_hashes(
                [singleton_member_puzzle.puzzle_hash()], include_spent_coins=False
            )
        )[0].coin
        block_height = sim.block_height

        # Create an announcements to be asserted in the delegated puzzle
        announcement = CreateCoinAnnouncement(msg=b"foo", coin_id=coin.name())

        # Make solution for singleton
        fullsol = Program.to(
            [
                [launcher_coin.parent_coin_info, 1],
                1,
                [
                    [51, Program.to(1).get_tree_hash(), 1],
                    [
                        66,
                        0x17,
                        delegated_puzzle.get_tree_hash(),
                        coin.name(),
                    ],  # 00010111  - puzzle sender, coin receiver
                ],  # create approval message to singleton member puzzle
            ]
        )

        sb = WalletSpendBundle(
            [
                make_spend(
                    coin,
                    singleton_member_puzzle.puzzle_reveal(),
                    singleton_member_puzzle.solve(
                        [],
                        [],
                        singleton_member.solve(singleton_inner_puzzle_hash=singleton_innerpuz.get_tree_hash()),
                        DelegatedPuzzleAndSolution(
                            puzzle=delegated_puzzle,
                            solution=Program.to(
                                [
                                    announcement.to_program(),
                                    announcement.corresponding_assertion().to_program(),
                                ]
                            ),
                        ),
                    ),
                ),
                make_spend(
                    singleton_coin,
                    singleton_puzzle,
                    fullsol,
                ),
            ],
            G2Element(),
        )
        result = await client.push_tx(
            cost_logger.add_cost(
                "BLSMember spendbundle",
                sb,
            )
        )
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()
        await sim.rewind(block_height)


@pytest.mark.anyio
async def test_fixed_puzzle_member(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        delegated_puzzle = Program.to(1)
        delegated_puzzle_hash = delegated_puzzle.get_tree_hash()

        fixed_puzzle_member = FixedPuzzleMember(fixed_puzzle_hash=delegated_puzzle_hash)
        bls_puzzle = PuzzleWithRestrictions(nonce=0, restrictions=[], puzzle=fixed_puzzle_member)
        memo = MemberHint(
            puzhash=bls_puzzle.puzzle.puzzle_hash(0),
            memo=bls_puzzle.puzzle.memo(0),
        )

        assert bls_puzzle.memo() == Program.to(
            (
                bls_puzzle.spec_namespace,
                [
                    bls_puzzle.nonce,
                    [],
                    0,
                    memo.to_program(),
                ],
            )
        )

        # Farm and find coin
        await sim.farm_block(bls_puzzle.puzzle_hash())
        coin = (await client.get_coin_records_by_puzzle_hashes([bls_puzzle.puzzle_hash()], include_spent_coins=False))[
            0
        ].coin
        block_height = sim.block_height

        # Create an announcements to be asserted in the delegated puzzle
        announcement = CreateCoinAnnouncement(msg=b"foo", coin_id=coin.name())

        sb = WalletSpendBundle(
            [
                make_spend(
                    coin,
                    bls_puzzle.puzzle_reveal(),
                    bls_puzzle.solve(
                        [],
                        [],
                        Program.to(0),
                        DelegatedPuzzleAndSolution(
                            puzzle=Program.to(0),  # not the fixed puzzle
                            solution=Program.to(
                                [
                                    announcement.to_program(),
                                    announcement.corresponding_assertion().to_program(),
                                ]
                            ),
                        ),
                    ),
                )
            ],
            G2Element(),
        )
        result = await client.push_tx(
            cost_logger.add_cost(
                "BLSMember spendbundle",
                sb,
            )
        )
        assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)
        await sim.farm_block()
        await sim.rewind(block_height)

        sb = WalletSpendBundle(
            [
                make_spend(
                    coin,
                    bls_puzzle.puzzle_reveal(),
                    bls_puzzle.solve(
                        [],
                        [],
                        fixed_puzzle_member.solve(),
                        DelegatedPuzzleAndSolution(
                            puzzle=delegated_puzzle,  # the fixed puzzle
                            solution=Program.to(
                                [
                                    announcement.to_program(),
                                    announcement.corresponding_assertion().to_program(),
                                ]
                            ),
                        ),
                    ),
                )
            ],
            G2Element(),
        )
        result = await client.push_tx(
            cost_logger.add_cost(
                "BLSMember spendbundle",
                sb,
            )
        )
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()
