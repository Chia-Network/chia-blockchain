from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Optional, Union, cast

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia.data_layer.data_layer_util import DLProof, VerifyProofResponse
from chia.rpc.rpc_client import RpcClient
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.coin_record import CoinRecord
from chia.wallet.conditions import Condition, ConditionValidTimes, conditions_to_json_dicts
from chia.wallet.puzzles.clawback.metadata import AutoClaimSettings
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.offer import Offer
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.transaction_sorting import SortKey
from chia.wallet.util.clvm_streamable import json_deserialize_with_clvm_streamable
from chia.wallet.util.query_filter import TransactionTypeFilter
from chia.wallet.util.tx_config import CoinSelectionConfig, TXConfig
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_coin_store import GetCoinRecords
from chia.wallet.wallet_request_types import (
    AddKey,
    AddKeyResponse,
    ApplySignatures,
    ApplySignaturesResponse,
    CancelOfferResponse,
    CancelOffersResponse,
    CATSpendResponse,
    CheckDeleteKey,
    CheckDeleteKeyResponse,
    CombineCoins,
    CombineCoinsResponse,
    CreateNewDL,
    CreateNewDLResponse,
    CreateOfferForIDsResponse,
    CreateSignedTransactionsResponse,
    DeleteKey,
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
    DIDGetRecoveryInfo,
    DIDGetRecoveryInfoResponse,
    DIDGetRecoveryList,
    DIDGetRecoveryListResponse,
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
    DIDUpdateRecoveryIDs,
    DIDUpdateRecoveryIDsResponse,
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
    GatherSigningInfo,
    GatherSigningInfoResponse,
    GenerateMnemonicResponse,
    GetCATListResponse,
    GetHeightInfoResponse,
    GetLoggedInFingerprintResponse,
    GetNotifications,
    GetNotificationsResponse,
    GetOffersCountResponse,
    GetPrivateKey,
    GetPrivateKeyResponse,
    GetPublicKeysResponse,
    GetSyncStatusResponse,
    GetTimestampForHeight,
    GetTimestampForHeightResponse,
    GetTransactionMemo,
    GetTransactionMemoResponse,
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
    SendTransactionMultiResponse,
    SendTransactionResponse,
    SetWalletResyncOnStartup,
    SplitCoins,
    SplitCoinsResponse,
    SubmitTransactions,
    SubmitTransactionsResponse,
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
    result["transactions"] = [TransactionRecord.from_json_dict_convenience(tx) for tx in result["transactions"]]
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
    async def get_wallets(self, wallet_type: Optional[WalletType] = None) -> list[dict[str, Any]]:
        if wallet_type is None:
            request = {}
        else:
            request = {"type": wallet_type}
        response = await self.fetch("get_wallets", request)
        # TODO: casting due to lack of type checked deserialization
        return cast(list[dict[str, Any]], response["wallets"])

    # Wallet APIs
    async def get_wallet_balance(self, wallet_id: int) -> dict[str, Any]:
        request = {"wallet_id": wallet_id}
        response = await self.fetch("get_wallet_balance", request)
        # TODO: casting due to lack of type checked deserialization
        return cast(dict[str, Any], response["wallet_balance"])

    async def get_wallet_balances(self, wallet_ids: Optional[list[int]] = None) -> dict[str, dict[str, Any]]:
        request = {"wallet_ids": wallet_ids}
        response = await self.fetch("get_wallet_balances", request)
        # TODO: casting due to lack of type checked deserialization
        return cast(dict[str, dict[str, Any]], response["wallet_balances"])

    async def get_transaction(self, transaction_id: bytes32) -> TransactionRecord:
        request = {"transaction_id": transaction_id.hex()}
        response = await self.fetch("get_transaction", request)
        return TransactionRecord.from_json_dict_convenience(response["transaction"])

    async def get_transactions(
        self,
        wallet_id: int,
        start: Optional[int] = None,
        end: Optional[int] = None,
        sort_key: Optional[SortKey] = None,
        reverse: bool = False,
        to_address: Optional[str] = None,
        type_filter: Optional[TransactionTypeFilter] = None,
        confirmed: Optional[bool] = None,
    ) -> list[TransactionRecord]:
        request: dict[str, Any] = {"wallet_id": wallet_id}

        if start is not None:
            request["start"] = start
        if end is not None:
            request["end"] = end
        if sort_key is not None:
            request["sort_key"] = sort_key.name
        request["reverse"] = reverse

        if to_address is not None:
            request["to_address"] = to_address

        if type_filter is not None:
            request["type_filter"] = type_filter.to_json_dict()

        if confirmed is not None:
            request["confirmed"] = confirmed

        res = await self.fetch("get_transactions", request)
        return [TransactionRecord.from_json_dict_convenience(tx) for tx in res["transactions"]]

    async def get_transaction_count(
        self, wallet_id: int, confirmed: Optional[bool] = None, type_filter: Optional[TransactionTypeFilter] = None
    ) -> int:
        request: dict[str, Any] = {"wallet_id": wallet_id}
        if type_filter is not None:
            request["type_filter"] = type_filter.to_json_dict()
        if confirmed is not None:
            request["confirmed"] = confirmed
        res = await self.fetch("get_transaction_count", request)
        # TODO: casting due to lack of type checked deserialization
        return cast(int, res["count"])

    async def get_next_address(self, wallet_id: int, new_address: bool) -> str:
        request = {"wallet_id": wallet_id, "new_address": new_address}
        response = await self.fetch("get_next_address", request)
        # TODO: casting due to lack of type checked deserialization
        return cast(str, response["address"])

    async def send_transaction(
        self,
        wallet_id: int,
        amount: uint64,
        address: str,
        tx_config: TXConfig,
        fee: uint64 = uint64(0),
        memos: Optional[list[str]] = None,
        puzzle_decorator_override: Optional[list[dict[str, Union[str, int, bool]]]] = None,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
        push: bool = True,
    ) -> SendTransactionResponse:
        request = {
            "wallet_id": wallet_id,
            "amount": amount,
            "address": address,
            "fee": fee,
            "puzzle_decorator": puzzle_decorator_override,
            "extra_conditions": conditions_to_json_dicts(extra_conditions),
            "push": push,
            **tx_config.to_json_dict(),
            **timelock_info.to_json_dict(),
        }
        if memos is not None:
            request["memos"] = memos
        response = await self.fetch("send_transaction", request)
        return json_deserialize_with_clvm_streamable(response, SendTransactionResponse)

    async def send_transaction_multi(
        self,
        wallet_id: int,
        additions: list[dict[str, Any]],
        tx_config: TXConfig,
        coins: Optional[list[Coin]] = None,
        fee: uint64 = uint64(0),
        push: bool = True,
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> SendTransactionMultiResponse:
        # Converts bytes to hex for puzzle hashes
        additions_hex = []
        for ad in additions:
            additions_hex.append({"amount": ad["amount"], "puzzle_hash": ad["puzzle_hash"].hex()})
            if "memos" in ad:
                additions_hex[-1]["memos"] = ad["memos"]
        request = {
            "wallet_id": wallet_id,
            "additions": additions_hex,
            "fee": fee,
            "push": push,
            **tx_config.to_json_dict(),
            **timelock_info.to_json_dict(),
        }
        if coins is not None and len(coins) > 0:
            coins_json = [c.to_json_dict() for c in coins]
            request["coins"] = coins_json
        response = await self.fetch("send_transaction_multi", request)
        return json_deserialize_with_clvm_streamable(response, SendTransactionMultiResponse)

    async def spend_clawback_coins(
        self,
        coin_ids: list[bytes32],
        fee: int = 0,
        force: bool = False,
        push: bool = True,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> dict[str, Any]:
        request = {
            "coin_ids": [cid.hex() for cid in coin_ids],
            "fee": fee,
            "force": force,
            "extra_conditions": conditions_to_json_dicts(extra_conditions),
            "push": push,
            **timelock_info.to_json_dict(),
        }
        response = await self.fetch("spend_clawback_coins", request)
        return response

    async def delete_unconfirmed_transactions(self, wallet_id: int) -> None:
        await self.fetch("delete_unconfirmed_transactions", {"wallet_id": wallet_id})

    async def get_current_derivation_index(self) -> str:
        response = await self.fetch("get_current_derivation_index", {})
        index = response["index"]
        return str(index)

    async def extend_derivation_index(self, index: int) -> str:
        response = await self.fetch("extend_derivation_index", {"index": index})
        updated_index = response["index"]
        return str(updated_index)

    async def get_farmed_amount(self) -> dict[str, Any]:
        return await self.fetch("get_farmed_amount", {})

    async def create_signed_transactions(
        self,
        additions: list[dict[str, Any]],
        tx_config: TXConfig,
        coins: Optional[list[Coin]] = None,
        fee: uint64 = uint64(0),
        wallet_id: Optional[int] = None,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
        push: bool = False,
    ) -> CreateSignedTransactionsResponse:
        # Converts bytes to hex for puzzle hashes
        additions_hex = []
        for ad in additions:
            additions_hex.append({"amount": ad["amount"], "puzzle_hash": ad["puzzle_hash"].hex()})
            if "memos" in ad:
                additions_hex[-1]["memos"] = ad["memos"]

        request = {
            "additions": additions_hex,
            "fee": fee,
            "extra_conditions": conditions_to_json_dicts(extra_conditions),
            "push": push,
            **tx_config.to_json_dict(),
            **timelock_info.to_json_dict(),
        }

        if coins is not None and len(coins) > 0:
            coins_json = [c.to_json_dict() for c in coins]
            request["coins"] = coins_json

        if wallet_id:
            request["wallet_id"] = wallet_id

        response = await self.fetch("create_signed_transaction", request)
        return json_deserialize_with_clvm_streamable(response, CreateSignedTransactionsResponse)

    async def select_coins(self, amount: int, wallet_id: int, coin_selection_config: CoinSelectionConfig) -> list[Coin]:
        request = {"amount": amount, "wallet_id": wallet_id, **coin_selection_config.to_json_dict()}
        response = await self.fetch("select_coins", request)
        return [Coin.from_json_dict(coin) for coin in response["coins"]]

    async def get_coin_records(self, request: GetCoinRecords) -> dict[str, Any]:
        return await self.fetch("get_coin_records", request.to_json_dict())

    async def get_spendable_coins(
        self, wallet_id: int, coin_selection_config: CoinSelectionConfig
    ) -> tuple[list[CoinRecord], list[CoinRecord], list[Coin]]:
        """
        We return a tuple containing: (confirmed records, unconfirmed removals, unconfirmed additions)
        """
        request = {"wallet_id": wallet_id, **coin_selection_config.to_json_dict()}
        response = await self.fetch("get_spendable_coins", request)
        confirmed_wrs = [CoinRecord.from_json_dict(coin) for coin in response["confirmed_records"]]
        unconfirmed_removals = [CoinRecord.from_json_dict(coin) for coin in response["unconfirmed_removals"]]
        unconfirmed_additions = [Coin.from_json_dict(coin) for coin in response["unconfirmed_additions"]]
        return confirmed_wrs, unconfirmed_removals, unconfirmed_additions

    async def get_coin_records_by_names(
        self,
        names: list[bytes32],
        include_spent_coins: bool = True,
        start_height: Optional[int] = None,
        end_height: Optional[int] = None,
    ) -> list[CoinRecord]:
        names_hex = [name.hex() for name in names]
        request = {"names": names_hex, "include_spent_coins": include_spent_coins}
        if start_height is not None:
            request["start_height"] = start_height
        if end_height is not None:
            request["end_height"] = end_height

        response = await self.fetch("get_coin_records_by_names", request)
        return [CoinRecord.from_json_dict(cr) for cr in response["coin_records"]]

    # DID wallet
    async def create_new_did_wallet(
        self,
        amount: int,
        tx_config: TXConfig,
        fee: int = 0,
        name: Optional[str] = "DID Wallet",
        backup_ids: list[str] = [],
        required_num: int = 0,
        type: str = "new",
        backup_data: str = "",
        push: bool = True,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> dict[str, Any]:
        request = {
            "wallet_type": "did_wallet",
            "did_type": type,
            "backup_dids": backup_ids,
            "num_of_backup_ids_needed": required_num,
            "amount": amount,
            "fee": fee,
            "wallet_name": name,
            "push": push,
            "backup_data": backup_data,
            "extra_conditions": conditions_to_json_dicts(extra_conditions),
            **tx_config.to_json_dict(),
            **timelock_info.to_json_dict(),
        }
        response = await self.fetch("create_new_wallet", request)
        return response

    async def get_did_id(self, request: DIDGetDID) -> DIDGetDIDResponse:
        return DIDGetDIDResponse.from_json_dict(await self.fetch("did_get_did", request.to_json_dict()))

    async def get_did_info(self, request: DIDGetInfo) -> DIDGetInfoResponse:
        return DIDGetInfoResponse.from_json_dict(await self.fetch("did_get_info", request.to_json_dict()))

    async def create_did_backup_file(self, request: DIDCreateBackupFile) -> DIDCreateBackupFileResponse:
        return DIDCreateBackupFileResponse.from_json_dict(
            await self.fetch("did_create_backup_file", request.to_json_dict())
        )

    async def update_did_recovery_list(
        self,
        request: DIDUpdateRecoveryIDs,
        tx_config: TXConfig,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> DIDUpdateRecoveryIDsResponse:
        return DIDUpdateRecoveryIDsResponse.from_json_dict(
            await self.fetch(
                "did_update_recovery_ids",
                request.json_serialize_for_transport(tx_config, extra_conditions, timelock_info),
            )
        )

    async def get_did_recovery_list(self, request: DIDGetRecoveryList) -> DIDGetRecoveryListResponse:
        return DIDGetRecoveryListResponse.from_json_dict(
            await self.fetch("did_get_recovery_list", request.to_json_dict())
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

    async def did_create_attest(
        self,
        wallet_id: int,
        coin_name: str,
        pubkey: str,
        puzhash: str,
        file_name: str,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> dict[str, Any]:
        request = {
            "wallet_id": wallet_id,
            "coin_name": coin_name,
            "pubkey": pubkey,
            "puzhash": puzhash,
            "filename": file_name,
            "extra_conditions": conditions_to_json_dicts(extra_conditions),
            **timelock_info.to_json_dict(),
        }
        response = await self.fetch("did_create_attest", request)
        return response

    async def did_get_recovery_info(self, request: DIDGetRecoveryInfo) -> DIDGetRecoveryInfoResponse:
        return DIDGetRecoveryInfoResponse.from_json_dict(
            await self.fetch("did_get_information_needed_for_recovery", request.to_json_dict())
        )

    async def did_get_current_coin_info(self, request: DIDGetCurrentCoinInfo) -> DIDGetCurrentCoinInfoResponse:
        return DIDGetCurrentCoinInfoResponse.from_json_dict(
            await self.fetch("did_get_current_coin_info", request.to_json_dict())
        )

    async def did_recovery_spend(self, wallet_id: int, attest_filenames: str) -> dict[str, Any]:
        request = {"wallet_id": wallet_id, "attest_filenames": attest_filenames}
        response = await self.fetch("did_recovery_spend", request)
        return response

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

    # TODO: test all invocations of create_new_pool_wallet with new fee arg.
    async def create_new_pool_wallet(
        self,
        target_puzzlehash: Optional[bytes32],
        pool_url: Optional[str],
        relative_lock_height: uint32,
        backup_host: str,
        mode: str,
        state: str,
        fee: uint64,
        p2_singleton_delay_time: Optional[uint64] = None,
        p2_singleton_delayed_ph: Optional[bytes32] = None,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> TransactionRecord:
        request = {
            "wallet_type": "pool_wallet",
            "mode": mode,
            "initial_target_state": {
                "target_puzzle_hash": target_puzzlehash.hex() if target_puzzlehash else None,
                "relative_lock_height": relative_lock_height,
                "pool_url": pool_url,
                "state": state,
            },
            "fee": fee,
            "extra_conditions": conditions_to_json_dicts(extra_conditions),
            **timelock_info.to_json_dict(),
        }
        if p2_singleton_delay_time is not None:
            request["p2_singleton_delay_time"] = p2_singleton_delay_time
        if p2_singleton_delayed_ph is not None:
            request["p2_singleton_delayed_ph"] = p2_singleton_delayed_ph.hex()
        res = await self.fetch("create_new_wallet", request)
        return TransactionRecord.from_json_dict(res["transaction"])

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
    async def create_new_cat_and_wallet(
        self, amount: uint64, fee: uint64 = uint64(0), test: bool = False
    ) -> dict[str, Any]:
        request = {"wallet_type": "cat_wallet", "mode": "new", "amount": amount, "fee": fee, "test": test}
        return await self.fetch("create_new_wallet", request)

    async def create_wallet_for_existing_cat(self, asset_id: bytes) -> dict[str, Any]:
        request = {"wallet_type": "cat_wallet", "asset_id": asset_id.hex(), "mode": "existing"}
        return await self.fetch("create_new_wallet", request)

    async def get_cat_asset_id(self, wallet_id: int) -> bytes32:
        request = {"wallet_id": wallet_id}
        return bytes32.from_hexstr((await self.fetch("cat_get_asset_id", request))["asset_id"])

    async def get_stray_cats(self) -> list[dict[str, Any]]:
        response = await self.fetch("get_stray_cats", {})
        # TODO: casting due to lack of type checked deserialization
        return cast(list[dict[str, Any]], response["stray_cats"])

    async def cat_asset_id_to_name(self, asset_id: bytes32) -> Optional[tuple[Optional[uint32], str]]:
        request = {"asset_id": asset_id.hex()}
        try:
            res = await self.fetch("cat_asset_id_to_name", request)
        except ValueError:
            return None

        wallet_id: Optional[uint32] = None if res["wallet_id"] is None else uint32(int(res["wallet_id"]))
        return wallet_id, res["name"]

    async def get_cat_name(self, wallet_id: int) -> str:
        request = {"wallet_id": wallet_id}
        response = await self.fetch("cat_get_name", request)
        # TODO: casting due to lack of type checked deserialization
        return cast(str, response["name"])

    async def set_cat_name(self, wallet_id: int, name: str) -> None:
        request: dict[str, Any] = {
            "wallet_id": wallet_id,
            "name": name,
        }
        await self.fetch("cat_set_name", request)

    async def cat_spend(
        self,
        wallet_id: int,
        tx_config: TXConfig,
        amount: Optional[uint64] = None,
        inner_address: Optional[str] = None,
        fee: uint64 = uint64(0),
        memos: Optional[list[str]] = None,
        additions: Optional[list[dict[str, Any]]] = None,
        removals: Optional[list[Coin]] = None,
        cat_discrepancy: Optional[tuple[int, Program, Program]] = None,  # (extra_delta, tail_reveal, tail_solution)
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
        push: bool = True,
    ) -> CATSpendResponse:
        send_dict: dict[str, Any] = {
            "wallet_id": wallet_id,
            "fee": fee,
            "memos": memos if memos is not None else [],
            "extra_conditions": conditions_to_json_dicts(extra_conditions),
            "push": push,
            **tx_config.to_json_dict(),
            **timelock_info.to_json_dict(),
        }
        if amount is not None and inner_address is not None:
            send_dict["amount"] = amount
            send_dict["inner_address"] = inner_address
        elif additions is not None:
            additions_hex = []
            for ad in additions:
                additions_hex.append({"amount": ad["amount"], "puzzle_hash": ad["puzzle_hash"].hex()})
                if "memos" in ad:
                    additions_hex[-1]["memos"] = ad["memos"]
            send_dict["additions"] = additions_hex
        else:
            raise ValueError("Must specify either amount and inner_address or additions")
        if removals is not None and len(removals) > 0:
            send_dict["coins"] = [c.to_json_dict() for c in removals]
        if cat_discrepancy is not None:
            send_dict["extra_delta"] = cat_discrepancy[0]
            send_dict["tail_reveal"] = bytes(cat_discrepancy[1]).hex()
            send_dict["tail_solution"] = bytes(cat_discrepancy[2]).hex()
        res = await self.fetch("cat_spend", send_dict)
        return json_deserialize_with_clvm_streamable(res, CATSpendResponse)

    # Offers
    async def create_offer_for_ids(
        self,
        offer_dict: dict[Union[uint32, str], int],
        tx_config: TXConfig,
        driver_dict: Optional[dict[str, Any]] = None,
        solver: Optional[dict[str, Any]] = None,
        fee: int = 0,
        validate_only: bool = False,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> CreateOfferForIDsResponse:
        send_dict: dict[str, int] = {str(key): value for key, value in offer_dict.items()}

        req = {
            "offer": send_dict,
            "validate_only": validate_only,
            "fee": fee,
            "extra_conditions": conditions_to_json_dicts(extra_conditions),
            **tx_config.to_json_dict(),
            **timelock_info.to_json_dict(),
        }
        if driver_dict is not None:
            req["driver_dict"] = driver_dict
        if solver is not None:
            req["solver"] = solver
        res = await self.fetch("create_offer_for_ids", req)
        return json_deserialize_with_clvm_streamable(res, CreateOfferForIDsResponse)

    async def get_offer_summary(
        self, offer: Offer, advanced: bool = False
    ) -> tuple[bytes32, dict[str, dict[str, int]]]:
        res = await self.fetch("get_offer_summary", {"offer": offer.to_bech32(), "advanced": advanced})
        return bytes32.from_hexstr(res["id"]), res["summary"]

    async def check_offer_validity(self, offer: Offer) -> tuple[bytes32, bool]:
        res = await self.fetch("check_offer_validity", {"offer": offer.to_bech32()})
        return bytes32.from_hexstr(res["id"]), res["valid"]

    async def take_offer(
        self,
        offer: Offer,
        tx_config: TXConfig,
        solver: Optional[dict[str, Any]] = None,
        fee: int = 0,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
        push: bool = True,
    ) -> TakeOfferResponse:
        req = {
            "offer": offer.to_bech32(),
            "fee": fee,
            "extra_conditions": conditions_to_json_dicts(extra_conditions),
            "push": push,
            **tx_config.to_json_dict(),
            **timelock_info.to_json_dict(),
        }
        if solver is not None:
            req["solver"] = solver
        res = await self.fetch("take_offer", req)
        return json_deserialize_with_clvm_streamable(res, TakeOfferResponse)

    async def get_offer(self, trade_id: bytes32, file_contents: bool = False) -> TradeRecord:
        res = await self.fetch("get_offer", {"trade_id": trade_id.hex(), "file_contents": file_contents})
        offer_str = bytes(Offer.from_bech32(res["offer"])).hex() if file_contents else ""
        return TradeRecord.from_json_dict_convenience(res["trade_record"], offer_str)

    async def get_all_offers(
        self,
        start: int = 0,
        end: int = 50,
        sort_key: Optional[str] = None,
        reverse: bool = False,
        file_contents: bool = False,
        exclude_my_offers: bool = False,
        exclude_taken_offers: bool = False,
        include_completed: bool = False,
    ) -> list[TradeRecord]:
        res = await self.fetch(
            "get_all_offers",
            {
                "start": start,
                "end": end,
                "sort_key": sort_key,
                "reverse": reverse,
                "file_contents": file_contents,
                "exclude_my_offers": exclude_my_offers,
                "exclude_taken_offers": exclude_taken_offers,
                "include_completed": include_completed,
            },
        )

        records = []
        if file_contents:
            optional_offers = [bytes(Offer.from_bech32(o)).hex() for o in res["offers"]]
        else:
            optional_offers = [""] * len(res["trade_records"])
        for record, offer in zip(res["trade_records"], optional_offers):
            records.append(TradeRecord.from_json_dict_convenience(record, offer))

        return records

    async def get_offers_count(self) -> GetOffersCountResponse:
        return GetOffersCountResponse.from_json_dict(await self.fetch("get_offers_count", {}))

    async def cancel_offer(
        self,
        trade_id: bytes32,
        tx_config: TXConfig,
        fee: int = 0,
        secure: bool = True,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
        push: bool = True,
    ) -> CancelOfferResponse:
        res = await self.fetch(
            "cancel_offer",
            {
                "trade_id": trade_id.hex(),
                "secure": secure,
                "fee": fee,
                "extra_conditions": conditions_to_json_dicts(extra_conditions),
                "push": push,
                **tx_config.to_json_dict(),
                **timelock_info.to_json_dict(),
            },
        )

        return json_deserialize_with_clvm_streamable(res, CancelOfferResponse)

    async def cancel_offers(
        self,
        tx_config: TXConfig,
        batch_fee: int = 0,
        secure: bool = True,
        batch_size: int = 5,
        cancel_all: bool = False,
        asset_id: Optional[bytes32] = None,
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
        push: bool = True,
    ) -> CancelOffersResponse:
        res = await self.fetch(
            "cancel_offers",
            {
                "secure": secure,
                "batch_fee": batch_fee,
                "batch_size": batch_size,
                "cancel_all": cancel_all,
                "asset_id": None if asset_id is None else asset_id.hex(),
                "extra_conditions": conditions_to_json_dicts(extra_conditions),
                "push": push,
                **tx_config.to_json_dict(),
                **timelock_info.to_json_dict(),
            },
        )

        return json_deserialize_with_clvm_streamable(res, CancelOffersResponse)

    async def get_cat_list(self) -> GetCATListResponse:
        return GetCATListResponse.from_json_dict(await self.fetch("get_cat_list", {}))

    # NFT wallet
    async def create_new_nft_wallet(self, did_id: Optional[str], name: Optional[str] = None) -> dict[str, Any]:
        request = {"wallet_type": "nft_wallet", "did_id": did_id, "name": name}
        response = await self.fetch("create_new_wallet", request)
        return response

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

    async def delete_notifications(self, ids: Optional[Sequence[bytes32]] = None) -> bool:
        request = {}
        if ids is not None:
            request["ids"] = [id.hex() for id in ids]
        response = await self.fetch("delete_notifications", request)
        # TODO: casting due to lack of type checked deserialization
        result = cast(bool, response["success"])
        return result

    async def send_notification(
        self,
        target: bytes32,
        msg: bytes,
        amount: uint64,
        fee: uint64 = uint64(0),
        extra_conditions: tuple[Condition, ...] = tuple(),
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
        push: bool = True,
    ) -> TransactionRecord:
        response = await self.fetch(
            "send_notification",
            {
                "target": target.hex(),
                "message": msg.hex(),
                "amount": amount,
                "fee": fee,
                "extra_conditions": conditions_to_json_dicts(extra_conditions),
                "push": push,
                **timelock_info.to_json_dict(),
            },
        )
        return TransactionRecord.from_json_dict_convenience(response["tx"])

    async def sign_message_by_address(self, address: str, message: str) -> tuple[str, str, str]:
        response = await self.fetch("sign_message_by_address", {"address": address, "message": message})
        return response["pubkey"], response["signature"], response["signing_mode"]

    async def sign_message_by_id(
        self, id: str, message: str, is_hex: bool = False, safe_mode: bool = True
    ) -> tuple[str, str, str]:
        response = await self.fetch(
            "sign_message_by_id", {"id": id, "message": message, "is_hex": is_hex, "safe_mode": safe_mode}
        )
        return response["pubkey"], response["signature"], response["signing_mode"]

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
        return [TransactionRecord.from_json_dict_convenience(tx) for tx in response["transactions"]]

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
