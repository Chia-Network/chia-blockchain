from __future__ import annotations

from dataclasses import dataclass
from typing import List

from chia.rpc.util import RequestType
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.streamable import Streamable, streamable
from chia.wallet.util.signer_protocol import SignedTransaction, SigningInstructions, SigningResponse, Spend


class GatherSigningInfo(RequestType):
    spends: List[Spend]


@streamable
@dataclass(frozen=True)
class GatherSigningInfoResponse(Streamable):
    signing_instructions: SigningInstructions


class ApplySignatures(RequestType):
    spends: List[Spend]
    signing_responses: List[SigningResponse]


@streamable
@dataclass(frozen=True)
class ApplySignaturesResponse(Streamable):
    signed_transactions: List[SignedTransaction]


class SubmitTransactions(RequestType):
    signed_transactions: List[SignedTransaction]


@streamable
@dataclass(frozen=True)
class SubmitTransactionsResponse(Streamable):
    mempool_ids: List[bytes32]
