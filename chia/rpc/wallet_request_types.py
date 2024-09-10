# pylint: disable=invalid-field-call

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type, TypeVar

from chia_rs import G1Element, G2Element
from typing_extensions import dataclass_transform

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint16, uint32, uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.notification_store import Notification
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
from chia.wallet.util.clvm_streamable import json_deserialize_with_clvm_streamable
from chia.wallet.vc_wallet.vc_store import VCRecord
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

_T_OfferEndpointResponse = TypeVar("_T_OfferEndpointResponse", bound="_OfferEndpointResponse")


@dataclass_transform(frozen_default=True, kw_only_default=True)
def kw_only_dataclass(cls: Type[Any]) -> Type[Any]:
    if sys.version_info < (3, 10):
        return dataclass(frozen=True)(cls)  # pragma: no cover
    else:
        return dataclass(frozen=True, kw_only=True)(cls)


def default_raise() -> Any:  # pragma: no cover
    raise RuntimeError("This should be impossible to hit and is just for < 3.10 compatibility")


@streamable
@dataclass(frozen=True)
class GetNotifications(Streamable):
    ids: Optional[List[bytes32]] = None
    start: Optional[uint32] = None
    end: Optional[uint32] = None


@streamable
@dataclass(frozen=True)
class GetNotificationsResponse(Streamable):
    notifications: List[Notification]


@streamable
@dataclass(frozen=True)
class VerifySignature(Streamable):
    message: str
    pubkey: G1Element
    signature: G2Element
    signing_mode: Optional[str] = None
    address: Optional[str] = None


@streamable
@dataclass(frozen=True)
class VerifySignatureResponse(Streamable):
    isValid: bool
    error: Optional[str] = None


@streamable
@dataclass(frozen=True)
class GetTransactionMemo(Streamable):
    transaction_id: bytes32


# utility type for GetTransactionMemoResponse
@streamable
@dataclass(frozen=True)
class CoinIDWithMemos(Streamable):
    coin_id: bytes32
    memos: List[bytes]


@streamable
@dataclass(frozen=True)
class GetTransactionMemoResponse(Streamable):
    transaction_id: bytes32
    coins_with_memos: List[CoinIDWithMemos]

    # TODO: deprecate the kinda silly format of this RPC and delete these functions
    def to_json_dict(self) -> Dict[str, Any]:
        return {
            self.transaction_id.hex(): {
                cwm.coin_id.hex(): [memo.hex() for memo in cwm.memos] for cwm in self.coins_with_memos
            }
        }

    @classmethod
    def from_json_dict(cls, json_dict: Dict[str, Any]) -> GetTransactionMemoResponse:
        return cls(
            bytes32.from_hexstr(list(json_dict.keys())[0]),
            [
                CoinIDWithMemos(bytes32.from_hexstr(coin_id), [bytes32.from_hexstr(memo) for memo in memos])
                for coin_id, memos in list(json_dict.values())[0].items()
            ],
        )


@streamable
@dataclass(frozen=True)
class GetOffersCountResponse(Streamable):
    total: uint16
    my_offers_count: uint16
    taken_offers_count: uint16


@streamable
@dataclass(frozen=True)
class DefaultCAT(Streamable):
    asset_id: bytes32
    name: str
    symbol: str


@streamable
@dataclass(frozen=True)
class GetCATListResponse(Streamable):
    cat_list: List[DefaultCAT]


@streamable
@dataclass(frozen=True)
class DIDGetPubkey(Streamable):
    wallet_id: uint32


@streamable
@dataclass(frozen=True)
class DIDGetPubkeyResponse(Streamable):
    pubkey: G1Element


@streamable
@dataclass(frozen=True)
class DIDGetRecoveryInfo(Streamable):
    wallet_id: uint32


@streamable
@dataclass(frozen=True)
class DIDGetRecoveryInfoResponse(Streamable):
    wallet_id: uint32
    my_did: str
    coin_name: bytes32
    newpuzhash: bytes32
    pubkey: G1Element
    backup_dids: List[bytes32]


@streamable
@dataclass(frozen=True)
class DIDGetCurrentCoinInfo(Streamable):
    wallet_id: uint32


@streamable
@dataclass(frozen=True)
class DIDGetCurrentCoinInfoResponse(Streamable):
    wallet_id: uint32
    my_did: str
    did_parent: bytes32
    did_innerpuz: bytes32
    did_amount: uint64


@streamable
@dataclass(frozen=True)
class NFTGetByDID(Streamable):
    did_id: Optional[str] = None


@streamable
@dataclass(frozen=True)
class NFTGetByDIDResponse(Streamable):
    wallet_id: uint32


@streamable
@dataclass(frozen=True)
class NFTSetNFTStatus(Streamable):
    wallet_id: uint32
    coin_id: bytes32
    in_transaction: bool


# utility for NFTGetWalletsWithDIDsResponse
@streamable
@dataclass(frozen=True)
class NFTWalletWithDID(Streamable):
    wallet_id: uint32
    did_id: str
    did_wallet_id: uint32


@streamable
@dataclass(frozen=True)
class NFTGetWalletsWithDIDsResponse(Streamable):
    nft_wallets: List[NFTWalletWithDID]


# utility for NFTSetDIDBulk
@streamable
@dataclass(frozen=True)
class NFTCoin(Streamable):
    nft_coin_id: str
    wallet_id: uint32


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
    partial_allowed: bool = False


@streamable
@dataclass(frozen=True)
class ExecuteSigningInstructionsResponse(Streamable):
    signing_responses: List[SigningResponse]


# When inheriting from this class you must set any non default arguments with:
# field(default_factory=default_raise)
# (this is for < 3.10 compatibility)
@streamable
@kw_only_dataclass
class TransactionEndpointRequest(Streamable):
    fee: uint64 = uint64(0)
    push: Optional[bool] = None


@streamable
@dataclass(frozen=True)
class TransactionEndpointResponse(Streamable):
    unsigned_transactions: List[UnsignedTransaction]
    transactions: List[TransactionRecord]


@streamable
@kw_only_dataclass
class SplitCoins(TransactionEndpointRequest):
    wallet_id: uint32 = field(default_factory=default_raise)
    number_of_coins: uint16 = field(default_factory=default_raise)
    amount_per_coin: uint64 = field(default_factory=default_raise)
    target_coin_id: bytes32 = field(default_factory=default_raise)


@streamable
@dataclass(frozen=True)
class SplitCoinsResponse(TransactionEndpointResponse):
    pass


@streamable
@kw_only_dataclass
class CombineCoins(TransactionEndpointRequest):
    wallet_id: uint32 = field(default_factory=default_raise)
    number_of_coins: uint16 = field(default_factory=default_raise)
    largest_first: bool = False
    target_coin_ids: List[bytes32] = field(default_factory=list)
    target_coin_amount: Optional[uint64] = None
    coin_num_limit: uint16 = uint16(500)


@streamable
@dataclass(frozen=True)
class CombineCoinsResponse(TransactionEndpointResponse):
    pass


@streamable
@kw_only_dataclass
class NFTSetDIDBulk(TransactionEndpointRequest):
    nft_coin_list: List[NFTCoin] = field(default_factory=default_raise)
    did_id: Optional[str] = None


@streamable
@dataclass(frozen=True)
class NFTSetDIDBulkResponse(TransactionEndpointResponse):
    wallet_id: List[uint32]
    tx_num: uint16
    spend_bundle: WalletSpendBundle


@streamable
@kw_only_dataclass
class NFTTransferBulk(TransactionEndpointRequest):
    nft_coin_list: List[NFTCoin] = field(default_factory=default_raise)
    target_address: str = field(default_factory=default_raise)


@streamable
@dataclass(frozen=True)
class NFTTransferBulkResponse(TransactionEndpointResponse):
    wallet_id: List[uint32]
    tx_num: uint16
    spend_bundle: WalletSpendBundle


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
    spend_bundle: WalletSpendBundle


@streamable
@dataclass(frozen=True)
class DIDUpdateMetadataResponse(TransactionEndpointResponse):
    spend_bundle: WalletSpendBundle
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
        tx_endpoint: TransactionEndpointResponse = json_deserialize_with_clvm_streamable(
            json_dict, TransactionEndpointResponse
        )
        offer: Offer = Offer.from_bech32(json_dict["offer"])

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
    spend_bundle: WalletSpendBundle
    nft_id: str


@streamable
@dataclass(frozen=True)
class NFTAddURIResponse(TransactionEndpointResponse):
    wallet_id: uint32
    spend_bundle: WalletSpendBundle


@streamable
@dataclass(frozen=True)
class NFTTransferNFTResponse(TransactionEndpointResponse):
    wallet_id: uint32
    spend_bundle: WalletSpendBundle


@streamable
@dataclass(frozen=True)
class NFTSetNFTDIDResponse(TransactionEndpointResponse):
    wallet_id: uint32
    spend_bundle: WalletSpendBundle


@streamable
@dataclass(frozen=True)
class NFTMintBulkResponse(TransactionEndpointResponse):
    spend_bundle: WalletSpendBundle
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
