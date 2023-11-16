from __future__ import annotations

from hashlib import sha256
from typing import Tuple

import pytest
from blspy import PrivateKey
from chia_rs import ENABLE_SECP_OPS
from ecdsa import NIST256p, SigningKey

from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.condition_tools import conditions_dict_for_solution
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.util.merkle_tree import MerkleTree
from tests.clvm.test_puzzles import secret_exponent_for_index

P2_DELEGATED_SECP_MOD: Program = load_clvm("p2_delegated_secp.clsp")
P2_1_OF_N_MOD: Program = load_clvm("p2_1_of_n.clsp")
P2_1_OF_N_MOD_HASH = P2_1_OF_N_MOD.get_tree_hash()
RECOVERY_MOD: Program = load_clvm("vault_recovery.clsp")
RECOVERY_MOD_HASH = RECOVERY_MOD.get_tree_hash()
RECOVERY_ESCAPE_MOD: Program = load_clvm("vault_recovery_escape.clsp")
RECOVERY_ESCAPE_MOD_HASH = RECOVERY_ESCAPE_MOD.get_tree_hash()
RECOVERY_FINISH_MOD: Program = load_clvm("vault_recovery_finish.clsp")
RECOVERY_FINISH_MOD_HASH = RECOVERY_FINISH_MOD.get_tree_hash()
ACS = Program.to(1)
ACS_PH = ACS.get_tree_hash()


def run_with_secp(puzzle: Program, solution: Program) -> Tuple[int, Program]:
    return puzzle._run(INFINITE_COST, ENABLE_SECP_OPS, solution)


def test_recovery_puzzles() -> None:
    bls_sk = PrivateKey.from_bytes(secret_exponent_for_index(1).to_bytes(32, "big"))
    bls_pk = bls_sk.get_g1()

    p2_puzzlehash = ACS_PH
    vault_puzzlehash = Program.to("vault_puzzlehash")
    amount = 10000
    timelock = 5000
    recovery_conditions = Program.to([[51, p2_puzzlehash, amount]])

    curried_escape_puzzle = RECOVERY_ESCAPE_MOD.curry(bls_pk, vault_puzzlehash, amount)
    curried_finish_puzzle = RECOVERY_FINISH_MOD.curry(timelock, recovery_conditions)

    curried_recovery_puzzle = RECOVERY_MOD.curry(
        P2_1_OF_N_MOD_HASH, RECOVERY_ESCAPE_MOD_HASH, RECOVERY_FINISH_MOD_HASH, bls_pk, timelock
    )

    recovery_solution = Program.to([vault_puzzlehash, amount, recovery_conditions])

    conds = conditions_dict_for_solution(curried_recovery_puzzle, recovery_solution, INFINITE_COST)

    # Calculate the merkle root and expected recovery puzzle
    merkle_tree = MerkleTree([curried_escape_puzzle.get_tree_hash(), curried_finish_puzzle.get_tree_hash()])
    merkle_root = merkle_tree.calculate_root()
    recovery_puzzle = P2_1_OF_N_MOD.curry(merkle_root)
    recovery_puzzlehash = recovery_puzzle.get_tree_hash()

    # check for correct puzhash in conditions
    assert conds[ConditionOpcode.CREATE_COIN][0].vars[0] == recovery_puzzlehash

    # Spend the recovery puzzle
    # 1. Finish Recovery (after timelock)
    proof = merkle_tree.generate_proof(curried_finish_puzzle.get_tree_hash())
    finish_proof = Program.to((proof[0], proof[1][0]))
    inner_solution = Program.to([])
    finish_solution = Program.to([finish_proof, curried_finish_puzzle, inner_solution])
    finish_conds = conditions_dict_for_solution(recovery_puzzle, finish_solution, INFINITE_COST)
    assert finish_conds[ConditionOpcode.CREATE_COIN][0].vars[0] == p2_puzzlehash

    # 2. Escape Recovery
    proof = merkle_tree.generate_proof(curried_escape_puzzle.get_tree_hash())
    escape_proof = Program.to((proof[0], proof[1][0]))
    inner_solution = Program.to([])
    escape_solution = Program.to([escape_proof, curried_escape_puzzle, inner_solution])
    escape_conds = conditions_dict_for_solution(recovery_puzzle, escape_solution, INFINITE_COST)
    assert escape_conds[ConditionOpcode.CREATE_COIN][0].vars[0] == vault_puzzlehash


def test_p2_delegated_secp() -> None:
    secp_sk = SigningKey.generate(curve=NIST256p, hashfunc=sha256)
    secp_pk = secp_sk.verifying_key.to_string("compressed")
    secp_puzzle = P2_DELEGATED_SECP_MOD.curry(secp_pk)

    delegated_puzzle = ACS
    delegated_solution = Program.to([[51, ACS_PH, 1000]])
    signed_delegated_puzzle = secp_sk.sign_deterministic(delegated_puzzle.get_tree_hash())

    secp_solution = Program.to([delegated_puzzle, delegated_solution, signed_delegated_puzzle])
    _, conds = run_with_secp(secp_puzzle, secp_solution)

    assert conds.at("frf").as_atom() == ACS_PH

    # test that a bad secp sig fails
    sig_bytes = bytearray(signed_delegated_puzzle)
    sig_bytes[0] ^= (sig_bytes[0] + 1) % 256
    bad_signature = bytes(sig_bytes)

    bad_solution = Program.to([delegated_puzzle, delegated_solution, bad_signature])
    with pytest.raises(ValueError, match="secp256r1_verify failed"):
        run_with_secp(secp_puzzle, bad_solution)


def test_vault_root_puzzle() -> None:
    # create the secp and recovery puzzles
    # secp puzzle
    secp_sk = SigningKey.generate(curve=NIST256p, hashfunc=sha256)
    secp_pk = secp_sk.verifying_key.to_string("compressed")
    secp_puzzle = P2_DELEGATED_SECP_MOD.curry(secp_pk)
    secp_puzzlehash = secp_puzzle.get_tree_hash()

    # recovery puzzle
    bls_sk = PrivateKey.from_bytes(secret_exponent_for_index(1).to_bytes(32, "big"))
    bls_pk = bls_sk.get_g1()
    timelock = 5000
    amount = 10000

    recovery_puzzle = RECOVERY_MOD.curry(
        P2_1_OF_N_MOD_HASH, RECOVERY_ESCAPE_MOD_HASH, RECOVERY_FINISH_MOD_HASH, bls_pk, timelock
    )
    recovery_puzzlehash = recovery_puzzle.get_tree_hash()

    # create the vault root puzzle
    vault_merkle_tree = MerkleTree([secp_puzzlehash, recovery_puzzlehash])
    vault_merkle_root = vault_merkle_tree.calculate_root()
    vault_puzzle = P2_1_OF_N_MOD.curry(vault_merkle_root)
    vault_puzzlehash = vault_puzzle.get_tree_hash()

    # secp spend path
    delegated_puzzle = ACS
    delegated_solution = Program.to([[51, ACS_PH, amount]])
    signed_delegated_puzzle = secp_sk.sign_deterministic(delegated_puzzle.get_tree_hash())
    secp_solution = Program.to([delegated_puzzle, delegated_solution, signed_delegated_puzzle])
    proof = vault_merkle_tree.generate_proof(secp_puzzlehash)
    secp_proof = Program.to((proof[0], proof[1][0]))
    vault_solution = Program.to([secp_proof, secp_puzzle, secp_solution])
    secp_conds = conditions_dict_for_solution(vault_puzzle, vault_solution, INFINITE_COST)
    assert secp_conds[ConditionOpcode.CREATE_COIN][0].vars[0] == ACS_PH

    # recovery spend path
    recovery_conditions = Program.to([[51, ACS_PH, amount]])
    curried_escape_puzzle = RECOVERY_ESCAPE_MOD.curry(bls_pk, vault_puzzlehash, amount)
    curried_finish_puzzle = RECOVERY_FINISH_MOD.curry(timelock, recovery_conditions)
    recovery_merkle_tree = MerkleTree([curried_escape_puzzle.get_tree_hash(), curried_finish_puzzle.get_tree_hash()])
    recovery_merkle_root = recovery_merkle_tree.calculate_root()
    recovery_merkle_puzzle = P2_1_OF_N_MOD.curry(recovery_merkle_root)
    recovery_merkle_puzzlehash = recovery_merkle_puzzle.get_tree_hash()
    recovery_solution = Program.to([vault_puzzlehash, amount, recovery_conditions])

    proof = vault_merkle_tree.generate_proof(recovery_puzzlehash)
    recovery_proof = Program.to((proof[0], proof[1][0]))
    vault_solution = Program.to([recovery_proof, recovery_puzzle, recovery_solution])
    recovery_conds = conditions_dict_for_solution(vault_puzzle, vault_solution, INFINITE_COST)
    assert recovery_conds[ConditionOpcode.CREATE_COIN][0].vars[0] == recovery_merkle_puzzlehash
