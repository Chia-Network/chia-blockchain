from __future__ import annotations

import itertools
from typing import List

import pytest
from chia_rs import AugSchemeMPL, G2Element
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from chia._tests.clvm.test_custody_architecture import ACSDPuzValidator
from chia._tests.util.spend_sim import CostLogger, sim_and_client
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import make_spend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.hash import std_hash
from chia.wallet.conditions import CreateCoinAnnouncement
from chia.wallet.puzzles.custody.custody_architecture import (
    DelegatedPuzzleAndSolution,
    MemberOrDPuz,
    MofN,
    ProvenSpend,
    PuzzleHint,
    PuzzleWithRestrictions,
    Restriction,
)
from chia.wallet.puzzles.custody.member_puzzles.member_puzzles import BLSMember, PasskeyMember, SECPR1Member, SECPK1Member
from chia.wallet.wallet_spend_bundle import WalletSpendBundle


@pytest.mark.anyio
async def test_bls_member(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        delegated_puzzle = Program.to(1)
        delegated_puzzle_hash = delegated_puzzle.get_tree_hash()
        sk = AugSchemeMPL.key_gen(bytes.fromhex(str(0) * 64))

        bls_puzzle = PuzzleWithRestrictions(0, [], BLSMember(sk.public_key()))
        memo = PuzzleHint(
            bls_puzzle.puzzle.puzzle_hash(0),
            bls_puzzle.puzzle.memo(0),
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

        # Get signature for AGG_SIG_ME
        sig = sk.sign(delegated_puzzle_hash + coin.name() + DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA)
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
                            delegated_puzzle,
                            Program.to(
                                [
                                    announcement.to_program(),
                                    announcement.corresponding_assertion().to_program(),
                                ]
                            ),
                        ),
                    ),
                )
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
        await sim.rewind(block_height)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "with_restrictions",
    [True, False],
)
async def test_2_of_4_bls_members(cost_logger: CostLogger, with_restrictions: bool) -> None:
    """
    This tests the BLS Member puzzle with 4 different keys.
    It loops through every combination inside an M of N Puzzle where
    m = 2
    n = 4
    and every member puzzle is a unique BLSMember puzzle.
    """
    restrictions: List[Restriction[MemberOrDPuz]] = [ACSDPuzValidator()] if with_restrictions else []
    async with sim_and_client() as (sim, client):
        m = 2
        n = 4
        keys = []
        delegated_puzzle = Program.to(1)
        delegated_puzzle_hash = delegated_puzzle.get_tree_hash()
        for _ in range(0, n):
            sk = AugSchemeMPL.key_gen(bytes.fromhex(str(n) * 64))
            keys.append(sk)
        m_of_n = PuzzleWithRestrictions(
            0,
            [],
            MofN(
                m, [PuzzleWithRestrictions(n_i, restrictions, BLSMember(keys[n_i].public_key())) for n_i in range(0, n)]
            ),
        )

        # Farm and find coin
        await sim.farm_block(m_of_n.puzzle_hash())
        m_of_n_coin = (
            await client.get_coin_records_by_puzzle_hashes([m_of_n.puzzle_hash()], include_spent_coins=False)
        )[0].coin
        block_height = sim.block_height

        # Create an announcements to be asserted in the delegated puzzle
        announcement = CreateCoinAnnouncement(msg=b"foo", coin_id=m_of_n_coin.name())

        # Test a spend of every combination of m of n
        for indexes in itertools.combinations(range(0, n), m):
            proven_spends = {
                PuzzleWithRestrictions(index, restrictions, BLSMember(keys[index].public_key())).puzzle_hash(
                    _top_level=False
                ): ProvenSpend(
                    PuzzleWithRestrictions(index, restrictions, BLSMember(keys[index].public_key())).puzzle_reveal(
                        _top_level=False
                    ),
                    PuzzleWithRestrictions(index, restrictions, BLSMember(keys[index].public_key())).solve(
                        [],
                        [Program.to(None)] if with_restrictions else [],
                        Program.to(0),  # no solution required for this member puzzle, only sig
                    ),
                )
                for index in indexes
            }
            sig = G2Element()
            for index in indexes:
                sig = AugSchemeMPL.aggregate(
                    [
                        sig,
                        keys[index].sign(
                            delegated_puzzle_hash + m_of_n_coin.name() + DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA
                        ),
                    ]
                )
            assert isinstance(m_of_n.puzzle, MofN)
            sb = WalletSpendBundle(
                [
                    make_spend(
                        m_of_n_coin,
                        m_of_n.puzzle_reveal(),
                        m_of_n.solve(
                            [],
                            [],
                            m_of_n.puzzle.solve(proven_spends),  # pylint: disable=no-member
                            DelegatedPuzzleAndSolution(
                                delegated_puzzle,
                                Program.to(
                                    [
                                        announcement.to_program(),
                                        announcement.corresponding_assertion().to_program(),
                                    ]
                                ),
                            ),
                        ),
                    )
                ],
                sig,
            )
            result = await client.push_tx(
                cost_logger.add_cost(
                    f"M={m}, N={n}, indexes={indexes}{'w/ res.' if with_restrictions else ''}",
                    sb,
                )
            )
            assert result == (MempoolInclusionStatus.SUCCESS, None)
            await sim.farm_block()
            await sim.rewind(block_height)


@pytest.mark.anyio
async def test_passkey_member(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        delegated_puzzle = Program.to(1)
        delegated_puzzle_hash = delegated_puzzle.get_tree_hash()

        # setup keys
        seed = 0x1A62C9636D1C9DB2E7D564D0C11603BF456AAD25AA7B12BDFD762B4E38E7EDC6
        secp_sk = ec.derive_private_key(seed, ec.SECP256R1(), default_backend())
        secp_pk = secp_sk.public_key().public_bytes(Encoding.X962, PublicFormat.CompressedPoint)

        passkey_member = PasskeyMember(secp_pk, sim.defaults.GENESIS_CHALLENGE)

        passkey_puzzle = PuzzleWithRestrictions(0, [], passkey_member)

        # Farm and find coin
        await sim.farm_block(passkey_puzzle.puzzle_hash())
        coin = (
            await client.get_coin_records_by_puzzle_hashes([passkey_puzzle.puzzle_hash()], include_spent_coins=False)
        )[0].coin
        block_height = sim.block_height

        # Create an announcements to be asserted in the delegated puzzle
        announcement = CreateCoinAnnouncement(msg=b"foo", coin_id=coin.name())

        # Get signature for AGG_SIG_ME
        coin_id = coin.name()
        authenticator_data = b"foo"
        client_data = {"challenge": passkey_member.create_message(delegated_puzzle_hash, coin_id)}
        client_data_hash = std_hash(PasskeyMember.format_client_data_as_str(client_data).encode("utf8"))
        signature_message = authenticator_data + client_data_hash
        der_sig = secp_sk.sign(
            signature_message,
            # The type stubs are weird here, `deterministic_signing` is assuredly an argument
            ec.ECDSA(hashes.SHA256(), deterministic_signing=True),  # type: ignore[call-arg]
        )
        r, s = decode_dss_signature(der_sig)
        sig = r.to_bytes(32, byteorder="big") + s.to_bytes(32, byteorder="big")
        sb = WalletSpendBundle(
            [
                make_spend(
                    coin,
                    passkey_puzzle.puzzle_reveal(),
                    passkey_puzzle.solve(
                        [],
                        [],
                        passkey_member.solve(
                            authenticator_data,
                            client_data,
                            sig,
                            coin_id,
                        ),
                        DelegatedPuzzleAndSolution(
                            delegated_puzzle,
                            Program.to(
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
                "Passkey spendbundle",
                sb,
            )
        )
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()
        await sim.rewind(block_height)


@pytest.mark.anyio
async def test_secp256r1_member(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        delegated_puzzle = Program.to(1)
        delegated_puzzle_hash = delegated_puzzle.get_tree_hash()

        # setup keys
        seed = 0x1A62C9636D1C9DB2E7D564D0C11603BF456AAD25AA7B12BDFD762B4E38E7EDC6
        secp_sk = ec.derive_private_key(seed, ec.SECP256R1(), default_backend())
        secp_pk = secp_sk.public_key().public_bytes(Encoding.X962, PublicFormat.CompressedPoint)

        secpr1_member = SECPR1Member(secp_pk)

        secpr1_puzzle = PuzzleWithRestrictions(0, [], secpr1_member)

        # Farm and find coin
        await sim.farm_block(secpr1_puzzle.puzzle_hash())
        coin = (
            await client.get_coin_records_by_puzzle_hashes([secpr1_puzzle.puzzle_hash()], include_spent_coins=False)
        )[0].coin
        block_height = sim.block_height

        # Create an announcements to be asserted in the delegated puzzle
        announcement = CreateCoinAnnouncement(msg=b"foo", coin_id=coin.name())

        # Get signature for AGG_SIG_ME
        coin_id = coin.name()
        signature_message = delegated_puzzle_hash + coin_id
        der_sig = secp_sk.sign(
            signature_message,
            # The type stubs are weird here, `deterministic_signing` is assuredly an argument
            ec.ECDSA(hashes.SHA256(), deterministic_signing=True),  # type: ignore[call-arg]
        )
        r, s = decode_dss_signature(der_sig)
        sig = r.to_bytes(32, byteorder="big") + s.to_bytes(32, byteorder="big")
        sb = WalletSpendBundle(
            [
                make_spend(
                    coin,
                    secpr1_puzzle.puzzle_reveal(),
                    secpr1_puzzle.solve(
                        [],
                        [],
                        Program.to(
                            [
                                coin_id,
                                sig,
                            ]
                        ),
                        DelegatedPuzzleAndSolution(
                            delegated_puzzle,
                            Program.to(
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
                "secp spendbundle",
                sb,
            )
        )
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()
        await sim.rewind(block_height)

@pytest.mark.anyio
async def test_secp256k1_member(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        delegated_puzzle = Program.to(1)
        delegated_puzzle_hash = delegated_puzzle.get_tree_hash()

        # setup keys
        secp_sk = ec.generate_private_key(ec.SECP256R1())
        secp_pk = secp_sk.public_key().public_bytes(Encoding.X962, PublicFormat.CompressedPoint)

        secpk1_member = SECPK1Member(secp_pk)

        secpk1_puzzle = PuzzleWithRestrictions(0, [], secpk1_member)

        # Farm and find coin
        await sim.farm_block(secpk1_puzzle.puzzle_hash())
        coin = (
            await client.get_coin_records_by_puzzle_hashes([secpk1_puzzle.puzzle_hash()], include_spent_coins=False)
        )[0].coin
        block_height = sim.block_height

        # Create an announcements to be asserted in the delegated puzzle
        announcement = CreateCoinAnnouncement(msg=b"foo", coin_id=coin.name())

        # Get signature for AGG_SIG_ME
        coin_id = coin.name()
        signature_message = delegated_puzzle_hash + coin_id
        der_sig = secp_sk.sign(
            signature_message,
            # The type stubs are weird here, `deterministic_signing` is assuredly an argument
            ec.ECDSA(hashes.SHA256(), deterministic_signing=True),  # type: ignore[call-arg]
        )
        r, s = decode_dss_signature(der_sig)
        sig = r.to_bytes(32, byteorder="big") + s.to_bytes(32, byteorder="big")
        sb = WalletSpendBundle(
            [
                make_spend(
                    coin,
                    secpk1_puzzle.puzzle_reveal(),
                    secpk1_puzzle.solve(
                        [],
                        [],
                        Program.to(
                            [
                                coin_id,
                                sig,
                            ]
                        ),
                        DelegatedPuzzleAndSolution(
                            delegated_puzzle,
                            Program.to(
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
                "secp spendbundle",
                sb,
            )
        )
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()
        await sim.rewind(block_height)