from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

from chia_rs import AugSchemeMPL, G1Element, G2Element, PrivateKey
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash
from chia.wallet.puzzles.custody.custody_architecture import Puzzle
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    calculate_synthetic_public_key,
    calculate_synthetic_secret_key,
)
from chia.wallet.singleton import SINGLETON_LAUNCHER_PUZZLE_HASH, SINGLETON_TOP_LAYER_MOD_HASH

BLS_MEMBER_MOD = load_clvm_maybe_recompile(
    "bls_member.clsp", package_or_requirement="chia.wallet.puzzles.custody.member_puzzles"
)

BLS_WITH_TAPROOT_MEMBER_MOD = load_clvm_maybe_recompile(
    "bls_with_taproot_member.clsp", package_or_requirement="chia.wallet.puzzles.custody.member_puzzles"
)

PASSKEY_MEMBER_MOD = load_clvm_maybe_recompile(
    "passkey_member.clsp", package_or_requirement="chia.wallet.puzzles.custody.member_puzzles"
)

PASSKEY_PUZZLE_ASSERT_MEMBER_MOD = load_clvm_maybe_recompile(
    "passkey_member_puzzle_assert.clsp", package_or_requirement="chia.wallet.puzzles.custody.member_puzzles"
)

SECPR1_MEMBER_MOD = load_clvm_maybe_recompile(
    "secp256r1_member.clsp", package_or_requirement="chia.wallet.puzzles.custody.member_puzzles"
)

SECPK1_MEMBER_MOD = load_clvm_maybe_recompile(
    "secp256k1_member.clsp", package_or_requirement="chia.wallet.puzzles.custody.member_puzzles"
)

SECPR1_PUZZLE_ASSERT_MEMBER_MOD = load_clvm_maybe_recompile(
    "secp256r1_member_puzzle_assert.clsp", package_or_requirement="chia.wallet.puzzles.custody.member_puzzles"
)

SECPK1_PUZZLE_ASSERT_MEMBER_MOD = load_clvm_maybe_recompile(
    "secp256k1_member_puzzle_assert.clsp", package_or_requirement="chia.wallet.puzzles.custody.member_puzzles"
)

SINGLETON_MEMBER_MOD = load_clvm_maybe_recompile(
    "singleton_member.clsp", package_or_requirement="chia.wallet.puzzles.custody.member_puzzles"
)

FIXED_PUZZLE_MEMBER_MOD = load_clvm_maybe_recompile(
    "fixed_puzzle_member.clsp", package_or_requirement="chia.wallet.puzzles.custody.member_puzzles"
)


@dataclass(frozen=True)
class BLSMember(Puzzle):
    public_key: G1Element

    def memo(self, nonce: int) -> Program:
        return Program.to(0)

    def puzzle(self, nonce: int) -> Program:
        return BLS_MEMBER_MOD.curry(bytes(self.public_key))

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()


@dataclass(frozen=True)
class BLSWithTaprootMember(Puzzle):
    public_key: G1Element
    hidden_puzzle: Program  # must be specified manually due to frozen class

    def memo(self, nonce: int) -> Program:
        return Program.to(0)

    def puzzle(self, nonce: int) -> Program:
        synthetic_public_key = calculate_synthetic_public_key(self.public_key, self.hidden_puzzle.get_tree_hash())
        return BLS_WITH_TAPROOT_MEMBER_MOD.curry(bytes(synthetic_public_key))

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()

    def sign_with_synthetic_secret_key(self, original_secret_key: PrivateKey, message: bytes) -> G2Element:
        synthetic_sk = calculate_synthetic_secret_key(original_secret_key, self.hidden_puzzle.get_tree_hash())
        return AugSchemeMPL.sign(synthetic_sk, message)

    def solve(self, use_hidden_puzzle: bool = False) -> Program:
        if use_hidden_puzzle:
            return Program.to([self.public_key, self.hidden_puzzle])
        return Program.to([0])


@dataclass(frozen=True)
class PasskeyMember(Puzzle):
    secp_pk: bytes
    genesis_challenge: bytes32

    def memo(self, nonce: int) -> Program:
        return Program.to(0)

    def puzzle(self, nonce: int) -> Program:
        return PASSKEY_MEMBER_MOD.curry(self.genesis_challenge, self.secp_pk)

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()

    def create_message(self, delegated_puzzle_hash: bytes32, asserted_info: bytes32) -> str:
        message = base64.urlsafe_b64encode(std_hash(delegated_puzzle_hash + asserted_info + self.genesis_challenge))
        return message.decode("utf-8").rstrip("=")

    @staticmethod
    def format_client_data_as_str(client_data: dict[str, Any]) -> str:
        return json.dumps(client_data, separators=(",", ":"))

    def solve(
        self, authenticator_data: bytes, client_data: dict[str, Any], signature: bytes, asserted_info: bytes32
    ) -> Program:
        json_str = PasskeyMember.format_client_data_as_str(client_data)
        return Program.to([authenticator_data, json_str, json_str.find('"challenge":'), signature, asserted_info])


@dataclass(frozen=True)
class PasskeyPuzzleAssertMember(PasskeyMember):
    def puzzle(self, nonce: int) -> Program:
        return PASSKEY_PUZZLE_ASSERT_MEMBER_MOD.curry(self.genesis_challenge, self.secp_pk)


@dataclass(frozen=True)
class SECPR1Member(Puzzle):
    secp_pk: bytes

    def memo(self, nonce: int) -> Program:
        return Program.to(0)

    def puzzle(self, nonce: int) -> Program:
        return SECPR1_MEMBER_MOD.curry(self.secp_pk)

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()


@dataclass(frozen=True)
class SECPK1Member(Puzzle):
    secp_pk: bytes

    def memo(self, nonce: int) -> Program:
        return Program.to(0)

    def puzzle(self, nonce: int) -> Program:
        return SECPK1_MEMBER_MOD.curry(self.secp_pk)

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()

    def solve(self, secp_sk: EllipticCurvePrivateKey, message: bytes, coin_id: bytes32) -> Program:
        der_sig = secp_sk.sign(
            message,
            # The type stubs are weird here, `deterministic_signing` is assuredly an argument
            ec.ECDSA(hashes.SHA256(), deterministic_signing=True),  # type: ignore[call-arg]
        )
        r, _s = decode_dss_signature(der_sig)
        curve_order = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
        if _s > curve_order // 2:
            s = -_s % curve_order
        else:
            s = _s
        sig = r.to_bytes(32, byteorder="big") + s.to_bytes(32, byteorder="big")
        return Program.to([coin_id, sig])


@dataclass(frozen=True)
class SECPR1PuzzleAssertMember(SECPK1Member):
    def puzzle(self, nonce: int) -> Program:
        return SECPR1_PUZZLE_ASSERT_MEMBER_MOD.curry(self.secp_pk)


@dataclass(frozen=True)
class SECPK1PuzzleAssertMember(SECPK1Member):
    def puzzle(self, nonce: int) -> Program:
        return SECPK1_PUZZLE_ASSERT_MEMBER_MOD.curry(self.secp_pk)

    def solve(self, secp_sk: EllipticCurvePrivateKey, message: bytes, my_puzzle_hash: bytes32) -> Program:
        der_sig = secp_sk.sign(
            message,
            # The type stubs are weird here, `deterministic_signing` is assuredly an argument
            ec.ECDSA(hashes.SHA256(), deterministic_signing=True),  # type: ignore[call-arg]
        )
        r, _s = decode_dss_signature(der_sig)
        curve_order = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
        if _s > curve_order // 2:
            s = -_s % curve_order
        else:
            s = _s
        sig = r.to_bytes(32, byteorder="big") + s.to_bytes(32, byteorder="big")
        return Program.to([my_puzzle_hash, sig])


@dataclass(frozen=True)
class SingletonMember(Puzzle):
    singleton_id: bytes32
    singleton_mod_hash = SINGLETON_TOP_LAYER_MOD_HASH
    singleton_launcher_hash = SINGLETON_LAUNCHER_PUZZLE_HASH

    def memo(self, nonce: int) -> Program:
        return Program.to(0)

    def puzzle(self, nonce: int) -> Program:
        singleton_struct = (self.singleton_mod_hash, (self.singleton_id, self.singleton_launcher_hash))
        return SINGLETON_MEMBER_MOD.curry(singleton_struct)

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()


@dataclass(frozen=True)
class FixedPuzzleMember(Puzzle):
    fixed_puzzle_hash: bytes32

    def memo(self, nonce: int) -> Program:
        return Program.to(0)

    def puzzle(self, nonce: int) -> Program:
        return FIXED_PUZZLE_MEMBER_MOD.curry(self.fixed_puzzle_hash)

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()
