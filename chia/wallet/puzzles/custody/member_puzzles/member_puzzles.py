from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

from chia_rs import G1Element

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash
from chia.wallet.puzzles.custody.custody_architecture import Puzzle
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile

BLS_MEMBER_MOD = load_clvm_maybe_recompile(
    "bls_member.clsp", package_or_requirement="chia.wallet.puzzles.custody.member_puzzles"
)
PASSKEY_MEMBER_MOD = load_clvm_maybe_recompile(
    "passkey_member.clsp", package_or_requirement="chia.wallet.puzzles.custody.member_puzzles"
)

SECPR1_MEMBER_MOD = load_clvm_maybe_recompile(
    "secp256r1_member.clsp", package_or_requirement="chia.wallet.puzzles.custody.member_puzzles"
)

SECPK1_MEMBER_MOD = load_clvm_maybe_recompile(
    "secp256k1_member.clsp", package_or_requirement="chia.wallet.puzzles.custody.member_puzzles"
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
class PasskeyMember(Puzzle):
    secp_pk: bytes
    genesis_challenge: bytes32

    def memo(self, nonce: int) -> Program:
        return Program.to(0)

    def puzzle(self, nonce: int) -> Program:
        return PASSKEY_MEMBER_MOD.curry(self.genesis_challenge, self.secp_pk)

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()

    def create_message(self, delegated_puzzle_hash: bytes32, coin_id: bytes32) -> str:
        message = base64.urlsafe_b64encode(std_hash(delegated_puzzle_hash + coin_id + self.genesis_challenge))
        return message.decode("utf-8").rstrip("=")

    @staticmethod
    def format_client_data_as_str(client_data: dict[str, Any]) -> str:
        return json.dumps(client_data, separators=(",", ":"))

    def solve(
        self, authenticator_data: bytes, client_data: dict[str, Any], signature: bytes, coin_id: bytes32
    ) -> Program:
        json_str = PasskeyMember.format_client_data_as_str(client_data)
        return Program.to([authenticator_data, json_str, json_str.find('"challenge":'), signature, coin_id])


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