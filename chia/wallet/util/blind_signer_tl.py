from __future__ import annotations

from dataclasses import field
from typing import List

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.wallet.signer_protocol import (
    KeyHints,
    PathHint,
    SigningInstructions,
    SigningResponse,
    SigningTarget,
    SumHint,
    TransactionInfo,
    UnsignedTransaction,
)
from chia.wallet.util.clvm_streamable import ClvmStreamable, TransportLayer, TransportLayerMapping

# Pylint doesn't understand that these classes are in fact dataclasses
# pylint: disable=invalid-field-call


class BSTLSigningTarget(ClvmStreamable):
    fingerprint: bytes = field(metadata=dict(key="f"))
    message: bytes = field(metadata=dict(key="m"))
    hook: bytes32 = field(metadata=dict(key="h"))

    @staticmethod
    def from_wallet_api(_from: SigningTarget) -> BSTLSigningTarget:
        return BSTLSigningTarget(**_from.__dict__)

    @staticmethod
    def to_wallet_api(_from: BSTLSigningTarget) -> SigningTarget:
        return SigningTarget(**_from.__dict__)


class BSTLSumHint(ClvmStreamable):
    fingerprints: List[bytes] = field(metadata=dict(key="f"))
    synthetic_offset: bytes = field(metadata=dict(key="o"))
    final_pubkey: bytes = field(metadata=dict(key="p"))

    @staticmethod
    def from_wallet_api(_from: SumHint) -> BSTLSumHint:
        return BSTLSumHint(**_from.__dict__)

    @staticmethod
    def to_wallet_api(_from: BSTLSumHint) -> SumHint:
        return SumHint(**_from.__dict__)


class BSTLPathHint(ClvmStreamable):
    root_fingerprint: bytes = field(metadata=dict(key="f"))
    path: List[uint64] = field(metadata=dict(key="p"))

    @staticmethod
    def from_wallet_api(_from: PathHint) -> BSTLPathHint:
        return BSTLPathHint(**_from.__dict__)

    @staticmethod
    def to_wallet_api(_from: BSTLPathHint) -> PathHint:
        return PathHint(**_from.__dict__)


class BSTLSigningInstructions(ClvmStreamable):
    sum_hints: List[BSTLSumHint] = field(metadata=dict(key="s"))
    path_hints: List[BSTLPathHint] = field(metadata=dict(key="p"))
    targets: List[BSTLSigningTarget] = field(metadata=dict(key="t"))

    @staticmethod
    def from_wallet_api(_from: SigningInstructions) -> BSTLSigningInstructions:
        return BSTLSigningInstructions(
            [BSTLSumHint(**sum_hint.__dict__) for sum_hint in _from.key_hints.sum_hints],
            [BSTLPathHint(**path_hint.__dict__) for path_hint in _from.key_hints.path_hints],
            [BSTLSigningTarget(**signing_target.__dict__) for signing_target in _from.targets],
        )

    @staticmethod
    def to_wallet_api(_from: BSTLSigningInstructions) -> SigningInstructions:
        return SigningInstructions(
            KeyHints(
                [SumHint(**sum_hint.__dict__) for sum_hint in _from.sum_hints],
                [PathHint(**path_hint.__dict__) for path_hint in _from.path_hints],
            ),
            [SigningTarget(**signing_target.__dict__) for signing_target in _from.targets],
        )


class BSTLUnsignedTransaction(ClvmStreamable):
    sum_hints: List[BSTLSumHint] = field(metadata=dict(key="s"))
    path_hints: List[BSTLPathHint] = field(metadata=dict(key="p"))
    targets: List[BSTLSigningTarget] = field(metadata=dict(key="t"))

    @staticmethod
    def from_wallet_api(_from: UnsignedTransaction) -> BSTLUnsignedTransaction:
        return BSTLUnsignedTransaction(
            [BSTLSumHint(**sum_hint.__dict__) for sum_hint in _from.signing_instructions.key_hints.sum_hints],
            [BSTLPathHint(**path_hint.__dict__) for path_hint in _from.signing_instructions.key_hints.path_hints],
            [BSTLSigningTarget(**signing_target.__dict__) for signing_target in _from.signing_instructions.targets],
        )

    @staticmethod
    def to_wallet_api(_from: BSTLUnsignedTransaction) -> UnsignedTransaction:
        return UnsignedTransaction(
            TransactionInfo([]),
            SigningInstructions(
                KeyHints(
                    [SumHint(**sum_hint.__dict__) for sum_hint in _from.sum_hints],
                    [PathHint(**path_hint.__dict__) for path_hint in _from.path_hints],
                ),
                [SigningTarget(**signing_target.__dict__) for signing_target in _from.targets],
            ),
        )


class BSTLSigningResponse(ClvmStreamable):
    signature: bytes = field(metadata=dict(key="s"))
    hook: bytes32 = field(metadata=dict(key="h"))

    @staticmethod
    def from_wallet_api(_from: SigningResponse) -> BSTLSigningResponse:
        return BSTLSigningResponse(**_from.__dict__)

    @staticmethod
    def to_wallet_api(_from: BSTLSigningResponse) -> SigningResponse:
        return SigningResponse(**_from.__dict__)


BLIND_SIGNER_TRANSPORT = TransportLayer(
    [
        TransportLayerMapping(
            SigningTarget, BSTLSigningTarget, BSTLSigningTarget.from_wallet_api, BSTLSigningTarget.to_wallet_api
        ),
        TransportLayerMapping(SumHint, BSTLSumHint, BSTLSumHint.from_wallet_api, BSTLSumHint.to_wallet_api),
        TransportLayerMapping(PathHint, BSTLPathHint, BSTLPathHint.from_wallet_api, BSTLPathHint.to_wallet_api),
        TransportLayerMapping(
            SigningInstructions,
            BSTLSigningInstructions,
            BSTLSigningInstructions.from_wallet_api,
            BSTLSigningInstructions.to_wallet_api,
        ),
        TransportLayerMapping(
            SigningResponse, BSTLSigningResponse, BSTLSigningResponse.from_wallet_api, BSTLSigningResponse.to_wallet_api
        ),
        TransportLayerMapping(
            UnsignedTransaction,
            BSTLUnsignedTransaction,
            BSTLUnsignedTransaction.from_wallet_api,
            BSTLUnsignedTransaction.to_wallet_api,
        ),
    ]
)
