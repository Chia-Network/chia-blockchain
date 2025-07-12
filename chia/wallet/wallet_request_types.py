from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Optional, final

from chia_rs import Coin, G1Element, G2Element, PrivateKey
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16, uint32, uint64
from typing_extensions import Self, dataclass_transform

from chia.data_layer.data_layer_wallet import Mirror
from chia.data_layer.singleton_record import SingletonRecord
from chia.pools.pool_wallet_info import PoolWalletInfo
from chia.types.blockchain_format.program import Program
from chia.util.byte_types import hexstr_to_bytes
from chia.util.streamable import Streamable, streamable
from chia.wallet.conditions import Condition, ConditionValidTimes
from chia.wallet.nft_wallet.nft_info import NFTInfo
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
from chia.wallet.util.tx_config import TXConfig
from chia.wallet.vc_wallet.vc_store import VCProofs, VCRecord
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
class DIDGetRecoveryInfo(Streamable):
    wallet_id: uint32


@streamable
@dataclass(frozen=True)
class DIDGetRecoveryInfoResponse(Streamable):
    wallet_id: uint32
    my_did: str
    coin_name: bytes32
    newpuzhash: Optional[bytes32]
    pubkey: Optional[G1Element]
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
class DIDGetRecoveryList(Streamable):
    wallet_id: uint32


@streamable
@dataclass(frozen=True)
class DIDGetRecoveryListResponse(Streamable):
    wallet_id: uint32
    recovery_list: list[str]
    num_required: uint16


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
class DIDUpdateRecoveryIDs(TransactionEndpointRequest):
    wallet_id: uint32 = field(default_factory=default_raise)
    new_list: list[str] = field(default_factory=default_raise)
    num_verifications_required: Optional[uint64] = None


@streamable
@dataclass(frozen=True)
class DIDUpdateRecoveryIDsResponse(TransactionEndpointResponse):
    pass


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
class CATSpendResponse(TransactionEndpointResponse):
    transaction: TransactionRecord
    transaction_id: bytes32


@streamable
@dataclass(frozen=True)
class _OfferEndpointResponse(TransactionEndpointResponse):
    offer: Offer
    trade_record: TradeRecord

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
