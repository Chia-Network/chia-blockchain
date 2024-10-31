from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, BinaryIO, Optional, TypeVar

from chia_rs import G1Element, G2Element, PrivateKey
from chia_rs.sized_ints import uint8
from typing_extensions import dataclass_transform

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint16, uint32, uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.conditions import Condition, ConditionValidTimes
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
from chia.wallet.transaction_sorting import SortKey
from chia.wallet.util.clvm_streamable import json_deserialize_with_clvm_streamable
from chia.wallet.util.query_filter import TransactionTypeFilter
from chia.wallet.util.tx_config import TXConfig
from chia.wallet.vc_wallet.vc_store import VCRecord
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_node import Balance
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

_T_OfferEndpointResponse = TypeVar("_T_OfferEndpointResponse", bound="_OfferEndpointResponse")


@dataclass_transform(frozen_default=True, kw_only_default=True)
def kw_only_dataclass(cls: type[Any]) -> type[Any]:
    if sys.version_info < (3, 10):
        return dataclass(frozen=True)(cls)  # pragma: no cover
    else:
        return dataclass(frozen=True, kw_only=True)(cls)


def default_raise() -> Any:  # pragma: no cover
    raise RuntimeError("This should be impossible to hit and is just for < 3.10 compatibility")


class UserFriendlyMemos:
    unfriendly_memos: list[tuple[bytes32, list[bytes]]]

    def __init__(self, unfriendly_memos: list[tuple[bytes32, list[bytes]]]) -> None:
        self.unfriendly_memos = unfriendly_memos

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, UserFriendlyMemos) and other.unfriendly_memos == self.unfriendly_memos:
            return True
        else:
            return False

    def __bytes__(self) -> bytes:
        raise NotImplementedError("Should not be serializing this object as bytes, it's only for RPC")

    @classmethod
    def parse(cls, f: BinaryIO) -> UserFriendlyMemos:
        raise NotImplementedError("Should not be deserializing this object from a stream, it's only for RPC")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "0x" + coin_id.hex(): "0x" + memo.hex()
            for coin_id, memos in self.unfriendly_memos
            for memo in memos
            if memo is not None
        }

    @classmethod
    def from_json_dict(cls, json_dict: dict[str, Any]) -> UserFriendlyMemos:
        return UserFriendlyMemos(
            [(bytes32.from_hexstr(coin_id), [hexstr_to_bytes(memo)]) for coin_id, memo in json_dict.items()]
        )


_T_UserFriendlyTransactionRecord = TypeVar("_T_UserFriendlyTransactionRecord", bound="UserFriendlyTransactionRecord")


@streamable
@dataclass(frozen=True)
class UserFriendlyTransactionRecord(TransactionRecord):
    to_address: str
    memos: UserFriendlyMemos  # type: ignore[assignment]

    def get_memos(self) -> dict[bytes32, list[bytes]]:
        return {coin_id: ms for coin_id, ms in self.memos.unfriendly_memos}

    def to_transaction_record(self) -> TransactionRecord:
        return TransactionRecord.from_json_dict_convenience(self.to_json_dict())

    @classmethod
    def from_transaction_record(
        cls: type[_T_UserFriendlyTransactionRecord], tx: TransactionRecord, config: dict[str, Any]
    ) -> _T_UserFriendlyTransactionRecord:
        dict_convenience = tx.to_json_dict_convenience(config)
        return cls.from_json_dict(dict_convenience)


@streamable
@dataclass(frozen=True)
class Empty(Streamable):
    pass


@streamable
@dataclass(frozen=True)
class LogIn(Streamable):
    fingerprint: uint32


@streamable
@dataclass(frozen=True)
class LogInResponse(Streamable):
    fingerprint: uint32


@streamable
@dataclass(frozen=True)
class GetLoggedInFingerprintResponse(Streamable):
    fingerprint: Optional[uint32]


@streamable
@dataclass(frozen=True)
class GetPublicKeysResponse(Streamable):
    keyring_is_locked: bool
    public_key_fingerprints: Optional[list[uint32]] = None

    @property
    def pk_fingerprints(self) -> list[uint32]:
        if self.keyring_is_locked:
            raise RuntimeError("get_public_keys cannot return public keys because the keyring is locked")
        else:
            assert self.public_key_fingerprints is not None
            return self.public_key_fingerprints


@streamable
@dataclass(frozen=True)
class GetPrivateKey(Streamable):
    fingerprint: uint32


# utility for `GetPrivateKeyResponse`
@streamable
@dataclass(frozen=True)
class GetPrivateKeyFormat(Streamable):
    fingerprint: uint32
    sk: PrivateKey
    pk: G1Element
    farmer_pk: G1Element
    pool_pk: G1Element
    seed: Optional[str]


@streamable
@dataclass(frozen=True)
class GetPrivateKeyResponse(Streamable):
    private_key: GetPrivateKeyFormat


@streamable
@dataclass(frozen=True)
class GenerateMnemonicResponse(Streamable):
    mnemonic: list[str]


@streamable
@dataclass(frozen=True)
class AddKey(Streamable):
    mnemonic: list[str]


@streamable
@dataclass(frozen=True)
class AddKeyResponse(Streamable):
    fingerprint: uint32


@streamable
@dataclass(frozen=True)
class DeleteKey(Streamable):
    fingerprint: uint32


@streamable
@dataclass(frozen=True)
class CheckDeleteKey(Streamable):
    fingerprint: uint32
    max_ph_to_search: uint16 = uint16(100)


@streamable
@dataclass(frozen=True)
class CheckDeleteKeyResponse(Streamable):
    fingerprint: uint32
    used_for_farmer_rewards: bool
    used_for_pool_rewards: bool
    wallet_balance: bool


@streamable
@dataclass(frozen=True)
class SetWalletResyncOnStartup(Streamable):
    enable: bool = True


@streamable
@dataclass(frozen=True)
class GetSyncStatusResponse(Streamable):
    synced: bool
    syncing: bool
    genesis_initialized: bool = True


@streamable
@dataclass(frozen=True)
class GetHeightInfoResponse(Streamable):
    height: uint32


@streamable
@dataclass(frozen=True)
class PushTX(Streamable):
    spend_bundle: WalletSpendBundle

    # We allow for flexibility in transaction parsing here so we need to override
    @classmethod
    def from_json_dict(cls, json_dict: dict[str, Any]) -> PushTX:
        if isinstance(json_dict["spend_bundle"], str):
            spend_bundle = WalletSpendBundle.from_bytes(hexstr_to_bytes(json_dict["spend_bundle"]))
        else:
            spend_bundle = WalletSpendBundle.from_json_dict(json_dict["spend_bundle"])

        json_dict["spend_bundle"] = spend_bundle.to_json_dict()
        return super().from_json_dict(json_dict)


@streamable
@dataclass(frozen=True)
class GetTimestampForHeight(Streamable):
    height: uint32


@streamable
@dataclass(frozen=True)
class GetTimestampForHeightResponse(Streamable):
    timestamp: uint64


@streamable
@dataclass(frozen=True)
class GetWallets(Streamable):
    type: Optional[uint16] = None
    include_data: bool = True


# utility for GetWalletsResponse
@streamable
@dataclass(frozen=True)
class WalletInfoResponse(WalletInfo):
    authorized_providers: list[bytes32] = field(default_factory=list)
    flags_needed: list[str] = field(default_factory=list)


@streamable
@dataclass(frozen=True)
class GetWalletsResponse(Streamable):
    wallets: list[WalletInfoResponse]
    fingerprint: Optional[uint32] = None


@streamable
@dataclass(frozen=True)
class GetWalletBalance(Streamable):
    wallet_id: uint32


@streamable
@dataclass(frozen=True)
class GetWalletBalances(Streamable):
    wallet_ids: Optional[list[uint32]] = None


# utility for GetWalletBalanceResponse(s)
@streamable
@kw_only_dataclass
class BalanceResponse(Balance):
    wallet_id: uint32 = field(default_factory=default_raise)
    wallet_type: uint8 = field(default_factory=default_raise)
    fingerprint: Optional[uint32] = None
    asset_id: Optional[bytes32] = None
    pending_approval_balance: Optional[uint64] = None


@streamable
@dataclass(frozen=True)
class GetWalletBalanceResponse(Streamable):
    wallet_balance: BalanceResponse


@streamable
@dataclass(frozen=True)
class GetWalletBalancesResponse(Streamable):
    wallet_balances: list[BalanceResponse]

    @property
    def wallet_balances_dict(self) -> dict[uint32, BalanceResponse]:
        return {response.wallet_id: response for response in self.wallet_balances}

    # special dict format that streamable can't handle natively
    def to_json_dict(self) -> dict[str, Any]:
        return {
            "wallet_balances": {
                str(wallet_id): response.to_json_dict() for wallet_id, response in self.wallet_balances_dict.items()
            }
        }

    @classmethod
    def from_json_dict(cls, json_dict: dict[str, Any]) -> GetWalletBalancesResponse:
        return super().from_json_dict(
            {"wallet_balances": [balance_response for balance_response in json_dict["wallet_balances"].values()]}
        )


@streamable
@dataclass(frozen=True)
class GetTransaction(Streamable):
    transaction_id: bytes32


@streamable
@dataclass(frozen=True)
class GetTransactionResponse(Streamable):
    transaction: UserFriendlyTransactionRecord
    transaction_id: bytes32


@streamable
@dataclass(frozen=True)
class GetTransactions(Streamable):
    wallet_id: uint32
    start: Optional[uint16] = None
    end: Optional[uint16] = None
    sort_key: Optional[str] = None
    reverse: bool = False
    to_address: Optional[str] = None
    type_filter: Optional[TransactionTypeFilter] = None
    confirmed: Optional[bool] = None

    def __post_init__(self) -> None:
        if self.sort_key is not None and self.sort_key not in SortKey.__members__:
            raise ValueError(f"There is no known sort {self.sort_key}")


# utility for GetTransactionsResponse
class TransactionRecordMetadata:
    content: dict[str, Any]
    coin_id: bytes32
    spent: bool

    def __init__(self, content: dict[str, Any], coin_id: bytes32, spent: bool) -> None:
        self.content = content
        self.coin_id = coin_id
        self.spent = spent

    def __eq__(self, other: Any) -> bool:
        if (
            isinstance(other, TransactionRecordMetadata)
            and other.content == self.content
            and other.coin_id == self.coin_id
            and other.spent == self.spent
        ):
            return True
        else:
            return False

    def __bytes__(self) -> bytes:
        raise NotImplementedError("Should not be serializing this object as bytes, it's only for RPC")

    @classmethod
    def parse(cls, f: BinaryIO) -> TransactionRecordMetadata:
        raise NotImplementedError("Should not be deserializing this object from a stream, it's only for RPC")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            **self.content,
            "coin_id": "0x" + self.coin_id.hex(),
            "spent": self.spent,
        }

    @classmethod
    def from_json_dict(cls, json_dict: dict[str, Any]) -> TransactionRecordMetadata:
        return TransactionRecordMetadata(
            coin_id=bytes32.from_hexstr(json_dict["coin_id"]),
            spent=json_dict["spent"],
            content={k: v for k, v in json_dict.items() if k not in ("coin_id", "spent")},
        )


# utility for GetTransactionsResponse
@streamable
@dataclass(frozen=True)
class UserFriendlyTransactionRecordWithMetadata(UserFriendlyTransactionRecord):
    metadata: Optional[TransactionRecordMetadata] = None


@streamable
@dataclass(frozen=True)
class GetTransactionsResponse(Streamable):
    transactions: list[UserFriendlyTransactionRecordWithMetadata]
    wallet_id: uint32


@streamable
@dataclass(frozen=True)
class GetTransactionCount(Streamable):
    wallet_id: uint32
    type_filter: Optional[TransactionTypeFilter] = None
    confirmed: Optional[bool] = None


@streamable
@dataclass(frozen=True)
class GetTransactionCountResponse(Streamable):
    count: uint16
    wallet_id: uint32


@streamable
@dataclass(frozen=True)
class GetNextAddress(Streamable):
    wallet_id: uint32
    new_address: bool = True


@streamable
@dataclass(frozen=True)
class GetNextAddressResponse(Streamable):
    wallet_id: uint32
    address: str


@streamable
@dataclass(frozen=True)
class GetNotifications(Streamable):
    ids: Optional[list[bytes32]] = None
    start: Optional[uint32] = None
    end: Optional[uint32] = None


@streamable
@dataclass(frozen=True)
class GetNotificationsResponse(Streamable):
    notifications: list[Notification]


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
    memos: list[bytes]


@streamable
@dataclass(frozen=True)
class GetTransactionMemoResponse(Streamable):
    transaction_id: bytes32
    coins_with_memos: list[CoinIDWithMemos]

    # TODO: deprecate the kinda silly format of this RPC and delete these functions
    def to_json_dict(self) -> dict[str, Any]:
        return {
            self.transaction_id.hex(): {
                cwm.coin_id.hex(): [memo.hex() for memo in cwm.memos] for cwm in self.coins_with_memos
            }
        }

    @classmethod
    def from_json_dict(cls, json_dict: dict[str, Any]) -> GetTransactionMemoResponse:
        return cls(
            bytes32.from_hexstr(next(iter(json_dict.keys()))),
            [
                CoinIDWithMemos(bytes32.from_hexstr(coin_id), [bytes32.from_hexstr(memo) for memo in memos])
                for coin_id, memos in next(iter(json_dict.values())).items()
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
    cat_list: list[DefaultCAT]


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
    backup_dids: list[bytes32]


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
    nft_wallets: list[NFTWalletWithDID]


# utility for NFTSetDIDBulk
@streamable
@dataclass(frozen=True)
class NFTCoin(Streamable):
    nft_coin_id: str
    wallet_id: uint32


@streamable
@dataclass(frozen=True)
class GatherSigningInfo(Streamable):
    spends: list[Spend]


@streamable
@dataclass(frozen=True)
class GatherSigningInfoResponse(Streamable):
    signing_instructions: SigningInstructions


@streamable
@dataclass(frozen=True)
class ApplySignatures(Streamable):
    spends: list[Spend]
    signing_responses: list[SigningResponse]


@streamable
@dataclass(frozen=True)
class ApplySignaturesResponse(Streamable):
    signed_transactions: list[SignedTransaction]


@streamable
@dataclass(frozen=True)
class SubmitTransactions(Streamable):
    signed_transactions: list[SignedTransaction]


@streamable
@dataclass(frozen=True)
class SubmitTransactionsResponse(Streamable):
    mempool_ids: list[bytes32]


@streamable
@dataclass(frozen=True)
class ExecuteSigningInstructions(Streamable):
    signing_instructions: SigningInstructions
    partial_allowed: bool = False


@streamable
@dataclass(frozen=True)
class ExecuteSigningInstructionsResponse(Streamable):
    signing_responses: list[SigningResponse]


# When inheriting from this class you must set any non default arguments with:
# field(default_factory=default_raise)
# (this is for < 3.10 compatibility)
@streamable
@kw_only_dataclass
class TransactionEndpointRequest(Streamable):
    fee: uint64 = uint64(0)
    push: Optional[bool] = None
    sign: Optional[bool] = None

    def to_json_dict(self, _avoid_ban: bool = False) -> dict[str, Any]:
        if not _avoid_ban:
            raise NotImplementedError(
                "to_json_dict is banned on TransactionEndpointRequest, please use .json_serialize_for_transport"
            )
        else:
            return super().to_json_dict()

    def json_serialize_for_transport(
        self, tx_config: TXConfig, extra_conditions: tuple[Condition, ...], timelock_info: ConditionValidTimes
    ) -> dict[str, Any]:
        return {
            **tx_config.to_json_dict(),
            **timelock_info.to_json_dict(),
            "extra_conditions": [condition.to_json_dict() for condition in extra_conditions],
            **self.to_json_dict(_avoid_ban=True),
        }


@streamable
@dataclass(frozen=True)
class TransactionEndpointResponse(Streamable):
    unsigned_transactions: list[UnsignedTransaction]
    transactions: list[TransactionRecord]


@streamable
@dataclass(frozen=True)
class PushTransactions(TransactionEndpointRequest):
    transactions: list[TransactionRecord] = field(default_factory=default_raise)
    push: Optional[bool] = True

    # We allow for flexibility in transaction parsing here so we need to override
    @classmethod
    def from_json_dict(cls, json_dict: dict[str, Any]) -> PushTransactions:
        transactions: list[TransactionRecord] = []
        for transaction_hexstr_or_json in json_dict["transactions"]:
            if isinstance(transaction_hexstr_or_json, str):
                tx = TransactionRecord.from_bytes(hexstr_to_bytes(transaction_hexstr_or_json))
            else:
                try:
                    tx = TransactionRecord.from_json_dict_convenience(transaction_hexstr_or_json)
                except AttributeError:
                    tx = TransactionRecord.from_json_dict(transaction_hexstr_or_json)
            transactions.append(tx)

        json_dict["transactions"] = [tx.to_json_dict() for tx in transactions]
        return super().from_json_dict(json_dict)


@streamable
@dataclass(frozen=True)
class PushTransactionsResponse(TransactionEndpointResponse):
    pass


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
    number_of_coins: uint16 = uint16(500)
    largest_first: bool = False
    target_coin_ids: list[bytes32] = field(default_factory=list)
    target_coin_amount: Optional[uint64] = None
    coin_num_limit: uint16 = uint16(500)


@streamable
@dataclass(frozen=True)
class CombineCoinsResponse(TransactionEndpointResponse):
    pass


@streamable
@kw_only_dataclass
class NFTSetDIDBulk(TransactionEndpointRequest):
    nft_coin_list: list[NFTCoin] = field(default_factory=default_raise)
    did_id: Optional[str] = None


@streamable
@dataclass(frozen=True)
class NFTSetDIDBulkResponse(TransactionEndpointResponse):
    wallet_id: list[uint32]
    tx_num: uint16
    spend_bundle: WalletSpendBundle


@streamable
@kw_only_dataclass
class NFTTransferBulk(TransactionEndpointRequest):
    nft_coin_list: list[NFTCoin] = field(default_factory=default_raise)
    target_address: str = field(default_factory=default_raise)


@streamable
@dataclass(frozen=True)
class NFTTransferBulkResponse(TransactionEndpointResponse):
    wallet_id: list[uint32]
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
    signed_txs: list[TransactionRecord]
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
    def from_json_dict(cls: type[_T_OfferEndpointResponse], json_dict: dict[str, Any]) -> _T_OfferEndpointResponse:
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
    nft_id_list: list[str]


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
    txs: list[TransactionRecord]


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
