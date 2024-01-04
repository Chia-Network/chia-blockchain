from __future__ import annotations

from hashlib import sha256

import pytest
from chia_rs import PrivateKey
from ecdsa import NIST256p, SigningKey

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.condition_tools import conditions_dict_for_solution
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import DEFAULT_HIDDEN_PUZZLE_HASH
from chia.wallet.util.merkle_tree import MerkleTree
from tests.clvm.test_puzzles import secret_exponent_for_index

P2_DELEGATED_SECP_MOD: Program = load_clvm("p2_delegated_or_hidden_secp.clsp")
P2_1_OF_N_MOD: Program = load_clvm("p2_1_of_n.clsp")
P2_1_OF_N_MOD_HASH: bytes32 = P2_1_OF_N_MOD.get_tree_hash()
P2_RECOVERY_MOD: Program = load_clvm("vault_p2_recovery.clsp")
P2_RECOVERY_MOD_HASH: bytes32 = P2_RECOVERY_MOD.get_tree_hash()
RECOVERY_FINISH_MOD: Program = load_clvm("vault_recovery_finish.clsp")
RECOVERY_FINISH_MOD_HASH: bytes32 = RECOVERY_FINISH_MOD.get_tree_hash()
ACS: Program = Program.to(1)
ACS_PH: bytes32 = ACS.get_tree_hash()


def test_secp_hidden() -> None:
    HIDDEN_PUZZLE: Program = Program.to(1)
    HIDDEN_PUZZLE_HASH: bytes32 = HIDDEN_PUZZLE.get_tree_hash()

    secp_sk = SigningKey.generate(curve=NIST256p, hashfunc=sha256)
    secp_pk = secp_sk.verifying_key.to_string("compressed")
    escape_puzzle = P2_DELEGATED_SECP_MOD.curry(DEFAULT_CONSTANTS.GENESIS_CHALLENGE, secp_pk, HIDDEN_PUZZLE_HASH)
    coin_id = Program.to("coin_id").get_tree_hash()
    conditions = Program.to([[51, ACS_PH, 100]])
    hidden_escape_solution = Program.to([HIDDEN_PUZZLE, conditions, 0, coin_id])
    hidden_result = escape_puzzle.run(hidden_escape_solution)
    assert hidden_result == Program.to(conditions)


def test_recovery_puzzles() -> None:
    bls_sk = PrivateKey.from_bytes(secret_exponent_for_index(1).to_bytes(32, "big"))
    bls_pk = bls_sk.get_g1()
    secp_sk = SigningKey.generate(curve=NIST256p, hashfunc=sha256)
    secp_pk = secp_sk.verifying_key.to_string("compressed")

    p2_puzzlehash = ACS_PH
    amount = 10000
    timelock = 5000
    coin_id = Program.to("coin_id").get_tree_hash()
    recovery_conditions = Program.to([[51, p2_puzzlehash, amount]])

    escape_puzzle = P2_DELEGATED_SECP_MOD.curry(
        DEFAULT_CONSTANTS.GENESIS_CHALLENGE, secp_pk, DEFAULT_HIDDEN_PUZZLE_HASH
    )
    escape_puzzlehash = escape_puzzle.get_tree_hash()
    finish_puzzle = RECOVERY_FINISH_MOD.curry(timelock, recovery_conditions)
    finish_puzzlehash = finish_puzzle.get_tree_hash()

    curried_recovery_puzzle = P2_RECOVERY_MOD.curry(
        P2_1_OF_N_MOD_HASH, RECOVERY_FINISH_MOD_HASH, escape_puzzlehash, bls_pk, timelock
    )

    recovery_solution = Program.to([amount, recovery_conditions])

    conds = conditions_dict_for_solution(curried_recovery_puzzle, recovery_solution, INFINITE_COST)

    # Calculate the merkle root and expected recovery puzzle
    merkle_tree = MerkleTree([escape_puzzlehash, finish_puzzlehash])
    merkle_root = merkle_tree.calculate_root()
    recovery_puzzle = P2_1_OF_N_MOD.curry(merkle_root)
    recovery_puzzlehash = recovery_puzzle.get_tree_hash()

    # check for correct puzhash in conditions
    assert conds[ConditionOpcode.CREATE_COIN][0].vars[0] == recovery_puzzlehash

    # Spend the recovery puzzle
    # 1. Finish Recovery (after timelock)
    proof = merkle_tree.generate_proof(finish_puzzlehash)
    finish_proof = Program.to((proof[0], proof[1][0]))
    inner_solution = Program.to([])
    finish_solution = Program.to([finish_proof, finish_puzzle, inner_solution])
    finish_conds = conditions_dict_for_solution(recovery_puzzle, finish_solution, INFINITE_COST)
    assert finish_conds[ConditionOpcode.CREATE_COIN][0].vars[0] == p2_puzzlehash

    # 2. Escape Recovery
    proof = merkle_tree.generate_proof(escape_puzzlehash)
    escape_proof = Program.to((proof[0], proof[1][0]))
    delegated_puzzle = ACS
    delegated_solution = Program.to([[51, ACS_PH, amount]])
    signed_delegated_puzzle = secp_sk.sign_deterministic(
        delegated_puzzle.get_tree_hash() + coin_id + DEFAULT_CONSTANTS.GENESIS_CHALLENGE + DEFAULT_HIDDEN_PUZZLE_HASH
    )
    secp_solution = Program.to(
        [delegated_puzzle, delegated_solution, signed_delegated_puzzle, coin_id, DEFAULT_CONSTANTS.GENESIS_CHALLENGE]
    )
    escape_solution = Program.to([escape_proof, escape_puzzle, secp_solution])
    escape_conds = conditions_dict_for_solution(recovery_puzzle, escape_solution, INFINITE_COST)
    assert escape_conds[ConditionOpcode.CREATE_COIN][0].vars[0] == ACS_PH


def test_p2_delegated_secp() -> None:
    secp_sk = SigningKey.generate(curve=NIST256p, hashfunc=sha256)
    secp_pk = secp_sk.verifying_key.to_string("compressed")
    secp_puzzle = P2_DELEGATED_SECP_MOD.curry(DEFAULT_CONSTANTS.GENESIS_CHALLENGE, secp_pk, DEFAULT_HIDDEN_PUZZLE_HASH)

    coin_id = Program.to("coin_id").get_tree_hash()
    delegated_puzzle = ACS
    delegated_solution = Program.to([[51, ACS_PH, 1000]])
    signed_delegated_puzzle = secp_sk.sign_deterministic(
        delegated_puzzle.get_tree_hash() + coin_id + DEFAULT_CONSTANTS.GENESIS_CHALLENGE + DEFAULT_HIDDEN_PUZZLE_HASH
    )

    secp_solution = Program.to([delegated_puzzle, delegated_solution, signed_delegated_puzzle, coin_id])
    conds = secp_puzzle.run(secp_solution)

    assert conds.at("rfrf").as_atom() == ACS_PH

    # test that a bad secp sig fails
    sig_bytes = bytearray(signed_delegated_puzzle)
    sig_bytes[0] ^= (sig_bytes[0] + 1) % 256
    bad_signature = bytes(sig_bytes)

    bad_solution = Program.to(
        [delegated_puzzle, delegated_solution, bad_signature, coin_id, DEFAULT_CONSTANTS.GENESIS_CHALLENGE]
    )
    with pytest.raises(ValueError, match="secp256r1_verify failed"):
        secp_puzzle.run(bad_solution)


def test_vault_root_puzzle() -> None:
    # create the secp and recovery puzzles
    # secp puzzle
    secp_sk = SigningKey.generate(curve=NIST256p, hashfunc=sha256)
    secp_pk = secp_sk.verifying_key.to_string("compressed")
    secp_puzzle = P2_DELEGATED_SECP_MOD.curry(DEFAULT_CONSTANTS.GENESIS_CHALLENGE, secp_pk, DEFAULT_HIDDEN_PUZZLE_HASH)
    secp_puzzlehash = secp_puzzle.get_tree_hash()

    # recovery keys
    bls_sk = PrivateKey.from_bytes(secret_exponent_for_index(1).to_bytes(32, "big"))
    bls_pk = bls_sk.get_g1()

    timelock = 5000
    amount = 10000
    coin_id = Program.to("coin_id").get_tree_hash()

    recovery_puzzle = P2_RECOVERY_MOD.curry(
        P2_1_OF_N_MOD_HASH, RECOVERY_FINISH_MOD_HASH, secp_puzzlehash, bls_pk, timelock
    )
    recovery_puzzlehash = recovery_puzzle.get_tree_hash()

    # create the vault root puzzle
    vault_merkle_tree = MerkleTree([secp_puzzlehash, recovery_puzzlehash])
    vault_merkle_root = vault_merkle_tree.calculate_root()
    vault_puzzle = P2_1_OF_N_MOD.curry(vault_merkle_root)

    # secp spend path
    delegated_puzzle = ACS
    delegated_solution = Program.to([[51, ACS_PH, amount]])
    signed_delegated_puzzle = secp_sk.sign_deterministic(
        delegated_puzzle.get_tree_hash() + coin_id + DEFAULT_CONSTANTS.GENESIS_CHALLENGE + DEFAULT_HIDDEN_PUZZLE_HASH
    )
    secp_solution = Program.to([delegated_puzzle, delegated_solution, signed_delegated_puzzle, coin_id])
    proof = vault_merkle_tree.generate_proof(secp_puzzlehash)
    secp_proof = Program.to((proof[0], proof[1][0]))
    vault_solution = Program.to([secp_proof, secp_puzzle, secp_solution])
    secp_conds = conditions_dict_for_solution(vault_puzzle, vault_solution, INFINITE_COST)
    assert secp_conds[ConditionOpcode.CREATE_COIN][0].vars[0] == ACS_PH

    # recovery spend path
    recovery_conditions = Program.to([[51, ACS_PH, amount]])
    curried_escape_puzzle = P2_DELEGATED_SECP_MOD.curry(
        DEFAULT_CONSTANTS.GENESIS_CHALLENGE, secp_pk, DEFAULT_HIDDEN_PUZZLE_HASH
    )
    curried_finish_puzzle = RECOVERY_FINISH_MOD.curry(timelock, recovery_conditions)
    recovery_merkle_tree = MerkleTree([curried_escape_puzzle.get_tree_hash(), curried_finish_puzzle.get_tree_hash()])
    recovery_merkle_root = recovery_merkle_tree.calculate_root()
    recovery_merkle_puzzle = P2_1_OF_N_MOD.curry(recovery_merkle_root)
    recovery_merkle_puzzlehash = recovery_merkle_puzzle.get_tree_hash()
    recovery_solution = Program.to([amount, recovery_conditions])

    proof = vault_merkle_tree.generate_proof(recovery_puzzlehash)
    recovery_proof = Program.to((proof[0], proof[1][0]))
    vault_solution = Program.to([recovery_proof, recovery_puzzle, recovery_solution])
    recovery_conds = conditions_dict_for_solution(vault_puzzle, vault_solution, INFINITE_COST)
    assert recovery_conds[ConditionOpcode.CREATE_COIN][0].vars[0] == recovery_merkle_puzzlehash
