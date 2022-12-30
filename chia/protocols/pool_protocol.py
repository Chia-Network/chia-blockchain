from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from blspy import G1Element, G2Element

from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8, uint16, uint32, uint64
from chia.util.streamable import Streamable, streamable

POOL_PROTOCOL_VERSION = uint8(1)


class PoolErrorCode(Enum):
    REVERTED_SIGNAGE_POINT = 1
    TOO_LATE = 2
    NOT_FOUND = 3
    INVALID_PROOF = 4
    PROOF_NOT_GOOD_ENOUGH = 5
    INVALID_DIFFICULTY = 6
    INVALID_SIGNATURE = 7
    SERVER_EXCEPTION = 8
    INVALID_P2_SINGLETON_PUZZLE_HASH = 9
    FARMER_NOT_KNOWN = 10
    FARMER_ALREADY_KNOWN = 11
    INVALID_AUTHENTICATION_TOKEN = 12
    INVALID_PAYOUT_INSTRUCTIONS = 13
    INVALID_SINGLETON = 14
    DELAY_TIME_TOO_SHORT = 15
    REQUEST_FAILED = 16


# Used to verify GET /farmer and GET /login
@streamable
@dataclass(frozen=True)
class AuthenticationPayload(Streamable):
    method_name: str
    launcher_id: bytes32
    target_puzzle_hash: bytes32
    authentication_token: uint64


# GET /pool_info
@streamable
@dataclass(frozen=True)
class GetPoolInfoResponse(Streamable):
    name: str
    logo_url: str
    minimum_difficulty: uint64
    relative_lock_height: uint32
    protocol_version: uint8
    fee: str
    description: str
    target_puzzle_hash: bytes32
    authentication_token_timeout: uint8


# POST /partial


@streamable
@dataclass(frozen=True)
class PostPartialPayload(Streamable):
    launcher_id: bytes32
    authentication_token: uint64
    proof_of_space: ProofOfSpace
    sp_hash: bytes32
    end_of_sub_slot: bool
    harvester_id: bytes32


@streamable
@dataclass(frozen=True)
class PostPartialRequest(Streamable):
    payload: PostPartialPayload
    aggregate_signature: G2Element


# Response in success case
@streamable
@dataclass(frozen=True)
class PostPartialResponse(Streamable):
    new_difficulty: uint64


# GET /farmer


# Response in success case
@streamable
@dataclass(frozen=True)
class GetFarmerResponse(Streamable):
    authentication_public_key: G1Element
    payout_instructions: str
    current_difficulty: uint64
    current_points: uint64


# POST /farmer


@streamable
@dataclass(frozen=True)
class PostFarmerPayload(Streamable):
    launcher_id: bytes32
    authentication_token: uint64
    authentication_public_key: G1Element
    payout_instructions: str
    suggested_difficulty: Optional[uint64]


@streamable
@dataclass(frozen=True)
class PostFarmerRequest(Streamable):
    payload: PostFarmerPayload
    signature: G2Element


# Response in success case
@streamable
@dataclass(frozen=True)
class PostFarmerResponse(Streamable):
    welcome_message: str


# PUT /farmer


@streamable
@dataclass(frozen=True)
class PutFarmerPayload(Streamable):
    launcher_id: bytes32
    authentication_token: uint64
    authentication_public_key: Optional[G1Element]
    payout_instructions: Optional[str]
    suggested_difficulty: Optional[uint64]


@streamable
@dataclass(frozen=True)
class PutFarmerRequest(Streamable):
    payload: PutFarmerPayload
    signature: G2Element


# Response in success case
@streamable
@dataclass(frozen=True)
class PutFarmerResponse(Streamable):
    authentication_public_key: Optional[bool]
    payout_instructions: Optional[bool]
    suggested_difficulty: Optional[bool]


# Misc


# Response in error case for all endpoints of the pool protocol
@streamable
@dataclass(frozen=True)
class ErrorResponse(Streamable):
    error_code: uint16
    error_message: Optional[str]


# Get the current authentication token according to "Farmer authentication" in SPECIFICATION.md
def get_current_authentication_token(timeout: uint8) -> uint64:
    return uint64(int(int(time.time() / 60) / timeout))


# Validate a given authentication token against our local time
def validate_authentication_token(token: uint64, timeout: uint8):
    return abs(token - get_current_authentication_token(timeout)) <= timeout
