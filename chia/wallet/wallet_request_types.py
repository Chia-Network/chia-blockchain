from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, BinaryIO, final

from chia_rs import Coin, G1Element, G2Element, PrivateKey
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint16, uint32, uint64
from typing_extensions import Self

from chia.data_layer.data_layer_wallet import DataLayerSummary, Mirror
from chia.data_layer.singleton_record import SingletonRecord
from chia.pools.pool_wallet_info import PoolWalletInfo
from chia.types.blockchain_format.program import Program
from chia.types.coin_record import CoinRecord
from chia.util.byte_types import hexstr_to_bytes
from chia.util.streamable import Streamable, streamable
from chia.wallet.conditions import Condition, ConditionValidTimes, conditions_to_json_dicts
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
from chia.wallet.vc_wallet.vc_store import VCProofs, VCRecord
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_node import Balance
from chia.wallet.wallet_spend_bundle import WalletSpendBundle


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
    fingerprint: uint32 | None


@streamable
@dataclass(frozen=True)
class GetPublicKeysResponse(Streamable):
    keyring_is_locked: bool
    public_key_fingerprints: list[uint32] | None = None

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
    seed: str | None


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
    label: str | None = None


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
    type: uint16 | None = None
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
    fingerprint: uint32 | None = None


@streamable
@dataclass(frozen=True)
class GetWalletBalance(Streamable):
    wallet_id: uint32


@streamable
@dataclass(frozen=True)
class GetWalletBalances(Streamable):
    wallet_ids: list[uint32] | None = None


# utility for GetWalletBalanceResponse(s)
@streamable
@dataclass(frozen=True, kw_only=True)
class BalanceResponse(Balance):
    wallet_id: uint32 = field(default_factory=default_raise)
    wallet_type: uint8 = field(default_factory=default_raise)
    fingerprint: uint32 | None = None
    asset_id: bytes32 | None = None
    pending_approval_balance: uint64 | None = None


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
    start: uint16 | None = None
    end: uint16 | None = None
    sort_key: str | None = None
    reverse: bool = False
    to_address: str | None = None
    type_filter: TransactionTypeFilter | None = None
    confirmed: bool | None = None

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
    metadata: TransactionRecordMetadata | None = None


@streamable
@dataclass(frozen=True)
class GetTransactionsResponse(Streamable):
    transactions: list[TransactionRecordWithMetadata]
    wallet_id: uint32


@streamable
@dataclass(frozen=True)
class GetNotifications(Streamable):
    ids: list[bytes32] | None = None
    start: uint32 | None = None
    end: uint32 | None = None


@streamable
@dataclass(frozen=True)
class GetNotificationsResponse(Streamable):
    notifications: list[Notification]


@streamable
@dataclass(frozen=True)
class DeleteNotifications(Streamable):
    ids: list[bytes32] | None = None


@streamable
@dataclass(frozen=True)
class VerifySignature(Streamable):
    message: str
    pubkey: G1Element
    signature: G2Element
    signing_mode: str | None = None
    address: str | None = None


@streamable
@dataclass(frozen=True)
class VerifySignatureResponse(Streamable):
    isValid: bool
    error: str | None = None


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
    confirmed: bool | None = None
    type_filter: TransactionTypeFilter | None = None


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
    exclude_coins: list[Coin] | None = None  # for backwards compatibility

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
    start_height: uint32 | None = None
    end_height: uint32 | None = None
    include_spent_coins: bool = True


@streamable
@dataclass(frozen=True)
class GetCoinRecordsByNamesResponse(Streamable):
    coin_records: list[CoinRecord]


@streamable
@dataclass(frozen=True)
class GetCurrentDerivationIndexResponse(Streamable):
    index: uint32 | None


@streamable
@dataclass(frozen=True)
class ExtendDerivationIndex(Streamable):
    index: uint32


@streamable
@dataclass(frozen=True)
class ExtendDerivationIndexResponse(Streamable):
    index: uint32 | None


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
    wallet_id: uint32 | None
    name: str | None


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
    summary: OfferSummary | None = None
    data_layer_summary: DataLayerSummary | None = None

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
            summary: OfferSummary | DataLayerSummary = OfferSummary.from_json_dict(json_dict["summary"])
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
    recovery_list_hash: bytes32 | None
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
    recovery_list_hash: bytes32 | None = None
    num_verification: uint16 | None = None
    metadata: dict[str, str] | None = None


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
    coin_id: bytes32 | None = None


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
    wallet_id: uint32 | None = None


@streamable
@dataclass(frozen=True)
class NFTCountNFTsResponse(Streamable):
    wallet_id: uint32 | None
    count: uint64


@streamable
@dataclass(frozen=True)
class NFTGetNFTs(Streamable):
    wallet_id: uint32 | None = None
    start_index: uint32 = uint32(0)
    num: uint32 = uint32(50)


@streamable
@dataclass(frozen=True)
class NFTGetNFTsResponse(Streamable):
    wallet_id: uint32 | None
    nft_list: list[NFTInfo]


@streamable
@dataclass(frozen=True)
class NFTGetByDID(Streamable):
    did_id: str | None = None


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
    did_id: str | None


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
    asset: str | None
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
    fungible_asset: str | None
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
    singleton: SingletonRecord | None


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
    min_generation: uint32 | None = None
    max_generation: uint32 | None = None
    num_results: uint32 | None = None


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
    vc_record: VCRecord | None


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
    proof: VCProofsRPC | None


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
    def proof_dict(self) -> dict[bytes32, dict[str, str] | None]:
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
@dataclass(frozen=True, kw_only=True)
class TransactionEndpointRequest(Streamable):
    fee: uint64 = uint64(0)
    push: bool | None = None
    sign: bool | None = None

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
    puzzle_decorator: list[ClawbackPuzzleDecoratorOverride] | None = None


@streamable
@dataclass(frozen=True)
class SendTransactionResponse(TransactionEndpointResponse):
    transaction: TransactionRecord
    transaction_id: bytes32


@streamable
@dataclass(frozen=True)
class SpendClawbackCoins(TransactionEndpointRequest):
    coin_ids: list[bytes32] = field(default_factory=default_raise)
    batch_size: uint16 | None = None
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
    push: bool | None = True

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
@dataclass(frozen=True, kw_only=True)
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
@dataclass(frozen=True, kw_only=True)
class CombineCoins(TransactionEndpointRequest):
    wallet_id: uint32 = field(default_factory=default_raise)
    number_of_coins: uint16 = uint16(500)
    largest_first: bool = False
    target_coin_ids: list[bytes32] = field(default_factory=list)
    target_coin_amount: uint64 | None = None
    coin_num_limit: uint16 = uint16(500)


@streamable
@dataclass(frozen=True)
class CombineCoinsResponse(TransactionEndpointResponse):
    pass


# utility for CATSpend
# unfortunate that we can't use CreateCoin but the memos are taken as strings not bytes
@streamable
@dataclass(frozen=True)
class Addition(Streamable):
    amount: uint64
    puzzle_hash: bytes32
    memos: list[str] | None = None


@streamable
@dataclass(frozen=True, kw_only=True)
class CATSpend(TransactionEndpointRequest):
    wallet_id: uint32 = field(default_factory=default_raise)
    additions: list[Addition] | None = None
    amount: uint64 | None = None
    inner_address: str | None = None
    memos: list[str] | None = None
    coins: list[Coin] | None = None
    extra_delta: str | None = None  # str to support negative ints :(
    tail_reveal: bytes | None = None
    tail_solution: bytes | None = None

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
    def cat_discrepancy(self) -> tuple[int, Program, Program] | None:
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
@dataclass(frozen=True, kw_only=True)
class DIDMessageSpend(TransactionEndpointRequest):
    wallet_id: uint32 = field(default_factory=default_raise)
    coin_announcements: list[bytes] = field(default_factory=list)
    puzzle_announcements: list[bytes] = field(default_factory=list)


@streamable
@dataclass(frozen=True)
class DIDMessageSpendResponse(TransactionEndpointResponse):
    spend_bundle: WalletSpendBundle


@streamable
@dataclass(frozen=True, kw_only=True)
class DIDUpdateMetadata(TransactionEndpointRequest):
    wallet_id: uint32 = field(default_factory=default_raise)
    metadata: dict[str, str] = field(default_factory=dict)


@streamable
@dataclass(frozen=True)
class DIDUpdateMetadataResponse(TransactionEndpointResponse):
    spend_bundle: WalletSpendBundle
    wallet_id: uint32


@streamable
@dataclass(frozen=True, kw_only=True)
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
@dataclass(frozen=True, kw_only=True)
class NFTMintNFTRequest(TransactionEndpointRequest):
    wallet_id: uint32 = field(default_factory=default_raise)
    royalty_address: str | None = field(default_factory=default_raise)
    target_address: str | None = field(default_factory=default_raise)
    uris: list[str] = field(default_factory=default_raise)
    hash: bytes32 = field(default_factory=default_raise)
    royalty_amount: uint16 = uint16(0)
    meta_uris: list[str] = field(default_factory=list)
    license_uris: list[str] = field(default_factory=list)
    edition_number: uint64 = uint64(1)
    edition_total: uint64 = uint64(1)
    meta_hash: bytes32 | None = None
    license_hash: bytes32 | None = None
    did_id: str | None = None


@streamable
@dataclass(frozen=True)
class NFTMintNFTResponse(TransactionEndpointResponse):
    wallet_id: uint32
    spend_bundle: WalletSpendBundle
    nft_id: str


@streamable
@dataclass(frozen=True, kw_only=True)
class NFTSetNFTDID(TransactionEndpointRequest):
    wallet_id: uint32 = field(default_factory=default_raise)
    nft_coin_id: bytes32 = field(default_factory=default_raise)
    did_id: str | None = None


@streamable
@dataclass(frozen=True)
class NFTSetNFTDIDResponse(TransactionEndpointResponse):
    wallet_id: uint32
    spend_bundle: WalletSpendBundle


@streamable
@dataclass(frozen=True, kw_only=True)
class NFTSetDIDBulk(TransactionEndpointRequest):
    nft_coin_list: list[NFTCoin] = field(default_factory=default_raise)
    did_id: str | None = None


@streamable
@dataclass(frozen=True)
class NFTSetDIDBulkResponse(TransactionEndpointResponse):
    wallet_id: list[uint32]
    tx_num: uint16
    spend_bundle: WalletSpendBundle


@streamable
@dataclass(frozen=True, kw_only=True)
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
@dataclass(frozen=True, kw_only=True)
class CreateNewDL(TransactionEndpointRequest):
    root: bytes32 = field(default_factory=default_raise)


@streamable
@dataclass(frozen=True)
class CreateNewDLResponse(TransactionEndpointResponse):
    launcher_id: bytes32


@streamable
@dataclass(frozen=True, kw_only=True)
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
@dataclass(frozen=True, kw_only=True)
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
@dataclass(frozen=True, kw_only=True)
class DLNewMirror(TransactionEndpointRequest):
    launcher_id: bytes32 = field(default_factory=default_raise)
    amount: uint64 = field(default_factory=default_raise)
    urls: list[str] = field(default_factory=default_raise)


@streamable
@dataclass(frozen=True)
class DLNewMirrorResponse(TransactionEndpointResponse):
    pass


@streamable
@dataclass(frozen=True, kw_only=True)
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
    meta_hash: bytes32 | None = None
    license_hash: bytes32 | None = None


@streamable
@dataclass(frozen=True)
class NFTMintBulk(TransactionEndpointRequest):
    wallet_id: uint32 = field(default_factory=default_raise)
    metadata_list: list[NFTMintMetadata] = field(default_factory=default_raise)
    royalty_address: str | None = None
    royalty_percentage: uint16 | None = None
    target_list: list[str] = field(default_factory=list)
    mint_number_start: uint16 = uint16(1)
    mint_total: uint16 | None = None
    xch_coins: list[Coin] | None = None
    xch_change_target: str | None = None
    new_innerpuzhash: bytes32 | None = None
    new_p2_puzhash: bytes32 | None = None
    did_coin: Coin | None = None
    did_lineage_parent: bytes32 | None = None
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
    fee_transaction: TransactionRecord | None


@streamable
@dataclass(frozen=True)
class PWSelfPool(TransactionEndpointRequest):
    wallet_id: uint32 = field(default_factory=default_raise)


@streamable
@dataclass(frozen=True)
class PWSelfPoolResponse(TransactionEndpointResponse):
    total_fee: uint64
    transaction: TransactionRecord
    fee_transaction: TransactionRecord | None


@streamable
@dataclass(frozen=True)
class PWAbsorbRewards(TransactionEndpointRequest):
    wallet_id: uint32 = field(default_factory=default_raise)
    max_spends_in_tx: uint16 | None = None


@streamable
@dataclass(frozen=True)
class PWAbsorbRewardsResponse(TransactionEndpointResponse):
    state: PoolWalletInfo
    transaction: TransactionRecord
    fee_transaction: TransactionRecord | None


@streamable
@dataclass(frozen=True)
class VCMint(TransactionEndpointRequest):
    did_id: str = field(default_factory=default_raise)
    target_address: str | None = None


@streamable
@dataclass(frozen=True)
class VCMintResponse(TransactionEndpointResponse):
    vc_record: VCRecord


@streamable
@dataclass(frozen=True)
class VCSpend(TransactionEndpointRequest):
    vc_id: bytes32 = field(default_factory=default_raise)
    new_puzhash: bytes32 | None = None
    new_proof_hash: bytes32 | None = None
    provider_inner_puzhash: bytes32 | None = None


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


# TODO: The section below needs corresponding request types
# TODO: The section below should be added to the API (currently only for client)


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
    driver_dict: dict[bytes32, PuzzleInfo] | None = None
    solver: Solver | None = None
    validate_only: bool = False

    @property
    def offer_spec(self) -> dict[int | bytes32, int]:
        modified_offer: dict[int | bytes32, int] = {}
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
    solver: Solver | None = None

    @cached_property
    def parsed_offer(self) -> Offer:
        return Offer.from_bech32(self.offer)


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
