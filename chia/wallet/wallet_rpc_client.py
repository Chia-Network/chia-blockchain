from __future__ import annotations

from typing import Any

from chia_rs.sized_ints import uint32, uint64

from chia.data_layer.data_layer_util import DLProof, VerifyProofResponse
from chia.rpc.rpc_client import RpcClient
from chia.wallet.conditions import Condition, ConditionValidTimes
from chia.wallet.puzzles.clawback.metadata import AutoClaimSettings
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.clvm_streamable import json_deserialize_with_clvm_streamable
from chia.wallet.util.tx_config import TXConfig
from chia.wallet.wallet_coin_store import GetCoinRecords
from chia.wallet.wallet_request_types import (
    AddKey,
    AddKeyResponse,
    ApplySignatures,
    ApplySignaturesResponse,
    CancelOffer,
    CancelOfferResponse,
    CancelOffers,
    CancelOffersResponse,
    CATAssetIDToName,
    CATAssetIDToNameResponse,
    CATGetAssetID,
    CATGetAssetIDResponse,
    CATGetName,
    CATGetNameResponse,
    CATSetName,
    CATSetNameResponse,
    CATSpend,
    CATSpendResponse,
    CheckDeleteKey,
    CheckDeleteKeyResponse,
    CheckOfferValidity,
    CheckOfferValidityResponse,
    CombineCoins,
    CombineCoinsResponse,
    CreateNewDL,
    CreateNewDLResponse,
    CreateNewWallet,
    CreateNewWalletResponse,
    CreateOfferForIDs,
    CreateOfferForIDsResponse,
    CreateSignedTransaction,
    CreateSignedTransactionsResponse,
    DeleteKey,
    DeleteNotifications,
    DeleteUnconfirmedTransactions,
    DIDCreateBackupFile,
    DIDCreateBackupFileResponse,
    DIDFindLostDID,
    DIDFindLostDIDResponse,
    DIDGetCurrentCoinInfo,
    DIDGetCurrentCoinInfoResponse,
    DIDGetDID,
    DIDGetDIDResponse,
    DIDGetInfo,
    DIDGetInfoResponse,
    DIDGetMetadata,
    DIDGetMetadataResponse,
    DIDGetPubkey,
    DIDGetPubkeyResponse,
    DIDGetWalletName,
    DIDGetWalletNameResponse,
    DIDMessageSpend,
    DIDMessageSpendResponse,
    DIDSetWalletName,
    DIDSetWalletNameResponse,
    DIDTransferDID,
    DIDTransferDIDResponse,
    DIDUpdateMetadata,
    DIDUpdateMetadataResponse,
    DLDeleteMirror,
    DLDeleteMirrorResponse,
    DLGetMirrors,
    DLGetMirrorsResponse,
    DLHistory,
    DLHistoryResponse,
    DLLatestSingleton,
    DLLatestSingletonResponse,
    DLNewMirror,
    DLNewMirrorResponse,
    DLOwnedSingletonsResponse,
    DLSingletonsByRoot,
    DLSingletonsByRootResponse,
    DLStopTracking,
    DLTrackNew,
    DLUpdateMultiple,
    DLUpdateMultipleResponse,
    DLUpdateRoot,
    DLUpdateRootResponse,
    ExecuteSigningInstructions,
    ExecuteSigningInstructionsResponse,
    ExtendDerivationIndex,
    ExtendDerivationIndexResponse,
    GatherSigningInfo,
    GatherSigningInfoResponse,
    GenerateMnemonicResponse,
    GetAllOffers,
    GetAllOffersResponse,
    GetCATListResponse,
    GetCoinRecordsByNames,
    GetCoinRecordsByNamesResponse,
    GetCurrentDerivationIndexResponse,
    GetHeightInfoResponse,
    GetLoggedInFingerprintResponse,
    GetNextAddress,
    GetNextAddressResponse,
    GetNotifications,
    GetNotificationsResponse,
    GetOffer,
    GetOfferResponse,
    GetOffersCountResponse,
    GetOfferSummary,
    GetOfferSummaryResponse,
    GetPrivateKey,
    GetPrivateKeyResponse,
    GetPublicKeysResponse,
    GetSpendableCoins,
    GetSpendableCoinsResponse,
    GetStrayCATsResponse,
    GetSyncStatusResponse,
    GetTimestampForHeight,
    GetTimestampForHeightResponse,
    GetTransaction,
    GetTransactionCount,
    GetTransactionCountResponse,
    GetTransactionMemo,
    GetTransactionMemoResponse,
    GetTransactionResponse,
    GetTransactions,
    GetTransactionsResponse,
    GetWalletBalance,
    GetWalletBalanceResponse,
    GetWalletBalances,
    GetWalletBalancesResponse,
    GetWallets,
    GetWalletsResponse,
    LogIn,
    LogInResponse,
    NFTAddURI,
    NFTAddURIResponse,
    NFTCalculateRoyalties,
    NFTCalculateRoyaltiesResponse,
    NFTCountNFTs,
    NFTCountNFTsResponse,
    NFTGetByDID,
    NFTGetByDIDResponse,
    NFTGetInfo,
    NFTGetInfoResponse,
    NFTGetNFTs,
    NFTGetNFTsResponse,
    NFTGetWalletDID,
    NFTGetWalletDIDResponse,
    NFTGetWalletsWithDIDsResponse,
    NFTMintBulk,
    NFTMintBulkResponse,
    NFTMintNFTRequest,
    NFTMintNFTResponse,
    NFTSetDIDBulk,
    NFTSetDIDBulkResponse,
    NFTSetNFTDID,
    NFTSetNFTDIDResponse,
    NFTSetNFTStatus,
    NFTTransferBulk,
    NFTTransferBulkResponse,
    NFTTransferNFT,
    NFTTransferNFTResponse,
    PushTransactions,
    PushTransactionsResponse,
    PushTX,
    PWAbsorbRewards,
    PWAbsorbRewardsResponse,
    PWJoinPool,
    PWJoinPoolResponse,
    PWSelfPool,
    PWSelfPoolResponse,
    PWStatus,
    PWStatusResponse,
    SelectCoins,
    SelectCoinsResponse,
    SendNotification,
    SendNotificationResponse,
    SendTransaction,
    SendTransactionMulti,
    SendTransactionMultiResponse,
    SendTransactionResponse,
    SetWalletResyncOnStartup,
    SignMessageByAddress,
    SignMessageByAddressResponse,
    SignMessageByID,
    SignMessageByIDResponse,
    SpendClawbackCoins,
    SpendClawbackCoinsResponse,
    SplitCoins,
    SplitCoinsResponse,
    SubmitTransactions,
    SubmitTransactionsResponse,
    TakeOffer,
    TakeOfferResponse,
    VCAddProofs,
    VCGet,
    VCGetList,
    VCGetListResponse,
    VCGetProofsForRoot,
    VCGetProofsForRootResponse,
    VCGetResponse,
    VCMint,
    VCMintResponse,
    VCRevoke,
    VCRevokeResponse,
    VCSpend,
    VCSpendResponse,
    VerifySignature,
    VerifySignatureResponse,
)


def parse_result_transactions(result: dict[str, Any]) -> dict[str, Any]:
    result["transaction"] = TransactionRecord.from_json_dict(result["transaction"])
    result["transactions"] = [TransactionRecord.from_json_dict(tx) for tx in result["transactions"]]
    if result["fee_transaction"]:
        result["fee_transaction"] = TransactionRecord.from_json_dict(result["fee_transaction"])
    return result


class WalletRpcClient(RpcClient):
    """
    Client to Chia RPC, connects to a local wallet. Uses HTTP/JSON, and converts back from
    JSON into native python objects before returning. All api calls use POST requests.
    Note that this is not the same as the peer protocol, or wallet protocol (which run Chia's
    protocol on top of TCP), it's a separate protocol on top of HTTP that provides easy access
    to the full node.
    """

    # Key Management APIs
    async def log_in(self, request: LogIn) -> LogInResponse:
        return LogInResponse.from_json_dict(await self.fetch("log_in", request.to_json_dict()))

    async def get_logged_in_fingerprint(self) -> GetLoggedInFingerprintResponse:
        return GetLoggedInFingerprintResponse.from_json_dict(await self.fetch("get_logged_in_fingerprint", {}))

    async def get_public_keys(self) -> GetPublicKeysResponse:
        return GetPublicKeysResponse.from_json_dict(await self.fetch("get_public_keys", {}))

    async def get_private_key(self, request: GetPrivateKey) -> GetPrivateKeyResponse:
        return GetPrivateKeyResponse.from_json_dict(await self.fetch("get_private_key", request.to_json_dict()))

    async def generate_mnemonic(self) -> GenerateMnemonicResponse:
        return GenerateMnemonicResponse.from_json_dict(await self.fetch("generate_mnemonic", {}))

    async def add_key(self, request: AddKey) -> AddKeyResponse:
        return AddKeyResponse.from_json_dict(await self.fetch("add_key", request.to_json_dict()))

    async def delete_key(self, request: DeleteKey) -> None:
        await self.fetch("delete_key", request.to_json_dict())

    async def check_delete_key(self, request: CheckDeleteKey) -> CheckDeleteKeyResponse:
        return CheckDeleteKeyResponse.from_json_dict(await self.fetch("check_delete_key", request.to_json_dict()))

    async def delete_all_keys(self) -> None:
        await self.fetch("delete_all_keys", {})

    # Wallet Node APIs
    async def set_wallet_resync_on_startup(self, request: SetWalletResyncOnStartup) -> None:
        await self.fetch("set_wallet_resync_on_startup", request.to_json_dict())

    async def get_sync_status(self) -> GetSyncStatusResponse:
        return GetSyncStatusResponse.from_json_dict(await self.fetch("get_sync_status", {}))

    async def get_height_info(self) -> GetHeightInfoResponse:
        return GetHeightInfoResponse.from_json_dict(await self.fetch("get_height_info", {}))

    async def push_tx(self, request: PushTX) -> None:
        await self.fetch("push_tx", request.to_json_dict())

    async def push_transactions(
        self,
        request: PushTransactions,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> PushTransactionsResponse:
        return PushTransactionsResponse.from_json_dict(
            await self.fetch(
                "push_transactions", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    async def get_timestamp_for_height(self, request: GetTimestampForHeight) -> GetTimestampForHeightResponse:
        return GetTimestampForHeightResponse.from_json_dict(
            await self.fetch("get_timestamp_for_height", request.to_json_dict())
        )

    async def set_auto_claim(self, request: AutoClaimSettings) -> AutoClaimSettings:
        return AutoClaimSettings.from_json_dict(await self.fetch("set_auto_claim", {**request.to_json_dict()}))

    async def get_auto_claim(self) -> AutoClaimSettings:
        return AutoClaimSettings.from_json_dict(await self.fetch("get_auto_claim", {}))

    # Wallet Management APIs
    async def get_wallets(self, request: GetWallets) -> GetWalletsResponse:
        return GetWalletsResponse.from_json_dict(await self.fetch("get_wallets", request.to_json_dict()))

    # Wallet APIs
    async def get_wallet_balance(self, request: GetWalletBalance) -> GetWalletBalanceResponse:
        return GetWalletBalanceResponse.from_json_dict(await self.fetch("get_wallet_balance", request.to_json_dict()))

    async def get_wallet_balances(self, request: GetWalletBalances) -> GetWalletBalancesResponse:
        return GetWalletBalancesResponse.from_json_dict(await self.fetch("get_wallet_balances", request.to_json_dict()))

    async def get_transaction(self, request: GetTransaction) -> GetTransactionResponse:
        return GetTransactionResponse.from_json_dict(await self.fetch("get_transaction", request.to_json_dict()))

    async def get_transactions(self, request: GetTransactions) -> GetTransactionsResponse:
        return GetTransactionsResponse.from_json_dict(await self.fetch("get_transactions", request.to_json_dict()))

    async def get_transaction_count(self, request: GetTransactionCount) -> GetTransactionCountResponse:
        return GetTransactionCountResponse.from_json_dict(
            await self.fetch("get_transaction_count", request.to_json_dict())
        )

    async def get_next_address(self, request: GetNextAddress) -> GetNextAddressResponse:
        return GetNextAddressResponse.from_json_dict(await self.fetch("get_next_address", request.to_json_dict()))

    async def create_new_wallet(
        self,
        request: CreateNewWallet,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> CreateNewWalletResponse:
        return CreateNewWalletResponse.from_json_dict(
            await self.fetch(
                "create_new_wallet",
                request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info),
            )
        )

    async def send_transaction(
        self,
        request: SendTransaction,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> SendTransactionResponse:
        return SendTransactionResponse.from_json_dict(
            await self.fetch(
                "send_transaction",
                request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info),
            )
        )

    async def send_transaction_multi(
        self,
        request: SendTransactionMulti,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> SendTransactionMultiResponse:
        return SendTransactionMultiResponse.from_json_dict(
            await self.fetch(
                "send_transaction_multi",
                request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info),
            )
        )

    async def spend_clawback_coins(
        self,
        request: SpendClawbackCoins,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> SpendClawbackCoinsResponse:
        return SpendClawbackCoinsResponse.from_json_dict(
            await self.fetch(
                "spend_clawback_coins", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    async def delete_unconfirmed_transactions(self, request: DeleteUnconfirmedTransactions) -> None:
        await self.fetch("delete_unconfirmed_transactions", request.to_json_dict())

    async def get_current_derivation_index(self) -> GetCurrentDerivationIndexResponse:
        return GetCurrentDerivationIndexResponse.from_json_dict(await self.fetch("get_current_derivation_index", {}))

    async def extend_derivation_index(self, request: ExtendDerivationIndex) -> ExtendDerivationIndexResponse:
        return ExtendDerivationIndexResponse.from_json_dict(
            await self.fetch("extend_derivation_index", request.to_json_dict())
        )

    async def get_farmed_amount(self, include_pool_rewards: bool = False) -> dict[str, Any]:
        return await self.fetch("get_farmed_amount", {"include_pool_rewards": include_pool_rewards})

    async def create_signed_transactions(
        self,
        request: CreateSignedTransaction,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> CreateSignedTransactionsResponse:
        return CreateSignedTransactionsResponse.from_json_dict(
            await self.fetch(
                "create_signed_transaction",
                request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info),
            )
        )

    async def select_coins(self, request: SelectCoins) -> SelectCoinsResponse:
        return SelectCoinsResponse.from_json_dict(await self.fetch("select_coins", request.to_json_dict()))

    async def get_coin_records(self, request: GetCoinRecords) -> dict[str, Any]:
        return await self.fetch("get_coin_records", request.to_json_dict())

    async def get_spendable_coins(self, request: GetSpendableCoins) -> GetSpendableCoinsResponse:
        return GetSpendableCoinsResponse.from_json_dict(await self.fetch("get_spendable_coins", request.to_json_dict()))

    async def get_coin_records_by_names(self, request: GetCoinRecordsByNames) -> GetCoinRecordsByNamesResponse:
        return GetCoinRecordsByNamesResponse.from_json_dict(
            await self.fetch("get_coin_records_by_names", request.to_json_dict())
        )

    # DID wallet
    async def get_did_id(self, request: DIDGetDID) -> DIDGetDIDResponse:
        return DIDGetDIDResponse.from_json_dict(await self.fetch("did_get_did", request.to_json_dict()))

    async def get_did_info(self, request: DIDGetInfo) -> DIDGetInfoResponse:
        return DIDGetInfoResponse.from_json_dict(await self.fetch("did_get_info", request.to_json_dict()))

    async def create_did_backup_file(self, request: DIDCreateBackupFile) -> DIDCreateBackupFileResponse:
        return DIDCreateBackupFileResponse.from_json_dict(
            await self.fetch("did_create_backup_file", request.to_json_dict())
        )

    async def did_message_spend(
        self,
        request: DIDMessageSpend,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> DIDMessageSpendResponse:
        return DIDMessageSpendResponse.from_json_dict(
            await self.fetch(
                "did_message_spend",
                request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info),
            )
        )

    async def update_did_metadata(
        self,
        request: DIDUpdateMetadata,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> DIDUpdateMetadataResponse:
        return DIDUpdateMetadataResponse.from_json_dict(
            await self.fetch(
                "did_update_metadata",
                request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info),
            )
        )

    async def get_did_pubkey(self, request: DIDGetPubkey) -> DIDGetPubkeyResponse:
        return DIDGetPubkeyResponse.from_json_dict(await self.fetch("did_get_pubkey", request.to_json_dict()))

    async def get_did_metadata(self, request: DIDGetMetadata) -> DIDGetMetadataResponse:
        return DIDGetMetadataResponse.from_json_dict(await self.fetch("did_get_metadata", request.to_json_dict()))

    async def find_lost_did(self, request: DIDFindLostDID) -> DIDFindLostDIDResponse:
        return DIDFindLostDIDResponse.from_json_dict(await self.fetch("did_find_lost_did", request.to_json_dict()))

    async def create_new_did_wallet_from_recovery(self, filename: str) -> dict[str, Any]:
        request = {"wallet_type": "did_wallet", "did_type": "recovery", "filename": filename}
        response = await self.fetch("create_new_wallet", request)
        return response

    async def did_get_current_coin_info(self, request: DIDGetCurrentCoinInfo) -> DIDGetCurrentCoinInfoResponse:
        return DIDGetCurrentCoinInfoResponse.from_json_dict(
            await self.fetch("did_get_current_coin_info", request.to_json_dict())
        )

    async def did_transfer_did(
        self,
        request: DIDTransferDID,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> DIDTransferDIDResponse:
        return DIDTransferDIDResponse.from_json_dict(
            await self.fetch(
                "did_transfer_did",
                request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info),
            )
        )

    async def did_set_wallet_name(self, request: DIDSetWalletName) -> DIDSetWalletNameResponse:
        return DIDSetWalletNameResponse.from_json_dict(await self.fetch("did_set_wallet_name", request.to_json_dict()))

    async def did_get_wallet_name(self, request: DIDGetWalletName) -> DIDGetWalletNameResponse:
        return DIDGetWalletNameResponse.from_json_dict(await self.fetch("did_get_wallet_name", request.to_json_dict()))

    async def pw_self_pool(
        self,
        request: PWSelfPool,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> PWSelfPoolResponse:
        return PWSelfPoolResponse.from_json_dict(
            await self.fetch(
                "pw_self_pool", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    async def pw_join_pool(
        self,
        request: PWJoinPool,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> PWJoinPoolResponse:
        return PWJoinPoolResponse.from_json_dict(
            await self.fetch(
                "pw_join_pool", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    async def pw_absorb_rewards(
        self,
        request: PWAbsorbRewards,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> PWAbsorbRewardsResponse:
        return PWAbsorbRewardsResponse.from_json_dict(
            await self.fetch(
                "pw_absorb_rewards", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    async def pw_status(self, request: PWStatus) -> PWStatusResponse:
        return PWStatusResponse.from_json_dict(await self.fetch("pw_status", request.to_json_dict()))

    # CATS
    async def get_cat_asset_id(self, request: CATGetAssetID) -> CATGetAssetIDResponse:
        return CATGetAssetIDResponse.from_json_dict(await self.fetch("cat_get_asset_id", request.to_json_dict()))

    async def get_stray_cats(self) -> GetStrayCATsResponse:
        return GetStrayCATsResponse.from_json_dict(await self.fetch("get_stray_cats", {}))

    async def cat_asset_id_to_name(self, request: CATAssetIDToName) -> CATAssetIDToNameResponse:
        return CATAssetIDToNameResponse.from_json_dict(await self.fetch("cat_asset_id_to_name", request.to_json_dict()))

    async def get_cat_name(self, request: CATGetName) -> CATGetNameResponse:
        return CATGetNameResponse.from_json_dict(await self.fetch("cat_get_name", request.to_json_dict()))

    async def set_cat_name(self, request: CATSetName) -> CATSetNameResponse:
        return CATSetNameResponse.from_json_dict(await self.fetch("cat_set_name", request.to_json_dict()))

    async def cat_spend(
        self,
        request: CATSpend,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> CATSpendResponse:
        return CATSpendResponse.from_json_dict(
            await self.fetch(
                "cat_spend", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    # Offers
    async def create_offer_for_ids(
        self,
        request: CreateOfferForIDs,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> CreateOfferForIDsResponse:
        return CreateOfferForIDsResponse.from_json_dict(
            await self.fetch(
                "create_offer_for_ids", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    async def get_offer_summary(self, request: GetOfferSummary) -> GetOfferSummaryResponse:
        return GetOfferSummaryResponse.from_json_dict(await self.fetch("get_offer_summary", request.to_json_dict()))

    async def check_offer_validity(self, request: CheckOfferValidity) -> CheckOfferValidityResponse:
        return CheckOfferValidityResponse.from_json_dict(
            await self.fetch("check_offer_validity", request.to_json_dict())
        )

    async def take_offer(
        self,
        request: TakeOffer,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> TakeOfferResponse:
        return TakeOfferResponse.from_json_dict(
            await self.fetch(
                "take_offer", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    async def get_offer(self, request: GetOffer) -> GetOfferResponse:
        return GetOfferResponse.from_json_dict(await self.fetch("get_offer", request.to_json_dict()))

    async def get_all_offers(self, request: GetAllOffers) -> GetAllOffersResponse:
        return GetAllOffersResponse.from_json_dict(await self.fetch("get_all_offers", request.to_json_dict()))

    async def get_offers_count(self) -> GetOffersCountResponse:
        return GetOffersCountResponse.from_json_dict(await self.fetch("get_offers_count", {}))

    async def cancel_offer(
        self,
        request: CancelOffer,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> CancelOfferResponse:
        return CancelOfferResponse.from_json_dict(
            await self.fetch(
                "cancel_offer", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    async def cancel_offers(
        self,
        request: CancelOffers,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> CancelOffersResponse:
        return CancelOffersResponse.from_json_dict(
            await self.fetch(
                "cancel_offers", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    async def get_cat_list(self) -> GetCATListResponse:
        return GetCATListResponse.from_json_dict(await self.fetch("get_cat_list", {}))

    # NFT wallet
    async def mint_nft(
        self,
        request: NFTMintNFTRequest,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> NFTMintNFTResponse:
        return NFTMintNFTResponse.from_json_dict(
            await self.fetch(
                "nft_mint_nft", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    async def add_uri_to_nft(
        self,
        request: NFTAddURI,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> NFTAddURIResponse:
        return NFTAddURIResponse.from_json_dict(
            await self.fetch(
                "nft_add_uri", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    async def nft_calculate_royalties(
        self,
        request: NFTCalculateRoyalties,
    ) -> NFTCalculateRoyaltiesResponse:
        return NFTCalculateRoyaltiesResponse.from_json_dict(
            await self.fetch("nft_calculate_royalties", request.to_json_dict())
        )

    async def get_nft_info(self, request: NFTGetInfo) -> NFTGetInfoResponse:
        return NFTGetInfoResponse.from_json_dict(await self.fetch("nft_get_info", request.to_json_dict()))

    async def transfer_nft(
        self,
        request: NFTTransferNFT,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> NFTTransferNFTResponse:
        return NFTTransferNFTResponse.from_json_dict(
            await self.fetch(
                "nft_transfer_nft", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    async def count_nfts(self, request: NFTCountNFTs) -> NFTCountNFTsResponse:
        return NFTCountNFTsResponse.from_json_dict(await self.fetch("nft_count_nfts", request.to_json_dict()))

    async def list_nfts(self, request: NFTGetNFTs) -> NFTGetNFTsResponse:
        return NFTGetNFTsResponse.from_json_dict(await self.fetch("nft_get_nfts", request.to_json_dict()))

    async def get_nft_wallet_by_did(self, request: NFTGetByDID) -> NFTGetByDIDResponse:
        return NFTGetByDIDResponse.from_json_dict(await self.fetch("nft_get_by_did", request.to_json_dict()))

    async def set_nft_did(
        self,
        request: NFTSetNFTDID,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> NFTSetNFTDIDResponse:
        return NFTSetNFTDIDResponse.from_json_dict(
            await self.fetch(
                "nft_set_nft_did", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    async def set_nft_status(self, request: NFTSetNFTStatus) -> None:
        await self.fetch("nft_set_nft_status", request.to_json_dict())

    async def get_nft_wallet_did(self, request: NFTGetWalletDID) -> NFTGetWalletDIDResponse:
        return NFTGetWalletDIDResponse.from_json_dict(await self.fetch("nft_get_wallet_did", request.to_json_dict()))

    async def get_nft_wallets_with_dids(self) -> NFTGetWalletsWithDIDsResponse:
        return NFTGetWalletsWithDIDsResponse.from_json_dict(await self.fetch("nft_get_wallets_with_dids", {}))

    async def nft_mint_bulk(
        self,
        request: NFTMintBulk,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> NFTMintBulkResponse:
        return NFTMintBulkResponse.from_json_dict(
            await self.fetch(
                "nft_mint_bulk", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    async def set_nft_did_bulk(
        self,
        request: NFTSetDIDBulk,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> NFTSetDIDBulkResponse:
        return NFTSetDIDBulkResponse.from_json_dict(
            await self.fetch(
                "nft_set_did_bulk", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    async def transfer_nft_bulk(
        self,
        request: NFTTransferBulk,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> NFTTransferBulkResponse:
        return NFTTransferBulkResponse.from_json_dict(
            await self.fetch(
                "nft_transfer_bulk", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    # DataLayer
    async def create_new_dl(
        self,
        request: CreateNewDL,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> CreateNewDLResponse:
        return CreateNewDLResponse.from_json_dict(
            await self.fetch(
                "create_new_dl", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    async def dl_track_new(self, request: DLTrackNew) -> None:
        await self.fetch("dl_track_new", request.to_json_dict())

    async def dl_stop_tracking(self, request: DLStopTracking) -> None:
        await self.fetch("dl_stop_tracking", request.to_json_dict())

    async def dl_latest_singleton(self, request: DLLatestSingleton) -> DLLatestSingletonResponse:
        return DLLatestSingletonResponse.from_json_dict(await self.fetch("dl_latest_singleton", request.to_json_dict()))

    async def dl_singletons_by_root(self, request: DLSingletonsByRoot) -> DLSingletonsByRootResponse:
        return DLSingletonsByRootResponse.from_json_dict(
            await self.fetch("dl_singletons_by_root", request.to_json_dict())
        )

    async def dl_update_root(
        self,
        request: DLUpdateRoot,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> DLUpdateRootResponse:
        return DLUpdateRootResponse.from_json_dict(
            await self.fetch(
                "dl_update_root", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    async def dl_update_multiple(
        self,
        request: DLUpdateMultiple,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> DLUpdateMultipleResponse:
        return DLUpdateMultipleResponse.from_json_dict(
            await self.fetch(
                "dl_update_multiple", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    async def dl_history(self, request: DLHistory) -> DLHistoryResponse:
        return DLHistoryResponse.from_json_dict(await self.fetch("dl_history", request.to_json_dict()))

    async def dl_owned_singletons(self) -> DLOwnedSingletonsResponse:
        return DLOwnedSingletonsResponse.from_json_dict(await self.fetch("dl_owned_singletons", {}))

    async def dl_get_mirrors(self, request: DLGetMirrors) -> DLGetMirrorsResponse:
        return DLGetMirrorsResponse.from_json_dict(await self.fetch("dl_get_mirrors", request.to_json_dict()))

    async def dl_new_mirror(
        self,
        request: DLNewMirror,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> DLNewMirrorResponse:
        return DLNewMirrorResponse.from_json_dict(
            await self.fetch(
                "dl_new_mirror", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    async def dl_delete_mirror(
        self,
        request: DLDeleteMirror,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> DLDeleteMirrorResponse:
        return DLDeleteMirrorResponse.from_json_dict(
            await self.fetch(
                "dl_delete_mirror", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    async def dl_verify_proof(self, request: DLProof) -> VerifyProofResponse:
        return VerifyProofResponse.from_json_dict(await self.fetch("dl_verify_proof", request.to_json_dict()))

    async def get_notifications(self, request: GetNotifications) -> GetNotificationsResponse:
        response = await self.fetch("get_notifications", request.to_json_dict())
        return json_deserialize_with_clvm_streamable(response, GetNotificationsResponse)

    async def delete_notifications(self, request: DeleteNotifications) -> None:
        await self.fetch("delete_notifications", request.to_json_dict())

    async def send_notification(
        self,
        request: SendNotification,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> SendNotificationResponse:
        return SendNotificationResponse.from_json_dict(
            await self.fetch(
                "send_notification", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    async def sign_message_by_address(self, request: SignMessageByAddress) -> SignMessageByAddressResponse:
        return SignMessageByAddressResponse.from_json_dict(
            await self.fetch("sign_message_by_address", request.to_json_dict())
        )

    async def sign_message_by_id(self, request: SignMessageByID) -> SignMessageByIDResponse:
        return SignMessageByIDResponse.from_json_dict(await self.fetch("sign_message_by_id", request.to_json_dict()))

    async def verify_signature(self, request: VerifySignature) -> VerifySignatureResponse:
        return VerifySignatureResponse.from_json_dict(await self.fetch("verify_signature", {**request.to_json_dict()}))

    async def get_transaction_memo(self, request: GetTransactionMemo) -> GetTransactionMemoResponse:
        return GetTransactionMemoResponse.from_json_dict(
            await self.fetch("get_transaction_memo", {**request.to_json_dict()})
        )

    async def vc_mint(
        self,
        request: VCMint,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> VCMintResponse:
        return VCMintResponse.from_json_dict(
            await self.fetch(
                "vc_mint", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    async def vc_get(self, request: VCGet) -> VCGetResponse:
        return VCGetResponse.from_json_dict(await self.fetch("vc_get", request.to_json_dict()))

    async def vc_get_list(self, request: VCGetList) -> VCGetListResponse:
        return VCGetListResponse.from_json_dict(await self.fetch("vc_get_list", request.to_json_dict()))

    async def vc_spend(
        self,
        request: VCSpend,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> VCSpendResponse:
        return VCSpendResponse.from_json_dict(
            await self.fetch(
                "vc_spend", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    async def vc_add_proofs(self, request: VCAddProofs) -> None:
        await self.fetch("vc_add_proofs", request.to_json_dict())

    async def vc_get_proofs_for_root(self, request: VCGetProofsForRoot) -> VCGetProofsForRootResponse:
        return VCGetProofsForRootResponse.from_json_dict(
            await self.fetch("vc_get_proofs_for_root", request.to_json_dict())
        )

    async def vc_revoke(
        self,
        request: VCRevoke,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> VCRevokeResponse:
        return VCRevokeResponse.from_json_dict(
            await self.fetch(
                "vc_revoke", request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    async def crcat_approve_pending(
        self,
        wallet_id: uint32,
        min_amount_to_claim: uint64,
        tx_config: TXConfig,
        fee: uint64 = uint64(0),
        push: bool = True,
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> list[TransactionRecord]:
        response = await self.fetch(
            "crcat_approve_pending",
            {
                "wallet_id": wallet_id,
                "min_amount_to_claim": min_amount_to_claim,
                "fee": fee,
                "push": push,
                **tx_config.to_json_dict(),
                **timelock_info.to_json_dict(),
            },
        )
        return [TransactionRecord.from_json_dict(tx) for tx in response["transactions"]]

    async def gather_signing_info(
        self,
        args: GatherSigningInfo,
    ) -> GatherSigningInfoResponse:
        return json_deserialize_with_clvm_streamable(
            await self.fetch(
                "gather_signing_info",
                args.to_json_dict(),
            ),
            GatherSigningInfoResponse,
        )

    async def apply_signatures(
        self,
        args: ApplySignatures,
    ) -> ApplySignaturesResponse:
        return json_deserialize_with_clvm_streamable(
            await self.fetch(
                "apply_signatures",
                args.to_json_dict(),
            ),
            ApplySignaturesResponse,
        )

    async def submit_transactions(
        self,
        args: SubmitTransactions,
    ) -> SubmitTransactionsResponse:
        return json_deserialize_with_clvm_streamable(
            await self.fetch(
                "submit_transactions",
                args.to_json_dict(),
            ),
            SubmitTransactionsResponse,
        )

    async def execute_signing_instructions(
        self,
        args: ExecuteSigningInstructions,
    ) -> ExecuteSigningInstructionsResponse:
        return ExecuteSigningInstructionsResponse.from_json_dict(
            await self.fetch("execute_signing_instructions", args.to_json_dict())
        )

    async def split_coins(
        self,
        args: SplitCoins,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> SplitCoinsResponse:
        return SplitCoinsResponse.from_json_dict(
            await self.fetch(
                "split_coins", args.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )

    async def combine_coins(
        self,
        args: CombineCoins,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> CombineCoinsResponse:
        return CombineCoinsResponse.from_json_dict(
            await self.fetch(
                "combine_coins", args.json_serialize_for_transport(tx_config, extra_conditions, timelock_info)
            )
        )
