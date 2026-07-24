from chia.data_layer.data_layer_util import DLProof, VerifyProofResponse
from chia.rpc.rpc_client import RpcClient
from chia.wallet import wallet_request_types
from chia.wallet.conditions import Condition, ConditionValidTimes
from chia.wallet.puzzles.clawback.metadata import AutoClaimSettings
from chia.wallet.util.tx_config import TXConfig

def client_method_name(endpoint_name: str) -> str: ...

class WalletRpcClient(RpcClient):
    async def log_in(
        self,
        request: wallet_request_types.LogIn,
    ) -> wallet_request_types.LogInResponse: ...
    async def get_logged_in_fingerprint(self) -> wallet_request_types.GetLoggedInFingerprintResponse: ...
    async def get_public_keys(self) -> wallet_request_types.GetPublicKeysResponse: ...
    async def get_private_key(
        self,
        request: wallet_request_types.GetPrivateKey,
    ) -> wallet_request_types.GetPrivateKeyResponse: ...
    async def generate_mnemonic(self) -> wallet_request_types.GenerateMnemonicResponse: ...
    async def add_key(
        self,
        request: wallet_request_types.AddKey,
    ) -> wallet_request_types.AddKeyResponse: ...
    async def delete_key(
        self,
        request: wallet_request_types.DeleteKey,
    ) -> None: ...
    async def check_delete_key(
        self,
        request: wallet_request_types.CheckDeleteKey,
    ) -> wallet_request_types.CheckDeleteKeyResponse: ...
    async def delete_all_keys(self) -> None: ...
    async def set_wallet_resync_on_startup(
        self,
        request: wallet_request_types.SetWalletResyncOnStartup,
    ) -> None: ...
    async def get_sync_status(self) -> wallet_request_types.GetSyncStatusResponse: ...
    async def get_full_node_peer_count(self) -> wallet_request_types.GetFullNodePeerCountResponse: ...
    async def get_height_info(
        self,
        request: wallet_request_types.GetHeightInfo,
    ) -> wallet_request_types.GetHeightInfoResponse: ...
    async def push_tx(
        self,
        request: wallet_request_types.PushTX,
    ) -> None: ...
    async def push_transactions(
        self,
        request: wallet_request_types.PushTransactions,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.PushTransactionsResponse: ...
    async def get_timestamp_for_height(
        self,
        request: wallet_request_types.GetTimestampForHeight,
    ) -> wallet_request_types.GetTimestampForHeightResponse: ...
    async def get_fee_estimate(self) -> wallet_request_types.GetFeeEstimateResponse: ...
    async def set_auto_claim(
        self,
        request: AutoClaimSettings,
    ) -> AutoClaimSettings: ...
    async def get_auto_claim(self) -> AutoClaimSettings: ...
    async def get_wallets(
        self,
        request: wallet_request_types.GetWallets,
    ) -> wallet_request_types.GetWalletsResponse: ...
    async def create_new_wallet(
        self,
        request: wallet_request_types.CreateNewWallet,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.CreateNewWalletResponse: ...
    async def get_wallet_balance(
        self,
        request: wallet_request_types.GetWalletBalance,
    ) -> wallet_request_types.GetWalletBalanceResponse: ...
    async def get_wallet_balances(
        self,
        request: wallet_request_types.GetWalletBalances,
    ) -> wallet_request_types.GetWalletBalancesResponse: ...
    async def get_transaction(
        self,
        request: wallet_request_types.GetTransaction,
    ) -> wallet_request_types.GetTransactionResponse: ...
    async def get_transactions(
        self,
        request: wallet_request_types.GetTransactions,
    ) -> wallet_request_types.GetTransactionsResponse: ...
    async def get_transaction_count(
        self,
        request: wallet_request_types.GetTransactionCount,
    ) -> wallet_request_types.GetTransactionCountResponse: ...
    async def get_next_address(
        self,
        request: wallet_request_types.GetNextAddress,
    ) -> wallet_request_types.GetNextAddressResponse: ...
    async def send_transaction(
        self,
        request: wallet_request_types.SendTransaction,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.SendTransactionResponse: ...
    async def send_transaction_multi(
        self,
        request: wallet_request_types.SendTransactionMulti,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.SendTransactionMultiResponse: ...
    async def spend_clawback_coins(
        self,
        request: wallet_request_types.SpendClawbackCoins,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.SpendClawbackCoinsResponse: ...
    async def get_farmed_amount(
        self,
        request: wallet_request_types.GetFarmedAmount,
    ) -> wallet_request_types.GetFarmedAmountResponse: ...
    async def create_signed_transactions(
        self,
        request: wallet_request_types.CreateSignedTransaction,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.CreateSignedTransactionsResponse: ...
    async def delete_unconfirmed_transactions(
        self,
        request: wallet_request_types.DeleteUnconfirmedTransactions,
    ) -> None: ...
    async def select_coins(
        self,
        request: wallet_request_types.SelectCoins,
    ) -> wallet_request_types.SelectCoinsResponse: ...
    async def get_spendable_coins(
        self,
        request: wallet_request_types.GetSpendableCoins,
    ) -> wallet_request_types.GetSpendableCoinsResponse: ...
    async def get_coin_records_by_names(
        self,
        request: wallet_request_types.GetCoinRecordsByNames,
    ) -> wallet_request_types.GetCoinRecordsByNamesResponse: ...
    async def get_puzzle_and_solution(
        self,
        request: wallet_request_types.GetPuzzleAndSolution,
    ) -> wallet_request_types.GetPuzzleAndSolutionResponse: ...
    async def get_current_derivation_index(self) -> wallet_request_types.GetCurrentDerivationIndexResponse: ...
    async def extend_derivation_index(
        self,
        request: wallet_request_types.ExtendDerivationIndex,
    ) -> wallet_request_types.ExtendDerivationIndexResponse: ...
    async def get_notifications(
        self,
        request: wallet_request_types.GetNotifications,
    ) -> wallet_request_types.GetNotificationsResponse: ...
    async def delete_notifications(
        self,
        request: wallet_request_types.DeleteNotifications,
    ) -> None: ...
    async def send_notification(
        self,
        request: wallet_request_types.SendNotification,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.SendNotificationResponse: ...
    async def sign_message_by_address(
        self,
        request: wallet_request_types.SignMessageByAddress,
    ) -> wallet_request_types.SignMessageByAddressResponse: ...
    async def sign_message_by_id(
        self,
        request: wallet_request_types.SignMessageByID,
    ) -> wallet_request_types.SignMessageByIDResponse: ...
    async def verify_signature(
        self,
        request: wallet_request_types.VerifySignature,
    ) -> wallet_request_types.VerifySignatureResponse: ...
    async def get_transaction_memo(
        self,
        request: wallet_request_types.GetTransactionMemo,
    ) -> wallet_request_types.GetTransactionMemoResponse: ...
    async def split_coins(
        self,
        request: wallet_request_types.SplitCoins,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.SplitCoinsResponse: ...
    async def combine_coins(
        self,
        request: wallet_request_types.CombineCoins,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.CombineCoinsResponse: ...
    async def set_cat_name(
        self,
        request: wallet_request_types.CATSetName,
    ) -> wallet_request_types.CATSetNameResponse: ...
    async def cat_asset_id_to_name(
        self,
        request: wallet_request_types.CATAssetIDToName,
    ) -> wallet_request_types.CATAssetIDToNameResponse: ...
    async def get_cat_name(
        self,
        request: wallet_request_types.CATGetName,
    ) -> wallet_request_types.CATGetNameResponse: ...
    async def get_stray_cats(self) -> wallet_request_types.GetStrayCATsResponse: ...
    async def cat_spend(
        self,
        request: wallet_request_types.CATSpend,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.CATSpendResponse: ...
    async def get_cat_asset_id(
        self,
        request: wallet_request_types.CATGetAssetID,
    ) -> wallet_request_types.CATGetAssetIDResponse: ...
    async def create_offer_for_ids(
        self,
        request: wallet_request_types.CreateOfferForIDs,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.CreateOfferForIDsResponse: ...
    async def get_offer_summary(
        self,
        request: wallet_request_types.GetOfferSummary,
    ) -> wallet_request_types.GetOfferSummaryResponse: ...
    async def check_offer_validity(
        self,
        request: wallet_request_types.CheckOfferValidity,
    ) -> wallet_request_types.CheckOfferValidityResponse: ...
    async def take_offer(
        self,
        request: wallet_request_types.TakeOffer,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.TakeOfferResponse: ...
    async def get_offer(
        self,
        request: wallet_request_types.GetOffer,
    ) -> wallet_request_types.GetOfferResponse: ...
    async def get_all_offers(
        self,
        request: wallet_request_types.GetAllOffers,
    ) -> wallet_request_types.GetAllOffersResponse: ...
    async def get_offers_count(self) -> wallet_request_types.GetOffersCountResponse: ...
    async def cancel_offer(
        self,
        request: wallet_request_types.CancelOffer,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.CancelOfferResponse: ...
    async def cancel_offers(
        self,
        request: wallet_request_types.CancelOffers,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.CancelOffersResponse: ...
    async def get_cat_list(self) -> wallet_request_types.GetCATListResponse: ...
    async def did_set_wallet_name(
        self,
        request: wallet_request_types.DIDSetWalletName,
    ) -> wallet_request_types.DIDSetWalletNameResponse: ...
    async def did_get_wallet_name(
        self,
        request: wallet_request_types.DIDGetWalletName,
    ) -> wallet_request_types.DIDGetWalletNameResponse: ...
    async def update_did_metadata(
        self,
        request: wallet_request_types.DIDUpdateMetadata,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.DIDUpdateMetadataResponse: ...
    async def get_did_pubkey(
        self,
        request: wallet_request_types.DIDGetPubkey,
    ) -> wallet_request_types.DIDGetPubkeyResponse: ...
    async def get_did_id(
        self,
        request: wallet_request_types.DIDGetDID,
    ) -> wallet_request_types.DIDGetDIDResponse: ...
    async def get_did_metadata(
        self,
        request: wallet_request_types.DIDGetMetadata,
    ) -> wallet_request_types.DIDGetMetadataResponse: ...
    async def did_get_current_coin_info(
        self,
        request: wallet_request_types.DIDGetCurrentCoinInfo,
    ) -> wallet_request_types.DIDGetCurrentCoinInfoResponse: ...
    async def create_did_backup_file(
        self,
        request: wallet_request_types.DIDCreateBackupFile,
    ) -> wallet_request_types.DIDCreateBackupFileResponse: ...
    async def did_transfer_did(
        self,
        request: wallet_request_types.DIDTransferDID,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.DIDTransferDIDResponse: ...
    async def did_message_spend(
        self,
        request: wallet_request_types.DIDMessageSpend,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.DIDMessageSpendResponse: ...
    async def get_did_info(
        self,
        request: wallet_request_types.DIDGetInfo,
    ) -> wallet_request_types.DIDGetInfoResponse: ...
    async def find_lost_did(
        self,
        request: wallet_request_types.DIDFindLostDID,
    ) -> wallet_request_types.DIDFindLostDIDResponse: ...
    async def mint_nft(
        self,
        request: wallet_request_types.NFTMintNFTRequest,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.NFTMintNFTResponse: ...
    async def count_nfts(
        self,
        request: wallet_request_types.NFTCountNFTs,
    ) -> wallet_request_types.NFTCountNFTsResponse: ...
    async def list_nfts(
        self,
        request: wallet_request_types.NFTGetNFTs,
    ) -> wallet_request_types.NFTGetNFTsResponse: ...
    async def get_nft_wallet_by_did(
        self,
        request: wallet_request_types.NFTGetByDID,
    ) -> wallet_request_types.NFTGetByDIDResponse: ...
    async def set_nft_did(
        self,
        request: wallet_request_types.NFTSetNFTDID,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.NFTSetNFTDIDResponse: ...
    async def set_nft_status(
        self,
        request: wallet_request_types.NFTSetNFTStatus,
    ) -> None: ...
    async def get_nft_wallet_did(
        self,
        request: wallet_request_types.NFTGetWalletDID,
    ) -> wallet_request_types.NFTGetWalletDIDResponse: ...
    async def get_nft_wallets_with_dids(self) -> wallet_request_types.NFTGetWalletsWithDIDsResponse: ...
    async def get_nft_info(
        self,
        request: wallet_request_types.NFTGetInfo,
    ) -> wallet_request_types.NFTGetInfoResponse: ...
    async def transfer_nft(
        self,
        request: wallet_request_types.NFTTransferNFT,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.NFTTransferNFTResponse: ...
    async def add_uri_to_nft(
        self,
        request: wallet_request_types.NFTAddURI,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.NFTAddURIResponse: ...
    async def nft_calculate_royalties(
        self,
        request: wallet_request_types.NFTCalculateRoyalties,
    ) -> wallet_request_types.NFTCalculateRoyaltiesResponse: ...
    async def nft_mint_bulk(
        self,
        request: wallet_request_types.NFTMintBulk,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.NFTMintBulkResponse: ...
    async def set_nft_did_bulk(
        self,
        request: wallet_request_types.NFTSetDIDBulk,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.NFTSetDIDBulkResponse: ...
    async def transfer_nft_bulk(
        self,
        request: wallet_request_types.NFTTransferBulk,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.NFTTransferBulkResponse: ...
    async def register_remote_coins(
        self,
        request: wallet_request_types.RegisterRemoteCoins,
    ) -> None: ...
    async def get_coin_records(
        self,
        request: wallet_request_types.GetCoinRecords,
    ) -> wallet_request_types.GetCoinRecordsResponse: ...
    async def pw_join_pool(
        self,
        request: wallet_request_types.PWJoinPool,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.PWJoinPoolResponse: ...
    async def pw_self_pool(
        self,
        request: wallet_request_types.PWSelfPool,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.PWSelfPoolResponse: ...
    async def pw_absorb_rewards(
        self,
        request: wallet_request_types.PWAbsorbRewards,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.PWAbsorbRewardsResponse: ...
    async def pw_status(
        self,
        request: wallet_request_types.PWStatus,
    ) -> wallet_request_types.PWStatusResponse: ...
    async def create_new_dl(
        self,
        request: wallet_request_types.CreateNewDL,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.CreateNewDLResponse: ...
    async def dl_track_new(
        self,
        request: wallet_request_types.DLTrackNew,
    ) -> None: ...
    async def dl_stop_tracking(
        self,
        request: wallet_request_types.DLStopTracking,
    ) -> None: ...
    async def dl_latest_singleton(
        self,
        request: wallet_request_types.DLLatestSingleton,
    ) -> wallet_request_types.DLLatestSingletonResponse: ...
    async def dl_singletons_by_root(
        self,
        request: wallet_request_types.DLSingletonsByRoot,
    ) -> wallet_request_types.DLSingletonsByRootResponse: ...
    async def dl_update_root(
        self,
        request: wallet_request_types.DLUpdateRoot,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.DLUpdateRootResponse: ...
    async def dl_update_multiple(
        self,
        request: wallet_request_types.DLUpdateMultiple,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.DLUpdateMultipleResponse: ...
    async def dl_history(
        self,
        request: wallet_request_types.DLHistory,
    ) -> wallet_request_types.DLHistoryResponse: ...
    async def dl_owned_singletons(self) -> wallet_request_types.DLOwnedSingletonsResponse: ...
    async def dl_get_mirrors(
        self,
        request: wallet_request_types.DLGetMirrors,
    ) -> wallet_request_types.DLGetMirrorsResponse: ...
    async def dl_new_mirror(
        self,
        request: wallet_request_types.DLNewMirror,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.DLNewMirrorResponse: ...
    async def dl_delete_mirror(
        self,
        request: wallet_request_types.DLDeleteMirror,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.DLDeleteMirrorResponse: ...
    async def dl_verify_proof(
        self,
        request: DLProof,
    ) -> VerifyProofResponse: ...
    async def vc_mint(
        self,
        request: wallet_request_types.VCMint,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.VCMintResponse: ...
    async def vc_get(
        self,
        request: wallet_request_types.VCGet,
    ) -> wallet_request_types.VCGetResponse: ...
    async def vc_get_list(
        self,
        request: wallet_request_types.VCGetList,
    ) -> wallet_request_types.VCGetListResponse: ...
    async def vc_spend(
        self,
        request: wallet_request_types.VCSpend,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.VCSpendResponse: ...
    async def vc_add_proofs(
        self,
        request: wallet_request_types.VCAddProofs,
    ) -> None: ...
    async def vc_get_proofs_for_root(
        self,
        request: wallet_request_types.VCGetProofsForRoot,
    ) -> wallet_request_types.VCGetProofsForRootResponse: ...
    async def vc_revoke(
        self,
        request: wallet_request_types.VCRevoke,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.VCRevokeResponse: ...
    async def crcat_approve_pending(
        self,
        request: wallet_request_types.CRCATApprovePending,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = ...,
        timelock_info: ConditionValidTimes = ...,
    ) -> wallet_request_types.CRCATApprovePendingResponse: ...
    async def gather_signing_info(
        self,
        request: wallet_request_types.GatherSigningInfo,
    ) -> wallet_request_types.GatherSigningInfoResponse: ...
    async def apply_signatures(
        self,
        request: wallet_request_types.ApplySignatures,
    ) -> wallet_request_types.ApplySignaturesResponse: ...
    async def submit_transactions(
        self,
        request: wallet_request_types.SubmitTransactions,
    ) -> wallet_request_types.SubmitTransactionsResponse: ...
    async def execute_signing_instructions(
        self,
        request: wallet_request_types.ExecuteSigningInstructions,
    ) -> wallet_request_types.ExecuteSigningInstructionsResponse: ...
