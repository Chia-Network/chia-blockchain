from __future__ import annotations

import itertools
from typing import List

import pytest
from chia_rs import AugSchemeMPL, G2Element
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from chia._tests.clvm.test_custody_architecture import ACSDPuzValidator
from chia._tests.util.spend_sim import CostLogger, sim_and_client
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
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
from chia.wallet.puzzles.custody.member_puzzles.member_puzzles import (
    BLSMember,
    PasskeyMember,
    SECPK1Member,
    SECPK1PuzzleAssertMember,
    SECPR1Member,
    SECPR1PuzzleAssertMember,
)
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

from chia.wallet.puzzles.custody.member_puzzles.member_puzzles import BLSMember, SingletonMember
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_synthetic_public_key
from chia.wallet.singleton import SINGLETON_LAUNCHER_PUZZLE, SINGLETON_LAUNCHER_PUZZLE_HASH, SINGLETON_TOP_LAYER_MOD
from chia.wallet.wallet_spend_bundle import WalletSpendBundle
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8, uint16, uint32, uint64, uint128

from chia.consensus.constants import ConsensusConstants

AGG_SIG_DATA = bytes32.fromhex("ccd5bb71183532bff220ba46c268991a3ff07eb358e8255a65c30a2dce0e5fbb")

FORK_ENABLED_CONSTANTS = ConsensusConstants(
    SLOT_BLOCKS_TARGET=uint32(32),
    MIN_BLOCKS_PER_CHALLENGE_BLOCK=uint8(16),  # Must be less than half of SLOT_BLOCKS_TARGET
    MAX_SUB_SLOT_BLOCKS=uint32(128),  # Must be less than half of SUB_EPOCH_BLOCKS
    NUM_SPS_SUB_SLOT=uint32(64),  # Must be a power of 2
    SUB_SLOT_ITERS_STARTING=uint64(2**27),
    # DIFFICULTY_STARTING is the starting difficulty for the first epoch, which is then further
    # multiplied by another factor of DIFFICULTY_CONSTANT_FACTOR, to be used in the VDF iter calculation formula.
    DIFFICULTY_CONSTANT_FACTOR=uint128(2**67),
    DIFFICULTY_STARTING=uint64(7),
    DIFFICULTY_CHANGE_MAX_FACTOR=uint32(3),  # The next difficulty is truncated to range [prev / FACTOR, prev * FACTOR]
    # These 3 constants must be changed at the same time
    SUB_EPOCH_BLOCKS=uint32(384),  # The number of blocks per sub-epoch, mainnet 384
    EPOCH_BLOCKS=uint32(4608),  # The number of blocks per epoch, mainnet 4608. Must be multiple of SUB_EPOCH_SB
    SIGNIFICANT_BITS=uint8(8),  # The number of bits to look at in difficulty and min iters. The rest are zeroed
    DISCRIMINANT_SIZE_BITS=uint16(1024),  # Max is 1024 (based on ClassGroupElement int size)
    NUMBER_ZERO_BITS_PLOT_FILTER=uint8(9),  # H(plot signature of the challenge) must start with these many zeroes
    MIN_PLOT_SIZE=uint8(32),  # 32 for mainnet
    MAX_PLOT_SIZE=uint8(50),
    SUB_SLOT_TIME_TARGET=uint16(600),  # The target number of seconds per slot, mainnet 600
    NUM_SP_INTERVALS_EXTRA=uint8(3),  # The number of sp intervals to add to the signage point
    MAX_FUTURE_TIME2=uint32(2 * 60),  # The next block can have a timestamp of at most these many seconds in the future
    NUMBER_OF_TIMESTAMPS=uint8(11),  # Than the average of the last NUMBER_OF_TIMESTAMPS blocks
    # Used as the initial cc rc challenges, as well as first block back pointers, and first SES back pointer
    # We override this value based on the chain being run (testnet0, testnet1, mainnet, etc)
    # Default used for tests is std_hash(b'')
    GENESIS_CHALLENGE=bytes32.fromhex("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
    # Forks of chia should change the AGG_SIG_*_ADDITIONAL_DATA values to provide
    # replay attack protection. This is set to mainnet genesis challange
    AGG_SIG_ME_ADDITIONAL_DATA=AGG_SIG_DATA,
    AGG_SIG_PARENT_ADDITIONAL_DATA=std_hash(AGG_SIG_DATA + bytes([43])),
    AGG_SIG_PUZZLE_ADDITIONAL_DATA=std_hash(AGG_SIG_DATA + bytes([44])),
    AGG_SIG_AMOUNT_ADDITIONAL_DATA=std_hash(AGG_SIG_DATA + bytes([45])),
    AGG_SIG_PUZZLE_AMOUNT_ADDITIONAL_DATA=std_hash(AGG_SIG_DATA + bytes([46])),
    AGG_SIG_PARENT_AMOUNT_ADDITIONAL_DATA=std_hash(AGG_SIG_DATA + bytes([47])),
    AGG_SIG_PARENT_PUZZLE_ADDITIONAL_DATA=std_hash(AGG_SIG_DATA + bytes([48])),
    GENESIS_PRE_FARM_POOL_PUZZLE_HASH=bytes32.fromhex(
        "d23da14695a188ae5708dd152263c4db883eb27edeb936178d4d988b8f3ce5fc"
    ),
    GENESIS_PRE_FARM_FARMER_PUZZLE_HASH=bytes32.fromhex(
        "3d8765d3a597ec1d99663f6c9816d915b9f68613ac94009884c4addaefcce6af"
    ),
    MAX_VDF_WITNESS_SIZE=uint8(64),
    # Size of mempool = 10x the size of block
    MEMPOOL_BLOCK_BUFFER=uint8(10),
    # Max coin amount, fits into 64 bits
    MAX_COIN_AMOUNT=uint64((1 << 64) - 1),
    # Max block cost in clvm cost units
    MAX_BLOCK_COST_CLVM=uint64(11000000000),
    # The cost per byte of generator program
    COST_PER_BYTE=uint64(12000),
    WEIGHT_PROOF_THRESHOLD=uint8(2),
    BLOCKS_CACHE_SIZE=uint32(4608 + (128 * 4)),
    WEIGHT_PROOF_RECENT_BLOCKS=uint32(1000),
    # Allow up to 33 blocks per request. This defines the max allowed difference
    # between start and end in the block request message. But the range is
    # inclusive, so the max allowed range of 32 is a request for 33 blocks
    # (which is allowed)
    MAX_BLOCK_COUNT_PER_REQUESTS=uint32(32),
    MAX_GENERATOR_SIZE=uint32(1000000),
    MAX_GENERATOR_REF_LIST_SIZE=uint32(512),  # Number of references allowed in the block generator ref list
    POOL_SUB_SLOT_ITERS=uint64(37600000000),  # iters limit * NUM_SPS
    SOFT_FORK5_HEIGHT=uint32(0),
    # June 2024
    HARD_FORK_HEIGHT=uint32(0),
    # June 2027
    PLOT_FILTER_128_HEIGHT=uint32(0),
    # June 2030
    PLOT_FILTER_64_HEIGHT=uint32(0),
    # June 2033
    PLOT_FILTER_32_HEIGHT=uint32(0),
)


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
        assert secpr1_member.memo(0) == Program.to(0)
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
        secp_sk: EllipticCurvePrivateKey = ec.generate_private_key(ec.SECP256K1())
        secp_pk = secp_sk.public_key().public_bytes(Encoding.X962, PublicFormat.CompressedPoint)

        secpk1_member = SECPK1Member(secp_pk)
        assert secpk1_member.memo(0) == Program.to(0)

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

        sb = WalletSpendBundle(
            [
                make_spend(
                    coin,
                    secpk1_puzzle.puzzle_reveal(),
                    secpk1_puzzle.solve(
                        [],
                        [],
                        secpk1_member.solve(secp_sk, signature_message, coin_id),
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
async def test_secp256r1_puzzle_assert_member(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        delegated_puzzle = Program.to(1)
        delegated_puzzle_hash = delegated_puzzle.get_tree_hash()

        # setup keys
        seed = 0x1A62C9636D1C9DB2E7D564D0C11603BF456AAD25AA7B12BDFD762B4E38E7EDC6
        secp_sk = ec.derive_private_key(seed, ec.SECP256R1(), default_backend())
        secp_pk = secp_sk.public_key().public_bytes(Encoding.X962, PublicFormat.CompressedPoint)

        secpr1_member = SECPR1PuzzleAssertMember(secp_pk)
        assert secpr1_member.memo(0) == Program.to(0)
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
        signature_message = delegated_puzzle_hash + secpr1_puzzle.puzzle_hash()
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
                                secpr1_puzzle.puzzle_hash(),
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
async def test_secp256k1_puzzle_assert_member(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        delegated_puzzle = Program.to(1)
        delegated_puzzle_hash = delegated_puzzle.get_tree_hash()

        # setup keys
        secp_sk: EllipticCurvePrivateKey = ec.generate_private_key(ec.SECP256K1())
        secp_pk = secp_sk.public_key().public_bytes(Encoding.X962, PublicFormat.CompressedPoint)

        secpk1_member = SECPK1PuzzleAssertMember(secp_pk)
        assert secpk1_member.memo(0) == Program.to(0)

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
        signature_message = delegated_puzzle_hash + secpk1_puzzle.puzzle_hash()

        sb = WalletSpendBundle(
            [
                make_spend(
                    coin,
                    secpk1_puzzle.puzzle_reveal(),
                    secpk1_puzzle.solve(
                        [],
                        [],
                        secpk1_member.solve(secp_sk, signature_message, secpk1_puzzle.puzzle_hash()),
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
async def test_singleton_member(cost_logger: CostLogger) -> None:
    async with sim_and_client(defaults=FORK_ENABLED_CONSTANTS) as (sim, client):
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
        singleton_member_puzzle = PuzzleWithRestrictions(0, [], SingletonMember(launcher_coin.name()))

        singleton_struct = (SINGLETON_TOP_LAYER_MOD.get_tree_hash(), (launcher_coin.name(), SINGLETON_LAUNCHER_PUZZLE_HASH))
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

        memo = PuzzleHint(
            singleton_member_puzzle.puzzle.puzzle_hash(0),
            singleton_member_puzzle.puzzle.memo(0),
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
        fullsol = Program.to([
            [launcher_coin.parent_coin_info, 1],
            1,
            [
                [51, Program.to(1).get_tree_hash(), 1],
                [66, 0x17, delegated_puzzle.get_tree_hash(), coin.name()],  # 00010111  - puzzle sender, coin receiver
            ],  # create approval message to singleton member puzzle
        ])

        sb = WalletSpendBundle(
            [
                make_spend(
                    coin,
                    singleton_member_puzzle.puzzle_reveal(),
                    singleton_member_puzzle.solve(
                        [],
                        [],
                        Program.to(
                            [singleton_innerpuz.get_tree_hash()]
                        ),  # singleton member puzzle only requires singleton's current innerpuz
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
async def test_message_conditions(cost_logger: CostLogger) -> None:
    async with sim_and_client(defaults=FORK_ENABLED_CONSTANTS) as (sim, client):
        ## Temp
        # Farm and find coin
        await sim.farm_block(Program.to(1).get_tree_hash())
        await sim.farm_block(Program.to(1).get_tree_hash())
        coin_1 = (
            await client.get_coin_records_by_puzzle_hashes(
                [Program.to(1).get_tree_hash()], include_spent_coins=False
            )
        )[0].coin
        coin_2 = (
            await client.get_coin_records_by_puzzle_hashes(
                [Program.to(1).get_tree_hash()], include_spent_coins=False
            )
        )[1].coin

        sb = WalletSpendBundle(
            [
                make_spend(
                    coin_1,
                    Program.to(1),
                    Program.to([[66, 0x17, Program.to(1).get_tree_hash(), coin_2.name()]]),
                ),
                make_spend(
                    coin_2,
                    Program.to(1),
                    Program.to([[67, 0x17, Program.to(1).get_tree_hash(), Program.to(1).get_tree_hash()]]),
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
