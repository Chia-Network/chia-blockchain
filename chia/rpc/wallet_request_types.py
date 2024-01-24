from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Type, TypeVar

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle import SpendBundle
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint32
from chia.util.streamable import Streamable, streamable
from chia.wallet.signer_protocol import (
    SignedTransaction,
    SigningInstructions,
    SigningResponse,
    Spend,
    UnsignedTransaction,
)
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.offer import Offer
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.vc_wallet.vc_store import VCRecord

_T_OfferEndpointResponse = TypeVar("_T_OfferEndpointResponse", bound="_OfferEndpointResponse")


@streamable
@dataclass(frozen=True)
class GatherSigningInfo(Streamable):
    spends: List[Spend]


@streamable
@dataclass(frozen=True)
class GatherSigningInfoResponse(Streamable):
    signing_instructions: SigningInstructions


@streamable
@dataclass(frozen=True)
class ApplySignatures(Streamable):
    spends: List[Spend]
    signing_responses: List[SigningResponse]


@streamable
@dataclass(frozen=True)
class ApplySignaturesResponse(Streamable):
    signed_transactions: List[SignedTransaction]


@streamable
@dataclass(frozen=True)
class SubmitTransactions(Streamable):
    signed_transactions: List[SignedTransaction]


@streamable
@dataclass(frozen=True)
class SubmitTransactionsResponse(Streamable):
    mempool_ids: List[bytes32]


@streamable
@dataclass(frozen=True)
class ExecuteSigningInstructions(Streamable):
    signing_instructions: SigningInstructions
    partial_allowed: bool


@streamable
@dataclass(frozen=True)
class ExecuteSigningInstructionsResponse(Streamable):
    signing_responses: List[SigningResponse]


@streamable
@dataclass(frozen=True)
class TransactionEndpointResponse(Streamable):
    unsigned_transactions: List[UnsignedTransaction]
    transactions: List[TransactionRecord]


# TODO: The section below needs corresponding request types
# TODO: The section below should be added to the API (currently only for client)
@streamable
@dataclass(frozen=True)
class SendTransactionResponse(TransactionEndpointResponse):
    transaction: TransactionRecord
    transaction_id: bytes32


@streamable
@dataclass(frozen=True)
class SendTransactionMultiResponse(TransactionEndpointResponse):
    transaction: TransactionRecord
    transaction_id: bytes32


@streamable
@dataclass(frozen=True)
class CreateSignedTransactionsResponse(TransactionEndpointResponse):
    signed_txs: List[TransactionRecord]
    signed_tx: TransactionRecord


@streamable
@dataclass(frozen=True)
class DIDUpdateRecoveryIDsResponse(TransactionEndpointResponse):
    pass


@streamable
@dataclass(frozen=True)
class DIDMessageSpendResponse(TransactionEndpointResponse):
    spend_bundle: SpendBundle


@streamable
@dataclass(frozen=True)
class DIDUpdateMetadataResponse(TransactionEndpointResponse):
    spend_bundle: SpendBundle
    wallet_id: uint32


@streamable
@dataclass(frozen=True)
class DIDTransferDIDResponse(TransactionEndpointResponse):
    transaction: TransactionRecord
    transaction_id: bytes32


@streamable
@dataclass(frozen=True)
class CATSpendResponse(TransactionEndpointResponse):
    transaction: TransactionRecord
    transaction_id: bytes32


@streamable
@dataclass(frozen=True)
class _OfferEndpointResponse(TransactionEndpointResponse):
    offer: Offer
    trade_record: TradeRecord

    @classmethod
    def from_json_dict(cls: Type[_T_OfferEndpointResponse], json_dict: Dict[str, Any]) -> _T_OfferEndpointResponse:
        tx_endpoint: TransactionEndpointResponse = TransactionEndpointResponse.from_json_dict(json_dict)
        try:
            offer: Offer = Offer.from_bech32(json_dict["offer"])
        except Exception:
            offer = Offer.from_bytes(hexstr_to_bytes(json_dict["offer"]))

        return cls(
            **tx_endpoint.__dict__,
            offer=offer,
            trade_record=TradeRecord.from_json_dict_convenience(json_dict["trade_record"], bytes(offer).hex()),
        )


@streamable
@dataclass(frozen=True)
class CreateOfferForIDsResponse(_OfferEndpointResponse):
    pass


@streamable
@dataclass(frozen=True)
class TakeOfferResponse(_OfferEndpointResponse):  # Inheriting for de-dup sake
    pass


@streamable
@dataclass(frozen=True)
class CancelOfferResponse(TransactionEndpointResponse):
    pass


@streamable
@dataclass(frozen=True)
class CancelOffersResponse(TransactionEndpointResponse):
    pass


@streamable
@dataclass(frozen=True)
class NFTMintNFTResponse(TransactionEndpointResponse):
    wallet_id: uint32
    spend_bundle: SpendBundle
    nft_id: str


@streamable
@dataclass(frozen=True)
class NFTAddURIResponse(TransactionEndpointResponse):
    wallet_id: uint32
    spend_bundle: SpendBundle


@streamable
@dataclass(frozen=True)
class NFTTransferNFTResponse(TransactionEndpointResponse):
    wallet_id: uint32
    spend_bundle: SpendBundle


@streamable
@dataclass(frozen=True)
class NFTSetNFTDIDResponse(TransactionEndpointResponse):
    wallet_id: uint32
    spend_bundle: SpendBundle


@streamable
@dataclass(frozen=True)
class NFTMintBulkResponse(TransactionEndpointResponse):
    spend_bundle: SpendBundle
    nft_id_list: List[str]


@streamable
@dataclass(frozen=True)
class CreateNewDAOWalletResponse(TransactionEndpointResponse):
    type: uint32
    wallet_id: uint32
    treasury_id: bytes32
    cat_wallet_id: uint32
    dao_cat_wallet_id: uint32


@streamable
@dataclass(frozen=True)
class DAOCreateProposalResponse(TransactionEndpointResponse):
    proposal_id: bytes32
    tx_id: bytes32
    tx: TransactionRecord


@streamable
@dataclass(frozen=True)
class DAOVoteOnProposalResponse(TransactionEndpointResponse):
    tx_id: bytes32
    tx: TransactionRecord


@streamable
@dataclass(frozen=True)
class DAOCloseProposalResponse(TransactionEndpointResponse):
    tx_id: bytes32
    tx: TransactionRecord


@streamable
@dataclass(frozen=True)
class DAOFreeCoinsFromFinishedProposalsResponse(TransactionEndpointResponse):
    tx_id: bytes32
    tx: TransactionRecord


@streamable
@dataclass(frozen=True)
class DAOAddFundsToTreasuryResponse(TransactionEndpointResponse):
    tx_id: bytes32
    tx: TransactionRecord


@streamable
@dataclass(frozen=True)
class DAOSendToLockupResponse(TransactionEndpointResponse):
    tx_id: bytes32
    txs: List[TransactionRecord]


@streamable
@dataclass(frozen=True)
class DAOExitLockupResponse(TransactionEndpointResponse):
    tx_id: bytes32
    tx: TransactionRecord


@streamable
@dataclass(frozen=True)
class VCMintResponse(TransactionEndpointResponse):
    vc_record: VCRecord


@streamable
@dataclass(frozen=True)
class VCSpendResponse(TransactionEndpointResponse):
    pass


@streamable
@dataclass(frozen=True)
class VCRevokeResponse(TransactionEndpointResponse):
    pass
