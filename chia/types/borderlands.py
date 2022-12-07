from __future__ import annotations

from typing import NewType

from chia.types.blockchain_format.sized_bytes import bytes32, bytes48, bytes96

PrivateKeyBytes = NewType("PrivateKeyBytes", bytes32)
PublicKeyBytes = NewType("PublicKeyBytes", bytes48)
SignatureBytes = NewType("SignatureBytes", bytes96)
PuzzleHash = NewType("PuzzleHash", bytes32)
CoinID = NewType("CoinID", bytes32)
SpendBundleID = NewType("SpendBundleID", bytes32)  # Also used as MempoolItemID
BlockRecordHeaderHash = NewType("BlockRecordHeaderHash", bytes32)


def bytes_to_PrivateKeyBytes(input_bytes: bytes) -> PrivateKeyBytes:
    return PrivateKeyBytes(bytes32(input_bytes))


def bytes_to_PublicKeyBytes(input_bytes: bytes) -> PublicKeyBytes:
    return PublicKeyBytes(bytes48(input_bytes))


def bytes_to_SignatureBytes(input_bytes: bytes) -> SignatureBytes:
    return SignatureBytes(bytes96(input_bytes))


def bytes_to_PuzzleHash(input_bytes: bytes) -> PuzzleHash:
    return PuzzleHash(bytes32(input_bytes))


def bytes_to_CoinID(input_bytes: bytes) -> CoinID:
    return CoinID(bytes32(input_bytes))


def bytes_to_SpendBundleID(input_bytes: bytes) -> SpendBundleID:
    return SpendBundleID(bytes32(input_bytes))


def bytes_to_BlockRecordHeaderHash(input_bytes: bytes) -> BlockRecordHeaderHash:
    return BlockRecordHeaderHash(bytes32(input_bytes))
