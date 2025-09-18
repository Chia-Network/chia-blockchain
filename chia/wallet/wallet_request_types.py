from __future__ import annotations

import sys
from dataclasses import dataclass, field, fields
from enum import Enum
from functools import cached_property
from typing import Any, BinaryIO, Optional, TypeVar, Union, final

from chia_rs import Coin, G1Element, G2Element, PrivateKey
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint16, uint32, uint64
from typing_extensions import Self, dataclass_transform

from chia.data_layer.data_layer_wallet import DataLayerSummary, Mirror
from chia.data_layer.singleton_record import SingletonRecord
from chia.pools.pool_wallet_info import NewPoolWalletInitialTargetState, PoolWalletInfo
from chia.types.blockchain_format.coin import coin_as_list
from chia.types.blockchain_format.program import Program
from chia.types.coin_record import CoinRecord
from chia.util.byte_types import hexstr_to_bytes
from chia.util.hash import std_hash
from chia.util.streamable import Streamable, streamable, streamable_enum
from chia.wallet.conditions import (
    AssertCoinAnnouncement,
    AssertPuzzleAnnouncement,
    Condition,
    ConditionValidTimes,
    conditions_to_json_dicts,
)
from chia.wallet.nft_wallet.nft_info import NFTInfo
from chia.wallet.notification_store import Notification
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.signer_protocol import (
    SignedTransaction,
    SigningInstructions,
    SigningResponse,
    Spend,
    UnsignedTransaction,
)
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.offer import Offer, OfferSummary
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.transaction_sorting import SortKey
from chia.wallet.util.clvm_streamable import json_deserialize_with_clvm_streamable
from chia.wallet.util.puzzle_decorator_type import PuzzleDecoratorType
from chia.wallet.util.query_filter import TransactionTypeFilter
from chia.wallet.util.tx_config import CoinSelectionConfig, CoinSelectionConfigLoader, TXConfig
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.vc_wallet.vc_store import VCProofs, VCRecord
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_node import Balance
from chia.wallet.wallet_spend_bundle import WalletSpendBundle


@dataclass_transform(frozen_default=True, kw_only_default=True)
def kw_only_dataclass(cls: type[Any]) -> type[Any]:
    if sys.version_info >= (3, 10):
        return dataclass(frozen=True, kw_only=True)(cls)
    else:
        return dataclass(frozen=True)(cls)  # pragma: no cover


def default_raise() -> Any:  # pragma: no cover
    raise RuntimeError("This should be impossible to hit and is just for < 3.10 compatibility")


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
    wallet_balances: dict[uint32, BalanceResponse]


@streamable
@dataclass(frozen=True)
class GetTransaction(Streamable):
    transaction_id: bytes32


@streamable
@dataclass(frozen=True)
class GetTransactionResponse(Streamable):
    transaction: TransactionRecord
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
        if self.sort_key is not None and not hasattr(SortKey, self.sort_key):
            raise ValueError(f"There is no known sort {self.sort_key}")


# utility for GetTransactionsResponse
# this class cannot be a dataclass because if it is, streamable will assume it knows how to serialize it
# TODO: We should put some thought into deprecating this and separating the metadata more reasonably
class TransactionRecordMetadata:
    content: dict[str, Any]
    coin_id: bytes32
    spent: bool

    def __init__(self, content: dict[str, Any], coin_id: bytes32, spent: bool) -> None:
        self.content = content
        self.coin_id = coin_id
        self.spent = spent

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
            content={k: v for k, v in json_dict.items() if k not in {"coin_id", "spent"}},
        )


# utility for GetTransactionsResponse
@streamable
@dataclass(frozen=True)
class TransactionRecordWithMetadata(TransactionRecord):
    metadata: Optional[TransactionRecordMetadata] = None


@streamable
@dataclass(frozen=True)
class GetTransactionsResponse(Streamable):
    transactions: list[TransactionRecordWithMetadata]
    wallet_id: uint32


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
class DeleteNotifications(Streamable):
    ids: Optional[list[bytes32]] = None


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
class SignMessageByAddress(Streamable):
    address: str
    message: str
    is_hex: bool = False
    safe_mode: bool = True


@streamable
@dataclass(frozen=True)
class SignMessageByAddressResponse(Streamable):
    pubkey: G1Element
    signature: G2Element
    signing_mode: str


@streamable
@dataclass(frozen=True)
class SignMessageByID(Streamable):
    id: str
    message: str
    is_hex: bool = False
    safe_mode: bool = True


@streamable
@dataclass(frozen=True)
class SignMessageByIDResponse(Streamable):
    pubkey: G1Element
    signature: G2Element
    latest_coin_id: bytes32
    signing_mode: str


@streamable
@dataclass(frozen=True)
class GetTransactionMemo(Streamable):
    transaction_id: bytes32


@streamable
@dataclass(frozen=True)
class GetTransactionMemoResponse(Streamable):
    transaction_memos: dict[bytes32, dict[bytes32, list[bytes]]]

    @property
    def memo_dict(self) -> dict[bytes32, list[bytes]]:
        return next(iter(self.transaction_memos.values()))

    # TODO: deprecate the kinda silly format of this RPC and delete these functions
    def to_json_dict(self) -> dict[str, Any]:
        # This is semantically guaranteed but mypy can't know that
        return super().to_json_dict()["transaction_memos"]  # type: ignore[no-any-return]

    @classmethod
    def from_json_dict(cls, json_dict: dict[str, Any]) -> GetTransactionMemoResponse:
        return super().from_json_dict(
            # We have to filter out the "success" key here
            # because it doesn't match our `transaction_memos` hint
            #
            # We do this by only allowing the keys with "0x"
            # which we can assume exist because we serialize all responses
            {"transaction_memos": {key: value for key, value in json_dict.items() if key.startswith("0x")}}
        )


@streamable
@dataclass(frozen=True)
class GetTransactionCount(Streamable):
    wallet_id: uint32
    confirmed: Optional[bool] = None
    type_filter: Optional[TransactionTypeFilter] = None


@streamable
@dataclass(frozen=True)
class GetTransactionCountResponse(Streamable):
    wallet_id: uint32
    count: uint16


@streamable
@dataclass(frozen=True)
class GetNextAddress(Streamable):
    wallet_id: uint32
    new_address: bool = False
    save_derivations: bool = True


@streamable
@dataclass(frozen=True)
class GetNextAddressResponse(Streamable):
    wallet_id: uint32
    address: str


@streamable
@dataclass(frozen=True)
class DeleteUnconfirmedTransactions(Streamable):
    wallet_id: uint32


@streamable
@dataclass(frozen=True)
class SelectCoins(CoinSelectionConfigLoader):
    wallet_id: uint32 = field(default_factory=default_raise)
    amount: uint64 = field(default_factory=default_raise)
    exclude_coins: Optional[list[Coin]] = None  # for backwards compatibility

    def __post_init__(self) -> None:
        if self.excluded_coin_ids is not None and self.exclude_coins is not None:
            raise ValueError(
                "Cannot specify both excluded_coin_ids/excluded_coins and exclude_coins (the latter is deprecated)"
            )
        super().__post_init__()

    @classmethod
    def from_coin_selection_config(
        cls, wallet_id: uint32, amount: uint64, coin_selection_config: CoinSelectionConfig
    ) -> Self:
        return cls(
            wallet_id=wallet_id,
            amount=amount,
            min_coin_amount=coin_selection_config.min_coin_amount,
            max_coin_amount=coin_selection_config.max_coin_amount,
            excluded_coin_amounts=coin_selection_config.excluded_coin_amounts,
            excluded_coin_ids=coin_selection_config.excluded_coin_ids,
        )


@streamable
@dataclass(frozen=True)
class SelectCoinsResponse(Streamable):
    coins: list[Coin]


@streamable
@dataclass(frozen=True)
class GetSpendableCoins(CoinSelectionConfigLoader):
    wallet_id: uint32 = field(default_factory=default_raise)

    @classmethod
    def from_coin_selection_config(cls, wallet_id: uint32, coin_selection_config: CoinSelectionConfig) -> Self:
        return cls(
            wallet_id=wallet_id,
            min_coin_amount=coin_selection_config.min_coin_amount,
            max_coin_amount=coin_selection_config.max_coin_amount,
            excluded_coin_amounts=coin_selection_config.excluded_coin_amounts,
            excluded_coin_ids=coin_selection_config.excluded_coin_ids,
        )


@streamable
@dataclass(frozen=True)
class GetSpendableCoinsResponse(Streamable):
    confirmed_records: list[CoinRecord]
    unconfirmed_removals: list[CoinRecord]
    unconfirmed_additions: list[Coin]


@streamable
@dataclass(frozen=True)
class GetCoinRecordsByNames(Streamable):
    names: list[bytes32]
    start_height: Optional[uint32] = None
    end_height: Optional[uint32] = None
    include_spent_coins: bool = True


@streamable
@dataclass(frozen=True)
class GetCoinRecordsByNamesResponse(Streamable):
    coin_records: list[CoinRecord]


@streamable
@dataclass(frozen=True)
class GetCurrentDerivationIndexResponse(Streamable):
    index: Optional[uint32]


@streamable
@dataclass(frozen=True)
class ExtendDerivationIndex(Streamable):
    index: uint32


@streamable
@dataclass(frozen=True)
class ExtendDerivationIndexResponse(Streamable):
    index: Optional[uint32]


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
class CATSetName(Streamable):
    wallet_id: uint32
    name: str


@streamable
@dataclass(frozen=True)
class CATSetNameResponse(Streamable):
    wallet_id: uint32


@streamable
@dataclass(frozen=True)
class CATGetName(Streamable):
    wallet_id: uint32


@streamable
@dataclass(frozen=True)
class CATGetNameResponse(Streamable):
    wallet_id: uint32
    name: str


@streamable
@dataclass(frozen=True)
class StrayCAT(Streamable):
    asset_id: bytes32
    name: str
    first_seen_height: uint32
    sender_puzzle_hash: bytes32


@streamable
@dataclass(frozen=True)
class GetStrayCATsResponse(Streamable):
    stray_cats: list[StrayCAT]


@streamable
@dataclass(frozen=True)
class CATGetAssetID(Streamable):
    wallet_id: uint32


@streamable
@dataclass(frozen=True)
class CATGetAssetIDResponse(Streamable):
    wallet_id: uint32
    asset_id: bytes32


@streamable
@dataclass(frozen=True)
class CATAssetIDToName(Streamable):
    asset_id: bytes32


@streamable
@dataclass(frozen=True)
class CATAssetIDToNameResponse(Streamable):
    wallet_id: Optional[uint32]
    name: Optional[str]


@streamable
@dataclass(frozen=True)
class GetOfferSummary(Streamable):
    offer: str
    advanced: bool = False

    @cached_property
    def parsed_offer(self) -> Offer:
        return Offer.from_bech32(self.offer)


@streamable
@dataclass(frozen=True)
class GetOfferSummaryResponse(Streamable):
    id: bytes32
    summary: Optional[OfferSummary] = None
    data_layer_summary: Optional[DataLayerSummary] = None

    def __post_init__(self) -> None:
        if self.summary is not None and self.data_layer_summary is not None:
            raise ValueError("Cannot have both summary and data_layer_summary")
        elif self.summary is None and self.data_layer_summary is None:
            raise ValueError("Must have either summary or data_layer_summary")
        super().__post_init__()

    def to_json_dict(self) -> dict[str, Any]:
        serialized = super().to_json_dict()
        if self.data_layer_summary is not None:
            serialized["summary"] = serialized["data_layer_summary"]
        del serialized["data_layer_summary"]
        return serialized

    @classmethod
    def from_json_dict(cls, json_dict: dict[str, Any]) -> Self:
        if isinstance(json_dict["summary"]["offered"], dict):
            summary: Union[OfferSummary, DataLayerSummary] = OfferSummary.from_json_dict(json_dict["summary"])
        else:
            summary = DataLayerSummary.from_json_dict(json_dict["summary"])
        return cls(
            id=bytes32.from_hexstr(json_dict["id"]),
            summary=summary if isinstance(summary, OfferSummary) else None,
            data_layer_summary=summary if isinstance(summary, DataLayerSummary) else None,
        )


@streamable
@dataclass(frozen=True)
class CheckOfferValidity(Streamable):
    offer: str


@streamable
@dataclass(frozen=True)
class CheckOfferValidityResponse(Streamable):
    valid: bool
    id: bytes32


@streamable
@dataclass(frozen=True)
class DIDSetWalletName(Streamable):
    wallet_id: uint32
    name: str


@streamable
@dataclass(frozen=True)
class DIDSetWalletNameResponse(Streamable):
    wallet_id: uint32


@streamable
@dataclass(frozen=True)
class DIDGetWalletName(Streamable):
    wallet_id: uint32


@streamable
@dataclass(frozen=True)
class DIDGetWalletNameResponse(Streamable):
    wallet_id: uint32
    name: str


@streamable
@dataclass(frozen=True)
class DIDGetInfo(Streamable):
    coin_id: str
    latest: bool = True


@streamable
@dataclass(frozen=True)
class DIDGetInfoResponse(Streamable):
    did_id: str
    latest_coin: bytes32
    p2_address: str
    public_key: bytes
    recovery_list_hash: Optional[bytes32]
    num_verification: uint16
    metadata: dict[str, str]
    launcher_id: bytes32
    full_puzzle: Program
    solution: Program
    hints: list[bytes]


@streamable
@dataclass(frozen=True)
class DIDFindLostDID(Streamable):
    coin_id: str
    recovery_list_hash: Optional[bytes32] = None
    num_verification: Optional[uint16] = None
    metadata: Optional[dict[str, str]] = None


@streamable
@dataclass(frozen=True)
class DIDFindLostDIDResponse(Streamable):
    latest_coin_id: bytes32


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
class DIDCreateBackupFile(Streamable):
    wallet_id: uint32


@streamable
@dataclass(frozen=True)
class DIDCreateBackupFileResponse(Streamable):
    wallet_id: uint32
    backup_data: str


@streamable
@dataclass(frozen=True)
class DIDGetDID(Streamable):
    wallet_id: uint32


@streamable
@dataclass(frozen=True)
class DIDGetDIDResponse(Streamable):
    wallet_id: uint32
    my_did: str
    coin_id: Optional[bytes32] = None


@streamable
@dataclass(frozen=True)
class DIDGetMetadata(Streamable):
    wallet_id: uint32


@streamable
@dataclass(frozen=True)
class DIDGetMetadataResponse(Streamable):
    wallet_id: uint32
    metadata: dict[str, str]


@streamable
@dataclass(frozen=True)
class NFTCountNFTs(Streamable):
    wallet_id: Optional[uint32] = None


@streamable
@dataclass(frozen=True)
class NFTCountNFTsResponse(Streamable):
    wallet_id: Optional[uint32]
    count: uint64


@streamable
@dataclass(frozen=True)
class NFTGetNFTs(Streamable):
    wallet_id: Optional[uint32] = None
    start_index: uint32 = uint32(0)
    num: uint32 = uint32(50)


@streamable
@dataclass(frozen=True)
class NFTGetNFTsResponse(Streamable):
    wallet_id: Optional[uint32]
    nft_list: list[NFTInfo]


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
class NFTGetWalletDID(Streamable):
    wallet_id: uint32


@streamable
@dataclass(frozen=True)
class NFTGetWalletDIDResponse(Streamable):
    did_id: Optional[str]


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


@streamable
@dataclass(frozen=True)
class NFTGetInfo(Streamable):
    coin_id: str
    latest: bool = True


@streamable
@dataclass(frozen=True)
class NFTGetInfoResponse(Streamable):
    nft_info: NFTInfo


# utility for NFTCalculateRoyalties
@streamable
@dataclass(frozen=True)
class RoyaltyAsset(Streamable):
    asset: str
    royalty_address: str
    royalty_percentage: uint16


# utility for NFTCalculateRoyalties
@streamable
@dataclass(frozen=True)
class FungibleAsset(Streamable):
    asset: Optional[str]
    amount: uint64


@streamable
@dataclass(frozen=True)
class NFTCalculateRoyalties(Streamable):
    royalty_assets: list[RoyaltyAsset] = field(default_factory=list)
    fungible_assets: list[FungibleAsset] = field(default_factory=list)

    def __post_init__(self) -> None:
        if len(set(a.asset for a in self.royalty_assets)) != len(self.royalty_assets):
            raise ValueError("Multiple royalty assets with same name specified")
        if len(set(a.asset for a in self.fungible_assets)) != len(self.fungible_assets):
            raise ValueError("Multiple fungible assets with same name specified")


# utility for NFTCalculateRoyaltiesResponse
@streamable
@dataclass(frozen=True)
class RoyaltySummary(Streamable):
    royalty_asset: str
    fungible_asset: Optional[str]
    royalty_address: str
    royalty_amount: uint64


@streamable
@dataclass(frozen=True)
class NFTCalculateRoyaltiesResponse(Streamable):
    nft_info: list[RoyaltySummary]

    # old response is a dict with arbitrary keys so we must override serialization for backwards compatibility
    def to_json_dict(self) -> dict[str, Any]:
        summary_dict: dict[str, Any] = {}
        for info in self.nft_info:
            summary_dict.setdefault(info.royalty_asset, [])
            summary_dict[info.royalty_asset].append(
                {
                    "asset": info.fungible_asset,
                    "address": info.royalty_address,
                    "amount": info.royalty_amount,
                }
            )

        return summary_dict

    @classmethod
    def from_json_dict(cls, json_dict: dict[str, Any]) -> NFTCalculateRoyaltiesResponse:
        # There's some awkwardness here because the canonical format of this response
        # returns all of the asset information on the same level as the "success"
        # key that gets automatically returned by the RPC
        #
        # This is an unfortunate design choice, but one we must preserve for
        # backwards compatibility. This means the code below has some logic it
        # probably shouldn't have ignoring "assets" named "success".
        return cls(
            [
                RoyaltySummary(
                    royalty_asset,
                    summary["asset"],
                    summary["address"],
                    uint64(summary["amount"]),
                )
                for royalty_asset, summaries in json_dict.items()
                if royalty_asset != "success"
                for summary in summaries
            ]
        )


# utility for NFTSetDIDBulk
@streamable
@dataclass(frozen=True)
class NFTCoin(Streamable):
    nft_coin_id: str
    wallet_id: uint32


@streamable
@dataclass(frozen=True)
class PWStatus(Streamable):
    wallet_id: uint32


@streamable
@dataclass(frozen=True)
class PWStatusResponse(Streamable):
    state: PoolWalletInfo
    unconfirmed_transactions: list[TransactionRecord]


@streamable
@dataclass(frozen=True)
class DLTrackNew(Streamable):
    launcher_id: bytes32


@streamable
@dataclass(frozen=True)
class DLStopTracking(Streamable):
    launcher_id: bytes32


@streamable
@dataclass(frozen=True)
class DLLatestSingleton(Streamable):
    launcher_id: bytes32
    only_confirmed: bool = False


@streamable
@dataclass(frozen=True)
class DLLatestSingletonResponse(Streamable):
    singleton: Optional[SingletonRecord]


@streamable
@dataclass(frozen=True)
class DLSingletonsByRoot(Streamable):
    launcher_id: bytes32
    root: bytes32


@streamable
@dataclass(frozen=True)
class DLSingletonsByRootResponse(Streamable):
    singletons: list[SingletonRecord]


@streamable
@dataclass(frozen=True)
class DLHistory(Streamable):
    launcher_id: bytes32
    min_generation: Optional[uint32] = None
    max_generation: Optional[uint32] = None
    num_results: Optional[uint32] = None


@streamable
@dataclass(frozen=True)
class DLHistoryResponse(Streamable):
    history: list[SingletonRecord]
    count: uint32


@streamable
@dataclass(frozen=True)
class DLOwnedSingletonsResponse(Streamable):
    singletons: list[SingletonRecord]
    count: uint32


@streamable
@dataclass(frozen=True)
class DLGetMirrors(Streamable):
    launcher_id: bytes32


@streamable
@dataclass(frozen=True)
class DLGetMirrorsResponse(Streamable):
    mirrors: list[Mirror]


@streamable
@dataclass(frozen=True)
class VCGet(Streamable):
    vc_id: bytes32


@streamable
@dataclass(frozen=True)
class VCGetResponse(Streamable):
    vc_record: Optional[VCRecord]


@streamable
@dataclass(frozen=True)
class VCGetList(Streamable):
    start: uint32 = uint32(0)
    end: uint32 = uint32(50)


# utility for VC endpoints
@streamable
@dataclass(frozen=True)
class VCProofsRPC(Streamable):
    key_value_pairs: list[tuple[str, str]]

    def to_vc_proofs(self) -> VCProofs:
        return VCProofs({key: value for key, value in self.key_value_pairs})

    @classmethod
    def from_vc_proofs(cls, vc_proofs: VCProofs) -> Self:
        return cls([(key, value) for key, value in vc_proofs.key_value_pairs.items()])


# utility for VCGetListResponse
@streamable
@dataclass(frozen=True)
class VCProofWithHash(Streamable):
    hash: bytes32
    proof: Optional[VCProofsRPC]


# utility for VCGetListResponse
@final
@streamable
@dataclass(frozen=True)
class VCRecordWithCoinID(VCRecord):
    coin_id: bytes32

    @classmethod
    def from_vc_record(cls, vc_record: VCRecord) -> VCRecordWithCoinID:
        return cls(coin_id=vc_record.vc.coin.name(), **vc_record.__dict__)


@streamable
@dataclass(frozen=True)
class VCGetListResponse(Streamable):
    vc_records: list[VCRecordWithCoinID]
    proofs: list[VCProofWithHash]

    @property
    def proof_dict(self) -> dict[bytes32, Optional[dict[str, str]]]:
        return {
            pwh.hash: None if pwh.proof is None else {key: value for key, value in pwh.proof.key_value_pairs}
            for pwh in self.proofs
        }

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "vc_records": [vc_record.to_json_dict() for vc_record in self.vc_records],
            "proofs": {proof_hash.hex(): proof_data for proof_hash, proof_data in self.proof_dict.items()},
        }

    @classmethod
    def from_json_dict(cls, json_dict: dict[str, Any]) -> VCGetListResponse:
        return cls(
            [VCRecordWithCoinID.from_json_dict(vc_record) for vc_record in json_dict["vc_records"]],
            [
                VCProofWithHash(
                    bytes32.from_hexstr(proof_hash),
                    None if potential_proofs is None else VCProofsRPC.from_vc_proofs(VCProofs(potential_proofs)),
                )
                for proof_hash, potential_proofs in json_dict["proofs"].items()
            ],
        )


@streamable
@dataclass(frozen=True)
class VCAddProofs(VCProofsRPC):
    def to_json_dict(self) -> dict[str, Any]:
        return {"proofs": self.to_vc_proofs().key_value_pairs}

    @classmethod
    def from_json_dict(cls, json_dict: dict[str, Any]) -> Self:
        return cls([(key, value) for key, value in json_dict["proofs"].items()])


@streamable
@dataclass(frozen=True)
class VCGetProofsForRoot(Streamable):
    root: bytes32


@streamable
@dataclass(frozen=True)
class VCGetProofsForRootResponse(VCAddProofs):
    pass


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
            "extra_conditions": conditions_to_json_dicts(extra_conditions),
            **self.to_json_dict(_avoid_ban=True),
        }


@streamable
@dataclass(frozen=True)
class TransactionEndpointResponse(Streamable):
    unsigned_transactions: list[UnsignedTransaction]
    transactions: list[TransactionRecord]


# utility for SendTransaction
@streamable
@dataclass(frozen=True)
class ClawbackPuzzleDecoratorOverride(Streamable):
    decorator: str
    clawback_timelock: uint64

    def __post_init__(self) -> None:
        if self.decorator != PuzzleDecoratorType.CLAWBACK.name:
            raise ValueError("Invalid clawback puzzle decorator override specified")
        super().__post_init__()


@streamable
@dataclass(frozen=True)
class SendTransaction(TransactionEndpointRequest):
    wallet_id: uint32 = field(default_factory=default_raise)
    amount: uint64 = field(default_factory=default_raise)
    address: str = field(default_factory=default_raise)
    memos: list[str] = field(default_factory=list)
    # Technically this value was meant to support many types here
    # However, only one is supported right now and there are no plans to extend
    # So, as a slight hack, we'll specify that only Clawback is supported
    puzzle_decorator: Optional[list[ClawbackPuzzleDecoratorOverride]] = None


@streamable
@dataclass(frozen=True)
class SendTransactionResponse(TransactionEndpointResponse):
    transaction: TransactionRecord
    transaction_id: bytes32


@streamable
@dataclass(frozen=True)
class SpendClawbackCoins(TransactionEndpointRequest):
    coin_ids: list[bytes32] = field(default_factory=default_raise)
    batch_size: Optional[uint16] = None
    force: bool = False


@streamable
@dataclass(frozen=True)
class SpendClawbackCoinsResponse(TransactionEndpointResponse):
    transaction_ids: list[bytes32]


@streamable
@dataclass(frozen=True)
class SendNotification(TransactionEndpointRequest):
    target: bytes32 = field(default_factory=default_raise)
    message: bytes = field(default_factory=default_raise)
    amount: uint64 = uint64(0)


@streamable
@dataclass(frozen=True)
class SendNotificationResponse(TransactionEndpointResponse):
    tx: TransactionRecord


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


# utility for CATSpend/CreateSignedTransaction
# unfortunate that we can't use CreateCoin but the memos are taken as strings not bytes
@streamable
@dataclass(frozen=True)
class Addition(Streamable):
    amount: uint64
    puzzle_hash: bytes32
    memos: Optional[list[str]] = None


@streamable
@kw_only_dataclass
class CATSpend(TransactionEndpointRequest):
    wallet_id: uint32 = field(default_factory=default_raise)
    additions: Optional[list[Addition]] = None
    amount: Optional[uint64] = None
    inner_address: Optional[str] = None
    memos: Optional[list[str]] = None
    coins: Optional[list[Coin]] = None
    extra_delta: Optional[str] = None  # str to support negative ints :(
    tail_reveal: Optional[bytes] = None
    tail_solution: Optional[bytes] = None

    def __post_init__(self) -> None:
        if (
            self.additions is not None
            and (self.amount is not None or self.inner_address is not None or self.memos is not None)
        ) or (self.additions is None and self.amount is None and self.inner_address is None and self.memos is None):
            raise ValueError('Must specify "additions" or "amount"+"inner_address"+"memos", but not both.')
        elif self.additions is None and None in {self.amount, self.inner_address}:
            raise ValueError('Must specify "amount" and "inner_address" together.')
        super().__post_init__()

    @property
    def cat_discrepancy(self) -> Optional[tuple[int, Program, Program]]:
        if self.extra_delta is None and self.tail_reveal is None and self.tail_solution is None:
            return None
        elif None in {self.extra_delta, self.tail_reveal, self.tail_solution}:
            raise ValueError('Must specify "extra_delta", "tail_reveal" and "tail_solution" together.')
        else:
            # Curious that mypy doesn't see the elif and know that none of these are None
            return (
                int(self.extra_delta),  # type: ignore[arg-type]
                Program.from_bytes(self.tail_reveal),  # type: ignore[arg-type]
                Program.from_bytes(self.tail_solution),  # type: ignore[arg-type]
            )


@streamable
@dataclass(frozen=True)
class CATSpendResponse(TransactionEndpointResponse):
    transaction: TransactionRecord
    transaction_id: bytes32


@streamable
@kw_only_dataclass
class DIDMessageSpend(TransactionEndpointRequest):
    wallet_id: uint32 = field(default_factory=default_raise)
    coin_announcements: list[bytes] = field(default_factory=list)
    puzzle_announcements: list[bytes] = field(default_factory=list)


@streamable
@dataclass(frozen=True)
class DIDMessageSpendResponse(TransactionEndpointResponse):
    spend_bundle: WalletSpendBundle


@streamable
@kw_only_dataclass
class DIDUpdateMetadata(TransactionEndpointRequest):
    wallet_id: uint32 = field(default_factory=default_raise)
    metadata: dict[str, str] = field(default_factory=dict)


@streamable
@dataclass(frozen=True)
class DIDUpdateMetadataResponse(TransactionEndpointResponse):
    spend_bundle: WalletSpendBundle
    wallet_id: uint32


@streamable
@kw_only_dataclass
class DIDTransferDID(TransactionEndpointRequest):
    wallet_id: uint32 = field(default_factory=default_raise)
    inner_address: str = field(default_factory=default_raise)
    with_recovery_info: bool = True

    def __post_init__(self) -> None:
        if self.with_recovery_info is False:
            raise ValueError("Recovery related options are no longer supported. `with_recovery` must always be true.")
        return super().__post_init__()


@streamable
@dataclass(frozen=True)
class DIDTransferDIDResponse(TransactionEndpointResponse):
    transaction: TransactionRecord
    transaction_id: bytes32


@streamable
@kw_only_dataclass
class NFTMintNFTRequest(TransactionEndpointRequest):
    wallet_id: uint32 = field(default_factory=default_raise)
    royalty_address: Optional[str] = field(default_factory=default_raise)
    target_address: Optional[str] = field(default_factory=default_raise)
    uris: list[str] = field(default_factory=default_raise)
    hash: bytes32 = field(default_factory=default_raise)
    royalty_amount: uint16 = uint16(0)
    meta_uris: list[str] = field(default_factory=list)
    license_uris: list[str] = field(default_factory=list)
    edition_number: uint64 = uint64(1)
    edition_total: uint64 = uint64(1)
    meta_hash: Optional[bytes32] = None
    license_hash: Optional[bytes32] = None
    did_id: Optional[str] = None


@streamable
@dataclass(frozen=True)
class NFTMintNFTResponse(TransactionEndpointResponse):
    wallet_id: uint32
    spend_bundle: WalletSpendBundle
    nft_id: str


@streamable
@kw_only_dataclass
class NFTSetNFTDID(TransactionEndpointRequest):
    wallet_id: uint32 = field(default_factory=default_raise)
    nft_coin_id: bytes32 = field(default_factory=default_raise)
    did_id: Optional[str] = None


@streamable
@dataclass(frozen=True)
class NFTSetNFTDIDResponse(TransactionEndpointResponse):
    wallet_id: uint32
    spend_bundle: WalletSpendBundle


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


@streamable
@kw_only_dataclass
class CreateNewDL(TransactionEndpointRequest):
    root: bytes32 = field(default_factory=default_raise)


@streamable
@dataclass(frozen=True)
class CreateNewDLResponse(TransactionEndpointResponse):
    launcher_id: bytes32


@streamable
@kw_only_dataclass
class DLUpdateRoot(TransactionEndpointRequest):
    launcher_id: bytes32 = field(default_factory=default_raise)
    new_root: bytes32 = field(default_factory=default_raise)


@streamable
@dataclass(frozen=True)
class DLUpdateRootResponse(TransactionEndpointResponse):
    tx_record: TransactionRecord


# utilities for DLUpdateMultiple
@streamable
@dataclass(frozen=True)
class LauncherRootPair(Streamable):
    launcher_id: bytes32
    new_root: bytes32


@streamable
@dataclass(frozen=True)
class DLUpdateMultipleUpdates(Streamable):
    launcher_root_pairs: list[LauncherRootPair]

    def __post_init__(self) -> None:
        if len(set(pair.launcher_id for pair in self.launcher_root_pairs)) < len(self.launcher_root_pairs):
            raise ValueError("Multiple updates specified for a single launcher in `DLUpdateMultiple`")

    # TODO: deprecate the kinda silly format of this RPC and delete this function
    @classmethod
    def from_json_dict(cls, json_dict: dict[str, Any]) -> Self:
        return cls(
            [
                LauncherRootPair(
                    bytes32.from_hexstr(key),
                    bytes32.from_hexstr(value),
                )
                for key, value in json_dict.items()
            ]
        )


@streamable
@kw_only_dataclass
class DLUpdateMultiple(TransactionEndpointRequest):
    updates: DLUpdateMultipleUpdates = field(default_factory=default_raise)

    # TODO: deprecate the kinda silly format of this RPC and delete this function
    def to_json_dict(self, _avoid_ban: bool = False) -> dict[str, Any]:
        return {"updates": {pair.launcher_id.hex(): pair.new_root.hex() for pair in self.updates.launcher_root_pairs}}


@streamable
@dataclass(frozen=True)
class DLUpdateMultipleResponse(TransactionEndpointResponse):
    pass


@streamable
@kw_only_dataclass
class DLNewMirror(TransactionEndpointRequest):
    launcher_id: bytes32 = field(default_factory=default_raise)
    amount: uint64 = field(default_factory=default_raise)
    urls: list[str] = field(default_factory=default_raise)


@streamable
@dataclass(frozen=True)
class DLNewMirrorResponse(TransactionEndpointResponse):
    pass


@streamable
@kw_only_dataclass
class DLDeleteMirror(TransactionEndpointRequest):
    coin_id: bytes32 = field(default_factory=default_raise)


@streamable
@dataclass(frozen=True)
class DLDeleteMirrorResponse(TransactionEndpointResponse):
    pass


@streamable
@dataclass(frozen=True)
class NFTTransferNFT(TransactionEndpointRequest):
    wallet_id: uint32 = field(default_factory=default_raise)
    target_address: str = field(default_factory=default_raise)
    nft_coin_id: str = field(default_factory=default_raise)


@streamable
@dataclass(frozen=True)
class NFTTransferNFTResponse(TransactionEndpointResponse):
    wallet_id: uint32
    spend_bundle: WalletSpendBundle


@streamable
@dataclass(frozen=True)
class NFTAddURI(TransactionEndpointRequest):
    wallet_id: uint32 = field(default_factory=default_raise)
    uri: str = field(default_factory=default_raise)
    key: str = field(default_factory=default_raise)
    nft_coin_id: str = field(default_factory=default_raise)


@streamable
@dataclass(frozen=True)
class NFTAddURIResponse(TransactionEndpointResponse):
    wallet_id: uint32
    spend_bundle: WalletSpendBundle


# utility for NFTBulkMint
@streamable
@dataclass(frozen=True)
class NFTMintMetadata(Streamable):
    uris: list[str]
    hash: bytes32
    meta_uris: list[str] = field(default_factory=list)
    license_uris: list[str] = field(default_factory=list)
    edition_number: uint64 = uint64(1)
    edition_total: uint64 = uint64(1)
    meta_hash: Optional[bytes32] = None
    license_hash: Optional[bytes32] = None


@streamable
@dataclass(frozen=True)
class NFTMintBulk(TransactionEndpointRequest):
    wallet_id: uint32 = field(default_factory=default_raise)
    metadata_list: list[NFTMintMetadata] = field(default_factory=default_raise)
    royalty_address: Optional[str] = None
    royalty_percentage: Optional[uint16] = None
    target_list: list[str] = field(default_factory=list)
    mint_number_start: uint16 = uint16(1)
    mint_total: Optional[uint16] = None
    xch_coins: Optional[list[Coin]] = None
    xch_change_target: Optional[str] = None
    new_innerpuzhash: Optional[bytes32] = None
    new_p2_puzhash: Optional[bytes32] = None
    did_coin: Optional[Coin] = None
    did_lineage_parent: Optional[bytes32] = None
    mint_from_did: bool = False


@streamable
@dataclass(frozen=True)
class NFTMintBulkResponse(TransactionEndpointResponse):
    spend_bundle: WalletSpendBundle
    nft_id_list: list[str]


@streamable
@dataclass(frozen=True)
class PWJoinPool(TransactionEndpointRequest):
    wallet_id: uint32 = field(default_factory=default_raise)
    pool_url: str = field(default_factory=default_raise)
    target_puzzlehash: bytes32 = field(default_factory=default_raise)
    relative_lock_height: uint32 = field(default_factory=default_raise)


@streamable
@dataclass(frozen=True)
class PWJoinPoolResponse(TransactionEndpointResponse):
    total_fee: uint64
    transaction: TransactionRecord
    fee_transaction: Optional[TransactionRecord]


@streamable
@dataclass(frozen=True)
class PWSelfPool(TransactionEndpointRequest):
    wallet_id: uint32 = field(default_factory=default_raise)


@streamable
@dataclass(frozen=True)
class PWSelfPoolResponse(TransactionEndpointResponse):
    total_fee: uint64
    transaction: TransactionRecord
    fee_transaction: Optional[TransactionRecord]


@streamable
@dataclass(frozen=True)
class PWAbsorbRewards(TransactionEndpointRequest):
    wallet_id: uint32 = field(default_factory=default_raise)
    max_spends_in_tx: Optional[uint16] = None


@streamable
@dataclass(frozen=True)
class PWAbsorbRewardsResponse(TransactionEndpointResponse):
    state: PoolWalletInfo
    transaction: TransactionRecord
    fee_transaction: Optional[TransactionRecord]


@streamable
@dataclass(frozen=True)
class VCMint(TransactionEndpointRequest):
    did_id: str = field(default_factory=default_raise)
    target_address: Optional[str] = None


@streamable
@dataclass(frozen=True)
class VCMintResponse(TransactionEndpointResponse):
    vc_record: VCRecord


@streamable
@dataclass(frozen=True)
class VCSpend(TransactionEndpointRequest):
    vc_id: bytes32 = field(default_factory=default_raise)
    new_puzhash: Optional[bytes32] = None
    new_proof_hash: Optional[bytes32] = None
    provider_inner_puzhash: Optional[bytes32] = None


@streamable
@dataclass(frozen=True)
class VCSpendResponse(TransactionEndpointResponse):
    pass


@streamable
@dataclass(frozen=True)
class VCRevoke(TransactionEndpointRequest):
    vc_parent_id: bytes32 = field(default_factory=default_raise)


@streamable
@dataclass(frozen=True)
class VCRevokeResponse(TransactionEndpointResponse):
    pass


@streamable
@dataclass(frozen=True)
class CSTCoinAnnouncement(Streamable):
    coin_id: bytes32
    message: bytes


@streamable
@dataclass(frozen=True)
class CSTPuzzleAnnouncement(Streamable):
    puzzle_hash: bytes32
    message: bytes


@streamable
@dataclass(frozen=True)
class CreateSignedTransaction(TransactionEndpointRequest):
    additions: list[Addition] = field(default_factory=default_raise)
    wallet_id: Optional[uint32] = None
    coins: Optional[list[Coin]] = None
    morph_bytes: Optional[bytes] = None
    coin_announcements: list[CSTCoinAnnouncement] = field(default_factory=list)
    puzzle_announcements: list[CSTPuzzleAnnouncement] = field(default_factory=list)

    def __post_init__(self) -> None:
        if len(self.additions) < 1:
            raise ValueError("Must have at least one addition")
        super().__post_init__()

    @property
    def coin_set(self) -> Optional[set[Coin]]:
        if self.coins is None:
            return None
        else:
            return set(self.coins)

    @property
    def asserted_coin_announcements(self) -> tuple[AssertCoinAnnouncement, ...]:
        return tuple(
            AssertCoinAnnouncement(
                asserted_id=ca.coin_id,
                asserted_msg=(ca.message if self.morph_bytes is None else std_hash(self.morph_bytes + ca.message)),
            )
            for ca in self.coin_announcements
        )

    @property
    def asserted_puzzle_announcements(self) -> tuple[AssertPuzzleAnnouncement, ...]:
        return tuple(
            AssertPuzzleAnnouncement(
                asserted_ph=pa.puzzle_hash,
                asserted_msg=(pa.message if self.morph_bytes is None else std_hash(self.morph_bytes + pa.message)),
            )
            for pa in self.puzzle_announcements
        )


@streamable
@dataclass(frozen=True)
class CreateSignedTransactionsResponse(TransactionEndpointResponse):
    signed_txs: list[TransactionRecord]
    signed_tx: TransactionRecord


_T_SendTransactionMultiProxy = TypeVar("_T_SendTransactionMultiProxy", CATSpend, CreateSignedTransaction)


@streamable
@dataclass(frozen=True)
class SendTransactionMulti(TransactionEndpointRequest):
    # primarily for cat_spend
    wallet_id: uint32 = field(default_factory=default_raise)
    additions: Optional[list[Addition]] = None  # for both
    amount: Optional[uint64] = None
    inner_address: Optional[str] = None
    memos: Optional[list[str]] = None
    coins: Optional[list[Coin]] = None  # for both
    extra_delta: Optional[str] = None  # str to support negative ints :(
    tail_reveal: Optional[bytes] = None
    tail_solution: Optional[bytes] = None
    # for create_signed_transaction
    morph_bytes: Optional[bytes] = None
    coin_announcements: Optional[list[CSTCoinAnnouncement]] = None
    puzzle_announcements: Optional[list[CSTPuzzleAnnouncement]] = None

    def convert_to_proxy(self, proxy_type: type[_T_SendTransactionMultiProxy]) -> _T_SendTransactionMultiProxy:
        if proxy_type is CATSpend:
            if self.morph_bytes is not None:
                raise ValueError(
                    'Specified "morph_bytes" for a CAT-type wallet. Maybe you meant to specify an XCH wallet?'
                )
            elif self.coin_announcements or self.puzzle_announcements is not None:
                raise ValueError(
                    'Specified "coin/puzzle_announcements" for a CAT-type wallet.'
                    "Maybe you meant to specify an XCH wallet?"
                )

            # not sure why mypy hasn't understood this is purely a CATSpend
            return proxy_type(
                wallet_id=self.wallet_id,
                additions=self.additions,  # type: ignore[arg-type]
                amount=self.amount,  # type: ignore[call-arg]
                inner_address=self.inner_address,
                memos=self.memos,
                coins=self.coins,
                extra_delta=self.extra_delta,
                tail_reveal=self.tail_reveal,
                tail_solution=self.tail_solution,
                fee=self.fee,
                push=self.push,
                sign=self.sign,
            )
        elif proxy_type is CreateSignedTransaction:
            if self.amount is not None:
                raise ValueError('Specified "amount" for an XCH wallet. Maybe you meant to specify a CAT-type wallet?')
            elif self.inner_address is not None:
                raise ValueError(
                    'Specified "inner_address" for an XCH wallet. Maybe you meant to specify a CAT-type wallet?'
                )
            elif self.memos is not None:
                raise ValueError('Specified "memos" for an XCH wallet. Maybe you meant to specify a CAT-type wallet?')
            elif self.extra_delta is not None or self.tail_reveal is not None or self.tail_solution is not None:
                raise ValueError(
                    'Specified "extra_delta", "tail_reveal", or "tail_solution" for an XCH wallet.'
                    "Maybe you meant to specify a CAT-type wallet?"
                )
            elif self.additions is None:
                raise ValueError('"additions" are required for XCH wallets.')

            # not sure why mypy hasn't understood this is purely a CreateSignedTransaction
            return proxy_type(
                additions=self.additions,
                wallet_id=self.wallet_id,
                coins=self.coins,
                morph_bytes=self.morph_bytes,  # type: ignore[call-arg]
                coin_announcements=self.coin_announcements if self.coin_announcements is not None else [],
                puzzle_announcements=self.puzzle_announcements if self.puzzle_announcements is not None else [],
                fee=self.fee,
                push=self.push,
                sign=self.sign,
            )
        else:
            raise ValueError("An unsupported wallet type was selected for `send_transaction_multi`")


@streamable
@dataclass(frozen=True)
class SendTransactionMultiResponse(TransactionEndpointResponse):
    transaction: TransactionRecord
    transaction_id: bytes32


@streamable
@dataclass(frozen=True)
class _OfferEndpointResponse(TransactionEndpointResponse):
    offer: Offer  # gotta figure out how to ignore this in streamable
    trade_record: TradeRecord

    def to_json_dict(self) -> dict[str, Any]:
        old_offer_override = getattr(self.offer, "json_serialization_override", None)
        object.__setattr__(self.offer, "json_serialization_override", lambda o: o.to_bech32())
        try:
            response = {**super().to_json_dict(), "trade_record": self.trade_record.to_json_dict_convenience()}
        except Exception:
            object.__setattr__(self.offer, "json_serialization_override", old_offer_override)
            raise
        return response

    @classmethod
    def from_json_dict(cls, json_dict: dict[str, Any]) -> Self:
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
class CreateOfferForIDs(TransactionEndpointRequest):
    # a hack for dict[str, int] because streamable doesn't support negative ints
    offer: dict[str, str] = field(default_factory=default_raise)
    driver_dict: Optional[dict[bytes32, PuzzleInfo]] = None
    solver: Optional[Solver] = None
    validate_only: bool = False

    @property
    def offer_spec(self) -> dict[Union[int, bytes32], int]:
        modified_offer: dict[Union[int, bytes32], int] = {}
        for wallet_identifier, change in self.offer.items():
            if len(wallet_identifier) > 16:  # wallet IDs are uint32 therefore no longer than 8 bytes :P
                modified_offer[bytes32.from_hexstr(wallet_identifier)] = int(change)
            else:
                modified_offer[int(wallet_identifier)] = int(change)

        return modified_offer


@streamable
@dataclass(frozen=True)
class CreateOfferForIDsResponse(_OfferEndpointResponse):
    pass


@streamable
@dataclass(frozen=True)
class TakeOffer(TransactionEndpointRequest):
    offer: str = field(default_factory=default_raise)
    solver: Optional[Solver] = None

    @cached_property
    def parsed_offer(self) -> Offer:
        return Offer.from_bech32(self.offer)


@streamable
@dataclass(frozen=True)
class TakeOfferResponse(_OfferEndpointResponse):  # Inheriting for de-dup sake
    pass


@streamable
@dataclass(frozen=True)
class GetOffer(Streamable):
    trade_id: bytes32
    file_contents: bool = False


@streamable
@dataclass(frozen=True)
class GetOfferResponse(Streamable):
    offer: Optional[str]
    trade_record: TradeRecord

    def to_json_dict(self) -> dict[str, Any]:
        return {**super().to_json_dict(), "trade_record": self.trade_record.to_json_dict_convenience()}

    @classmethod
    def from_json_dict(cls, json_dict: dict[str, Any]) -> Self:
        return cls(
            offer=json_dict["offer"],
            trade_record=TradeRecord.from_json_dict_convenience(
                json_dict["trade_record"],
                bytes(Offer.from_bech32(json_dict["offer"])).hex() if json_dict["offer"] is not None else "",
            ),
        )


@streamable
@dataclass(frozen=True)
class GetAllOffers(Streamable):
    start: uint16 = uint16(0)
    end: uint16 = uint16(10)
    exclude_my_offers: bool = False
    exclude_taken_offers: bool = False
    include_completed: bool = False
    sort_key: Optional[str] = None
    reverse: bool = False
    file_contents: bool = False


@streamable
@dataclass(frozen=True)
class GetAllOffersResponse(Streamable):
    offers: Optional[list[str]]
    trade_records: list[TradeRecord]

    def to_json_dict(self) -> dict[str, Any]:
        return {**super().to_json_dict(), "trade_records": [tr.to_json_dict_convenience() for tr in self.trade_records]}

    @classmethod
    def from_json_dict(cls, json_dict: dict[str, Any]) -> Self:
        return cls(
            offers=json_dict["offers"],
            trade_records=[
                TradeRecord.from_json_dict_convenience(
                    json_tr,
                    bytes(Offer.from_bech32(json_dict["offers"][i])).hex() if json_dict["offers"] is not None else "",
                )
                for i, json_tr in enumerate(json_dict["trade_records"])
            ],
        )


@streamable
@dataclass(frozen=True)
class CancelOffer(TransactionEndpointRequest):
    trade_id: bytes32 = field(default_factory=default_raise)
    secure: bool = field(default_factory=default_raise)


@streamable
@dataclass(frozen=True)
class CancelOfferResponse(TransactionEndpointResponse):
    pass


@streamable
@dataclass(frozen=True)
class CancelOffers(TransactionEndpointRequest):
    secure: bool = field(default_factory=default_raise)
    batch_fee: uint64 = uint64(0)
    batch_size: uint16 = uint16(5)
    cancel_all: bool = False
    asset_id: str = "xch"


@streamable
@dataclass(frozen=True)
class CancelOffersResponse(TransactionEndpointResponse):
    pass


# utilities for CreateNewWallet
@streamable_enum(str)
class CreateNewWalletType(Enum):
    CAT_WALLET = "cat_wallet"
    DID_WALLET = "did_wallet"
    NFT_WALLET = "nft_wallet"
    POOL_WALLET = "pool_wallet"


@streamable_enum(str)
class WalletCreationMode(Enum):
    NEW = "new"
    EXISTING = "existing"


@streamable_enum(str)
class DIDType(Enum):
    NEW = "new"
    RECOVERY = "recovery"


@streamable
@dataclass(frozen=True)
class CreateNewWallet(TransactionEndpointRequest):
    wallet_type: CreateNewWalletType = field(default_factory=default_raise)
    # CAT_WALLET
    mode: Optional[WalletCreationMode] = None  # required
    amount: Optional[uint64] = None  # required in "new"
    name: Optional[str] = None  # If not provided, the name will be autogenerated based on the tail hash
    test: bool = False  # must be True in "new"
    asset_id: Optional[str] = None  # required in "existing"

    # DID_WALLET
    did_type: Optional[DIDType] = None  # required
    # only in "new"
    # amount: uint64  # already defined, required
    backup_dids: list[str] = field(default_factory=list)  # must error if not []
    metadata: dict[str, str] = field(default_factory=dict)
    wallet_name: Optional[str] = None
    # only in "recovery"
    backup_data: Optional[str] = None  # required

    # NFT_WALLET
    did_id: Optional[str] = None
    # name: Optional[str] = None  # already defined

    # POOL_WALLET
    # mode: WalletCreationMode  # already defined, required, must be "new"
    initial_target_state: Optional[NewPoolWalletInitialTargetState] = None  # required
    p2_singleton_delayed_ph: Optional[bytes32] = None
    p2_singleton_delay_time: Optional[uint64] = None

    def __post_init__(self) -> None:
        if self.wallet_type == CreateNewWalletType.CAT_WALLET:
            if self.mode is None:
                raise ValueError('Must specify a "mode" when creating a new CAT wallet')
            if self.mode == WalletCreationMode.NEW:
                if not self.test:
                    raise ValueError(
                        "Support for this RPC mode has been dropped."
                        " Please use the CAT Admin Tool @ https://github.com/Chia-Network/CAT-admin-tool instead."
                    )
                if self.amount is None:
                    raise ValueError('Must specify an "amount" of CATs to generate')
                if self.asset_id is not None:
                    raise ValueError('"asset_id" is not an argument for new CAT wallets. Maybe you meant existing?')
            if self.mode == WalletCreationMode.EXISTING:
                if self.asset_id is None:
                    raise ValueError('Must specify an "asset_id" when creating an existing CAT wallet')
                if self.amount is not None:
                    raise ValueError('"amount" is not an argument for existing CAT wallets')
        elif self.test:
            raise ValueError('"test" mode is not supported except for new CAT wallets')
        else:
            if self.asset_id is not None:
                raise ValueError(
                    '"asset_id" is not a valid argument. Maybe you meant to create an existing CAT wallet?'
                )
            if self.mode != WalletCreationMode.NEW:
                raise ValueError('"mode": "existing" is only valid for CAT wallets')

        if self.wallet_type == CreateNewWalletType.DID_WALLET:
            if self.did_type is None:
                raise ValueError('Must specify "did_type": "new/recovery"')
            if self.did_type == DIDType.NEW:
                if self.amount is None:
                    raise ValueError('Must specify an "amount" when creating a new DID')
                if self.backup_dids != []:
                    raise ValueError('Recovery options are no longer supported. "backup_dids" cannot be set.')
                if self.backup_data is not None:
                    raise ValueError('"backup_data" is only an option in "did_type": "recovery"')
            if self.did_type == DIDType.RECOVERY:
                if self.amount is not None:
                    raise ValueError('Cannot specify an "amount" when recovering a DID')
                if self.backup_dids != []:
                    raise ValueError('Cannot specify "backup_dids" when recovering a DID')
                if self.metadata != {}:
                    raise ValueError('Cannot specify "metadata" when recovering a DID')
                if self.backup_data is None:
                    raise ValueError('Must specify "backup_data" when recovering a DID')
        else:
            if self.did_type is not None:
                raise ValueError('"did_type" is only a valid argument for DID wallets')
            if self.backup_dids != []:
                raise ValueError('"backup_dids" is only a valid argument for DID wallets')
            if self.metadata != {}:
                raise ValueError('"metadata" is only a valid argument for DID wallets')
            if self.wallet_name is not None:
                raise ValueError('"wallet_name" is only a valid argument for DID wallets')
            if self.backup_data is not None:
                raise ValueError('"backup_data" is only a valid argument for DID wallets')

        if self.wallet_type != CreateNewWalletType.NFT_WALLET and self.did_id is not None:
            raise ValueError('"did_id" is only a valid argument for NFT wallets')

        if self.wallet_type == CreateNewWalletType.POOL_WALLET:
            if self.initial_target_state is None:
                raise ValueError('"initial_target_state" is required for new pool wallets')
        else:
            if self.initial_target_state is not None:
                raise ValueError('"initial_target_state" is only a valid argument for pool wallets')
            if self.p2_singleton_delayed_ph is not None:
                raise ValueError('"p2_singleton_delayed_ph" is only a valid argument for pool wallets')
            if self.p2_singleton_delay_time is not None:
                raise ValueError('"p2_singleton_delay_time" is only a valid argument for pool wallets')

        super().__post_init__()


@streamable
@dataclass(frozen=True)
class CreateNewWalletResponse(TransactionEndpointResponse):
    type: str  # Alias for WalletType which is IntEnum and therefore incompatible
    wallet_id: uint32
    # Nothing below is truly optional when that type is being returned
    # CAT_WALLET (TXEndpoint)
    asset_id: Optional[bytes32] = None
    # DID_WALLET - NEW (TXEndpoint) / RECOVERY
    my_did: Optional[str] = None
    # DID_WALLET - RECOVERY
    coin_name: Optional[bytes32] = None
    coin_list: Optional[Coin] = None
    newpuzhash: Optional[bytes32] = None
    pubkey: Optional[G1Element] = None
    backup_dids: Optional[list[bytes32]] = None
    num_verifications_required: Optional[uint64] = None
    # NFT_WALLET
    # ...
    # POOL_WALLET (TXEndpoint)
    total_fee: Optional[uint64] = None
    transaction: Optional[TransactionRecord] = None
    launcher_id: Optional[bytes32] = None
    p2_singleton_puzzle_hash: Optional[bytes32] = None

    def __post_init__(self) -> None:
        if self.type not in {member.name for member in WalletType}:
            raise ValueError(f"Invalid wallet type: {self.type}")
        super().__post_init__()

    def to_json_dict(self) -> dict[str, Any]:
        field_names = {"type", "wallet_id"}
        tx_endpoint_field_names = set(field.name for field in fields(TransactionEndpointResponse))
        serialization_updates: dict[str, Any] = {}
        wallet_type = next(member for member in WalletType if member.name == self.type)
        if wallet_type == WalletType.CAT:
            if self.asset_id is None:
                raise ValueError("`asset_id` is required for CAT wallets")
            field_names &= {"asset_id"}
            field_names &= tx_endpoint_field_names
        elif wallet_type == WalletType.DECENTRALIZED_ID:
            if self.my_did is None:
                raise ValueError("`my_did` is required for DID wallets")
            field_names &= {"my_did"}
            if (
                self.coin_name is not None
                and self.coin_list is not None
                and self.newpuzhash is not None
                and self.pubkey is not None
                and self.backup_dids is not None
                and self.num_verifications_required is not None
            ):
                field_names &= {
                    "coin_name",
                    "coin_list",
                    "newpuzhash",
                    "pubkey",
                    "backup_dids",
                    "num_verifications_required",
                }
                serialization_updates["coin_list"] = coin_as_list(self.coin_list)
            elif not (
                self.coin_name is None
                and self.coin_list is None
                and self.newpuzhash is None
                and self.pubkey is None
                and self.backup_dids is None
                and self.num_verifications_required is None
            ):
                raise ValueError("Must specify all recovery options or none of them")
            else:
                field_names &= tx_endpoint_field_names
        elif wallet_type == WalletType.POOLING_WALLET:
            if not (
                (
                    self.total_fee is None
                    and self.transaction is None
                    and self.launcher_id is None
                    and self.p2_singleton_puzzle_hash is None
                )
                or (
                    self.total_fee is not None
                    and self.transaction is not None
                    and self.launcher_id is not None
                    and self.p2_singleton_puzzle_hash is not None
                )
            ):
                raise ValueError("Must specify all pooling options or none of them")
            else:
                field_names = {  # replaces the two that are for all others
                    "total_fee",
                    "transaction",
                    "launcher_id",
                    "p2_singleton_puzzle_hash",
                }
                field_names &= tx_endpoint_field_names

        return {**{k: v for k, v in super().to_json_dict().items() if k in field_names}, **serialization_updates}

    @classmethod
    def from_json_dict(cls, json_dict: dict[str, Any]) -> Self:
        if "transactions" not in json_dict:
            json_dict["transactions"] = []
        if "unsigned_transactions" not in json_dict:
            json_dict["unsigned_transactions"] = []
        return super().from_json_dict(json_dict)
