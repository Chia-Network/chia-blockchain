from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.util.streamable import Streamable
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
from chia.wallet.util.clvm_streamable import TranslationLayer, TranslationLayerMapping, clvm_streamable

# Pylint doesn't understand that these classes are in fact dataclasses
# pylint: disable=invalid-field-call


@clvm_streamable
@dataclass(frozen=True)
class BSTLSigningTarget(Streamable):
    fingerprint: bytes = field(metadata=dict(key="f"))
    message: bytes = field(metadata=dict(key="m"))
    hook: bytes32 = field(metadata=dict(key="h"))

    @staticmethod
    def from_wallet_api(_from: SigningTarget) -> BSTLSigningTarget:
        return BSTLSigningTarget(**_from.__dict__)

    @staticmethod
    def to_wallet_api(_from: BSTLSigningTarget) -> SigningTarget:
        return SigningTarget(**_from.__dict__)


@clvm_streamable
@dataclass(frozen=True)
class BSTLSumHint(Streamable):
    fingerprints: List[bytes] = field(metadata=dict(key="f"))
    synthetic_offset: bytes = field(metadata=dict(key="o"))
    final_pubkey: bytes = field(metadata=dict(key="p"))

    @staticmethod
    def from_wallet_api(_from: SumHint) -> BSTLSumHint:
        return BSTLSumHint(**_from.__dict__)

    @staticmethod
    def to_wallet_api(_from: BSTLSumHint) -> SumHint:
        return SumHint(**_from.__dict__)


@clvm_streamable
@dataclass(frozen=True)
class BSTLPathHint(Streamable):
    root_fingerprint: bytes = field(metadata=dict(key="f"))
    path: List[uint64] = field(metadata=dict(key="p"))

    @staticmethod
    def from_wallet_api(_from: PathHint) -> BSTLPathHint:
        return BSTLPathHint(**_from.__dict__)

    @staticmethod
    def to_wallet_api(_from: BSTLPathHint) -> PathHint:
        return PathHint(**_from.__dict__)


@clvm_streamable
@dataclass(frozen=True)
class BSTLSigningInstructions(Streamable):
    sum_hints: List[BSTLSumHint] = field(metadata=dict(key="s"))
    path_hints: List[BSTLPathHint] = field(metadata=dict(key="p"))
    targets: List[BSTLSigningTarget] = field(metadata=dict(key="t"))

    @staticmethod
    def from_wallet_api(_from: SigningInstructions) -> BSTLSigningInstructions:
        return BSTLSigningInstructions(
            [BSTLSumHint.from_wallet_api(sum_hint) for sum_hint in _from.key_hints.sum_hints],
            [BSTLPathHint.from_wallet_api(path_hint) for path_hint in _from.key_hints.path_hints],
            [BSTLSigningTarget.from_wallet_api(signing_target) for signing_target in _from.targets],
        )

    @staticmethod
    def to_wallet_api(_from: BSTLSigningInstructions) -> SigningInstructions:
        return SigningInstructions(
            KeyHints(
                [BSTLSumHint.to_wallet_api(sum_hint) for sum_hint in _from.sum_hints],
                [BSTLPathHint.to_wallet_api(path_hint) for path_hint in _from.path_hints],
            ),
            [BSTLSigningTarget.to_wallet_api(signing_target) for signing_target in _from.targets],
        )


@clvm_streamable
@dataclass(frozen=True)
class BSTLUnsignedTransaction(Streamable):
    sum_hints: List[BSTLSumHint] = field(metadata=dict(key="s"))
    path_hints: List[BSTLPathHint] = field(metadata=dict(key="p"))
    targets: List[BSTLSigningTarget] = field(metadata=dict(key="t"))

    @staticmethod
    def from_wallet_api(_from: UnsignedTransaction) -> BSTLUnsignedTransaction:
        return BSTLUnsignedTransaction(
            [BSTLSumHint.from_wallet_api(sum_hint) for sum_hint in _from.signing_instructions.key_hints.sum_hints],
            [BSTLPathHint.from_wallet_api(path_hint) for path_hint in _from.signing_instructions.key_hints.path_hints],
            [
                BSTLSigningTarget.from_wallet_api(signing_target)
                for signing_target in _from.signing_instructions.targets
            ],
        )

    @staticmethod
    def to_wallet_api(_from: BSTLUnsignedTransaction) -> UnsignedTransaction:
        return UnsignedTransaction(
            TransactionInfo([]),
            SigningInstructions(
                KeyHints(
                    [BSTLSumHint.to_wallet_api(sum_hint) for sum_hint in _from.sum_hints],
                    [BSTLPathHint.to_wallet_api(path_hint) for path_hint in _from.path_hints],
                ),
                [BSTLSigningTarget.to_wallet_api(signing_target) for signing_target in _from.targets],
            ),
        )


@clvm_streamable
@dataclass(frozen=True)
class BSTLSigningResponse(Streamable):
    signature: bytes = field(metadata=dict(key="s"))
    hook: bytes32 = field(metadata=dict(key="h"))

    @staticmethod
    def from_wallet_api(_from: SigningResponse) -> BSTLSigningResponse:
        return BSTLSigningResponse(**_from.__dict__)

    @staticmethod
    def to_wallet_api(_from: BSTLSigningResponse) -> SigningResponse:
        return SigningResponse(**_from.__dict__)


BLIND_SIGNER_TRANSLATION = TranslationLayer(
    [
        TranslationLayerMapping(
            SigningTarget, BSTLSigningTarget, BSTLSigningTarget.from_wallet_api, BSTLSigningTarget.to_wallet_api
        ),
        TranslationLayerMapping(SumHint, BSTLSumHint, BSTLSumHint.from_wallet_api, BSTLSumHint.to_wallet_api),
        TranslationLayerMapping(PathHint, BSTLPathHint, BSTLPathHint.from_wallet_api, BSTLPathHint.to_wallet_api),
        TranslationLayerMapping(
            SigningInstructions,
            BSTLSigningInstructions,
            BSTLSigningInstructions.from_wallet_api,
            BSTLSigningInstructions.to_wallet_api,
        ),
        TranslationLayerMapping(
            SigningResponse, BSTLSigningResponse, BSTLSigningResponse.from_wallet_api, BSTLSigningResponse.to_wallet_api
        ),
        TranslationLayerMapping(
            UnsignedTransaction,
            BSTLUnsignedTransaction,
            BSTLUnsignedTransaction.from_wallet_api,
            BSTLUnsignedTransaction.to_wallet_api,
        ),
    ]
)
