from __future__ import annotations

from dataclasses import dataclass

from chia_rs import G1Element, G2Element, Program, ProofOfSpace
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint16, uint32, uint64

from chia.util.streamable import Streamable, streamable


# Schema
@streamable
@dataclass(frozen=True, kw_only=True)
class GetLoginRequest(Streamable):
    launcher_id: bytes32
    timestamp: uint64
    signature: G2Element


@streamable
@dataclass(frozen=True, kw_only=True)
class FarmerRecord(Streamable):
    launcher_id: bytes32
    coin_id: bytes32
    pool_puzzle_hash: bytes32
    heightlock: uint32
    pool_memoization: Program
    user_puzzle_hash: bytes32
    exiting: bool


@streamable
@dataclass(frozen=True, kw_only=True)
class PartialMetadata(Streamable):
    timestamp: uint64
    difficulty: uint64


@streamable
@dataclass(frozen=True, kw_only=True)
class GetLoginResponse(Streamable):
    recent_partials: list[PartialMetadata]
    authentication_token: str


@streamable
@dataclass(frozen=True, kw_only=True)
class GetPoolInfoResponse(Streamable):
    name: str
    logo_url: str
    minimum_difficulty: uint64
    relative_lock_height: uint32
    protocol_version: uint8
    fee: uint16
    description: str
    target_puzzle_hash: bytes32
    authentication_token_timeout: uint8
    pool_memoization: Program  # addition from v1


@streamable
@dataclass(frozen=True, kw_only=True)
class PartialPayload(Streamable):
    launcher_id: bytes32
    authentication_token: str
    proof_of_space: ProofOfSpace
    sp_hash: bytes32
    end_of_sub_slot: bool
    harvester_id: bytes32


@streamable
@dataclass(frozen=True, kw_only=True)
class PostPartialRequest(Streamable):
    payload: PartialPayload
    aggregate_signature: G2Element


@streamable
@dataclass(frozen=True, kw_only=True)
class PostPartialResponse(Streamable):
    new_difficulty: uint64


@streamable
@dataclass(frozen=True, kw_only=True)
class GetFarmerRequest(Streamable):
    authentication_token: str
    launcher_id: bytes32


@streamable
@dataclass(frozen=True, kw_only=True)
class GetFarmerResponse(Streamable):
    authentication_public_key: G1Element
    payout_instructions: str
    current_difficulty: uint64
    current_points: uint64


@streamable
@dataclass(frozen=True, kw_only=True)
class FarmerPayload(Streamable):
    launcher_id: bytes32
    authentication_token: str | None = None
    authentication_public_key: G1Element | None = None
    payout_instructions: str | None = None
    suggested_difficulty: uint64 | None = None


@streamable
@dataclass(frozen=True, kw_only=True)
class FarmerRequest(Streamable):
    payload: FarmerPayload
    signature: G2Element


@streamable
@dataclass(frozen=True, kw_only=True)
class PostFarmerResponse(Streamable):
    welcome_message: str


@streamable
@dataclass(frozen=True, kw_only=True)
class PutFarmerResponse(Streamable):
    authentication_public_key: bool | None
    payout_instructions: bool | None
    suggested_difficulty: bool | None
