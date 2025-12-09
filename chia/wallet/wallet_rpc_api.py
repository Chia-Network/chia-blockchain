from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Callable
from itertools import count
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, cast

from chia_rs import AugSchemeMPL, Coin, CoinRecord, CoinSpend, CoinState, G1Element, G2Element, PrivateKey
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16, uint32, uint64
from clvm_tools.binutils import assemble

from chia.consensus.block_rewards import calculate_base_farmer_reward
from chia.data_layer.data_layer_errors import LauncherCoinNotFoundError
from chia.data_layer.data_layer_util import DLProof, VerifyProofResponse, dl_verify_proof
from chia.data_layer.data_layer_wallet import DataLayerWallet, Mirror
from chia.pools.pool_wallet import PoolWallet
from chia.pools.pool_wallet_info import FARMING_TO_POOL, PoolState, PoolWalletInfo, create_pool_state
from chia.protocols.outbound_message import NodeType
from chia.rpc.rpc_server import Endpoint, EndpointResult, default_get_connections
from chia.rpc.util import ALL_TRANSLATION_LAYERS, RpcEndpoint, marshal
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.program import Program
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.util.config import load_config
from chia.util.errors import KeychainIsLocked
from chia.util.keychain import bytes_to_mnemonic, generate_mnemonic
from chia.util.streamable import UInt32Range
from chia.util.ws_message import WsRpcMessage, create_payload_dict
from chia.wallet.cat_wallet.cat_constants import DEFAULT_CATS
from chia.wallet.cat_wallet.cat_info import CRCATInfo
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.cat_wallet.r_cat_wallet import RCATWallet
from chia.wallet.conditions import (
    AssertConcurrentSpend,
    Condition,
    ConditionValidTimes,
    CreateCoin,
    CreateCoinAnnouncement,
    CreatePuzzleAnnouncement,
    conditions_from_json_dicts,
    parse_timelock_info,
)
from chia.wallet.derive_keys import (
    MAX_POOL_WALLETS,
    master_sk_to_farmer_sk,
    master_sk_to_pool_sk,
    match_address_to_sk,
)
from chia.wallet.did_wallet import did_wallet_puzzles
from chia.wallet.did_wallet.did_info import DIDCoinData, DIDInfo, did_recovery_is_nil
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.did_wallet.did_wallet_puzzles import (
    DID_INNERPUZ_MOD,
    did_program_to_metadata,
    match_did_puzzle,
    metadata_to_program,
)
from chia.wallet.nft_wallet import nft_puzzle_utils
from chia.wallet.nft_wallet.nft_info import NFTCoinInfo, NFTInfo
from chia.wallet.nft_wallet.nft_puzzle_utils import get_metadata_and_phs
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.nft_wallet.uncurry_nft import UncurriedNFT
from chia.wallet.outer_puzzles import AssetType
from chia.wallet.puzzle_drivers import PuzzleInfo
from chia.wallet.puzzles.clawback.metadata import AutoClaimSettings
from chia.wallet.signer_protocol import SigningResponse
from chia.wallet.singleton import (
    SINGLETON_LAUNCHER_PUZZLE_HASH,
    create_singleton_puzzle,
    get_inner_puzzle_from_singleton,
)
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.offer import Offer, OfferSummary
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.util.address_type import AddressType, is_valid_address
from chia.wallet.util.clvm_streamable import json_serialize_with_clvm_streamable
from chia.wallet.util.compute_hints import compute_spend_hints_and_additions
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.curry_and_treehash import NIL_TREEHASH
from chia.wallet.util.query_filter import HashFilter
from chia.wallet.util.signing import sign_message, verify_signature
from chia.wallet.util.transaction_type import CLAWBACK_INCOMING_TRANSACTION_TYPES, TransactionType
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG, TXConfig, TXConfigLoader
from chia.wallet.util.wallet_sync_utils import fetch_coin_spend_for_coin_state
from chia.wallet.util.wallet_types import CoinType, WalletType
from chia.wallet.vc_wallet.cr_cat_drivers import ProofsChecker
from chia.wallet.vc_wallet.cr_cat_wallet import CRCATWallet
from chia.wallet.vc_wallet.vc_store import VCProofs
from chia.wallet.vc_wallet.vc_wallet import VCWallet
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_action_scope import WalletActionScope
from chia.wallet.wallet_coin_record import WalletCoinRecord, WalletCoinRecordMetadataParsingError
from chia.wallet.wallet_coin_store import CoinRecordOrder, GetCoinRecords, unspent_range
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_node import WalletNode, get_wallet_db_path
from chia.wallet.wallet_request_types import (
    AddKey,
    AddKeyResponse,
    ApplySignatures,
    ApplySignaturesResponse,
    BalanceResponse,
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
    CRCATApprovePending,
    CRCATApprovePendingResponse,
    CreateNewDL,
    CreateNewDLResponse,
    CreateNewWallet,
    CreateNewWalletResponse,
    CreateNewWalletType,
    CreateOfferForIDs,
    CreateOfferForIDsResponse,
    CreateSignedTransaction,
    CreateSignedTransactionsResponse,
    DefaultCAT,
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
    DIDType,
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
    Empty,
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
    GetPrivateKeyFormat,
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
    NFTWalletWithDID,
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
    StrayCAT,
    SubmitTransactions,
    SubmitTransactionsResponse,
    TakeOffer,
    TakeOfferResponse,
    TransactionRecordWithMetadata,
    VCAddProofs,
    VCGet,
    VCGetList,
    VCGetListResponse,
    VCGetProofsForRoot,
    VCGetProofsForRootResponse,
    VCGetResponse,
    VCMint,
    VCMintResponse,
    VCProofsRPC,
    VCProofWithHash,
    VCRecordWithCoinID,
    VCRevoke,
    VCRevokeResponse,
    VCSpend,
    VCSpendResponse,
    VerifySignature,
    VerifySignatureResponse,
    WalletCreationMode,
    WalletInfoResponse,
)
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

# Timeout for response from wallet/full node for sending a transaction
TIMEOUT = 30
MAX_DERIVATION_INDEX_DELTA = 1000
MAX_NFT_CHUNK_SIZE = 25

log = logging.getLogger(__name__)


def tx_endpoint(
    push: bool = False,
    merge_spends: bool = True,
) -> Callable[[RpcEndpoint], RpcEndpoint]:
    def _inner(func: RpcEndpoint) -> RpcEndpoint:
        async def rpc_endpoint(
            self: WalletRpcApi, request: dict[str, Any], *args: object, **kwargs: object
        ) -> EndpointResult:
            if await self.service.wallet_state_manager.synced() is False:
                raise ValueError("Wallet needs to be fully synced before making transactions.")

            assert self.service.logged_in_fingerprint is not None
            tx_config_loader: TXConfigLoader = TXConfigLoader.from_json_dict(request)

            # Some backwards compat fill-ins
            if tx_config_loader.excluded_coin_ids is None:
                tx_config_loader = tx_config_loader.override(
                    excluded_coin_ids=request.get("exclude_coin_ids"),
                )
            if tx_config_loader.excluded_coin_amounts is None:
                tx_config_loader = tx_config_loader.override(
                    excluded_coin_amounts=request.get("exclude_coin_amounts"),
                )
            if tx_config_loader.excluded_coin_ids is None:
                excluded_coins: list[dict[str, Any]] | None = request.get(
                    "exclude_coins", request.get("excluded_coins")
                )
                if excluded_coins is not None:
                    tx_config_loader = tx_config_loader.override(
                        excluded_coin_ids=[Coin.from_json_dict(c).name() for c in excluded_coins],
                    )

            tx_config: TXConfig = tx_config_loader.autofill(
                constants=self.service.wallet_state_manager.constants,
                config=self.service.wallet_state_manager.config,
                logged_in_fingerprint=self.service.logged_in_fingerprint,
            )

            extra_conditions: tuple[Condition, ...] = tuple()
            if "extra_conditions" in request:
                extra_conditions = tuple(conditions_from_json_dicts(request["extra_conditions"]))
            extra_conditions = (*extra_conditions, *ConditionValidTimes.from_json_dict(request).to_conditions())

            valid_times: ConditionValidTimes = parse_timelock_info(extra_conditions)
            if (
                valid_times.max_secs_after_created is not None
                or valid_times.min_secs_since_created is not None
                or valid_times.max_blocks_after_created is not None
                or valid_times.min_blocks_since_created is not None
            ):
                raise ValueError("Relative timelocks are not currently supported in the RPC")

            if "action_scope_override" in kwargs:
                response: EndpointResult = await func(
                    self,
                    request,
                    *args,
                    kwargs["action_scope_override"],
                    extra_conditions=extra_conditions,
                    **{k: v for k, v in kwargs.items() if k != "action_scope_override"},
                )
                action_scope = cast(WalletActionScope, kwargs["action_scope_override"])
            else:
                async with self.service.wallet_state_manager.new_action_scope(
                    tx_config,
                    push=request.get("push", push),
                    merge_spends=request.get("merge_spends", merge_spends),
                    sign=request.get("sign", self.service.config.get("auto_sign_txs", True)),
                ) as action_scope:
                    response = await func(
                        self,
                        request,
                        *args,
                        action_scope,
                        extra_conditions=extra_conditions,
                        **kwargs,
                    )

            if func.__name__ == "create_new_wallet" and "transactions" not in response:
                # unfortunately, this API isn't solely a tx endpoint
                return response

            if "action_scope_override" in kwargs:
                # deferring to parent action scope
                return response

            unsigned_txs = await self.service.wallet_state_manager.gather_signing_info_for_txs(
                action_scope.side_effects.transactions
            )

            if request.get("CHIP-0029", False):
                response["unsigned_transactions"] = [
                    json_serialize_with_clvm_streamable(
                        tx,
                        translation_layer=(
                            ALL_TRANSLATION_LAYERS[request["translation"]] if "translation" in request else None
                        ),
                    )
                    for tx in unsigned_txs
                ]
            else:
                response["unsigned_transactions"] = [tx.to_json_dict() for tx in unsigned_txs]

            response["transactions"] = [tx.to_json_dict() for tx in action_scope.side_effects.transactions]

            # Some backwards compatibility code here because transaction information being returned was not uniform
            # until the "transactions" key was applied to all of them. Unfortunately, since .add_pending_transactions
            # now applies transformations to the transactions, we have to special case edit all of the previous
            # spots where the information was being surfaced outside of the knowledge of this wrapper.
            new_txs = action_scope.side_effects.transactions
            if "transaction" in response:
                if (
                    func.__name__ == "create_new_wallet" and request["wallet_type"] == "pool_wallet"
                ) or func.__name__ in {"pw_join_pool", "pw_self_pool", "pw_absorb_rewards"}:
                    # Theses RPCs return not "convenience" for some reason
                    response["transaction"] = new_txs[-1].to_json_dict()
                else:
                    response["transaction"] = response["transactions"][0]
            if "tx_record" in response:
                response["tx_record"] = response["transactions"][0]
            if "fee_transaction" in response:
                # Theses RPCs return not "convenience" for some reason
                fee_transactions = [tx for tx in new_txs if tx.wallet_id == 1]
                if len(fee_transactions) == 0:
                    response["fee_transaction"] = None
                else:
                    response["fee_transaction"] = fee_transactions[0].to_json_dict()
            if "transaction_id" in response:
                response["transaction_id"] = new_txs[0].name
            if "transaction_ids" in response:
                response["transaction_ids"] = [
                    tx.name.hex() for tx in new_txs if tx.type == TransactionType.OUTGOING_CLAWBACK.value
                ]
            if "spend_bundle" in response:
                response["spend_bundle"] = WalletSpendBundle.aggregate(
                    [tx.spend_bundle for tx in new_txs if tx.spend_bundle is not None]
                )
            if "signed_txs" in response:
                response["signed_txs"] = response["transactions"]
            if "signed_tx" in response:
                response["signed_tx"] = response["transactions"][0]
            if "tx" in response:
                if func.__name__ == "send_notification":
                    response["tx"] = response["transactions"][0]
                else:
                    response["tx"] = new_txs[0].to_json_dict()
            if "txs" in response:
                response["txs"] = [tx.to_json_dict() for tx in new_txs]
            if "tx_id" in response:
                response["tx_id"] = new_txs[0].name
            if "trade_record" in response:
                old_offer: Offer = Offer.from_bech32(response["offer"])
                signed_coin_spends: list[CoinSpend] = [
                    coin_spend
                    for tx in new_txs
                    if tx.spend_bundle is not None
                    for coin_spend in tx.spend_bundle.coin_spends
                ]
                involved_coins: list[Coin] = [spend.coin for spend in signed_coin_spends]
                signed_coin_spends.extend(
                    [spend for spend in old_offer._bundle.coin_spends if spend.coin not in involved_coins]
                )
                new_offer_bundle = WalletSpendBundle(
                    signed_coin_spends,
                    AugSchemeMPL.aggregate(
                        [tx.spend_bundle.aggregated_signature for tx in new_txs if tx.spend_bundle is not None]
                    ),
                )
                new_offer: Offer = Offer(old_offer.requested_payments, new_offer_bundle, old_offer.driver_dict)
                response["offer"] = new_offer.to_bech32()
                old_trade_record: TradeRecord = TradeRecord.from_json_dict_convenience(
                    response["trade_record"], bytes(old_offer).hex()
                )
                new_trade: TradeRecord = dataclasses.replace(
                    old_trade_record,
                    offer=bytes(new_offer),
                    trade_id=new_offer.name(),
                )
                response["trade_record"] = new_trade.to_json_dict_convenience()
                if (
                    await self.service.wallet_state_manager.trade_manager.trade_store.get_trade_record(
                        old_trade_record.trade_id
                    )
                    is not None
                ):
                    await self.service.wallet_state_manager.trade_manager.trade_store.delete_trade_record(
                        old_trade_record.trade_id
                    )
                    await self.service.wallet_state_manager.trade_manager.save_trade(new_trade, new_offer)
                for tx in await self.service.wallet_state_manager.tx_store.get_transactions_by_trade_id(
                    old_trade_record.trade_id
                ):
                    await self.service.wallet_state_manager.tx_store.add_transaction_record(
                        dataclasses.replace(tx, trade_id=new_trade.trade_id)
                    )

            return response

        return rpc_endpoint

    return _inner


REPLACEABLE_TRANSACTION_RECORD = TransactionRecord(
    confirmed_at_height=uint32(0),
    created_at_time=uint64(0),
    to_puzzle_hash=bytes32.zeros,
    to_address=encode_puzzle_hash(bytes32.zeros, "replace"),
    amount=uint64(0),
    fee_amount=uint64(0),
    confirmed=False,
    sent=uint32(0),
    spend_bundle=WalletSpendBundle([], G2Element()),
    additions=[],
    removals=[],
    wallet_id=uint32(0),
    sent_to=[],
    trade_id=None,
    type=uint32(0),
    name=bytes32.zeros,
    memos={},
    valid_times=ConditionValidTimes(),
)


class WalletRpcApi:
    if TYPE_CHECKING:
        from chia.rpc.rpc_server import RpcApiProtocol

        _protocol_check: ClassVar[RpcApiProtocol] = cast("WalletRpcApi", None)

    max_get_coin_records_limit: ClassVar[uint32] = uint32(1000)
    max_get_coin_records_filter_items: ClassVar[uint32] = uint32(1000)

    def __init__(self, wallet_node: WalletNode):
        assert wallet_node is not None
        self.service = wallet_node
        self.service_name = "chia_wallet"

    def get_routes(self) -> dict[str, Endpoint]:
        return {
            # Key management
            "/log_in": self.log_in,
            "/get_logged_in_fingerprint": self.get_logged_in_fingerprint,
            "/get_public_keys": self.get_public_keys,
            "/get_private_key": self.get_private_key,
            "/generate_mnemonic": self.generate_mnemonic,
            "/add_key": self.add_key,
            "/delete_key": self.delete_key,
            "/check_delete_key": self.check_delete_key,
            "/delete_all_keys": self.delete_all_keys,
            # Wallet node
            "/set_wallet_resync_on_startup": self.set_wallet_resync_on_startup,
            "/get_sync_status": self.get_sync_status,
            "/get_height_info": self.get_height_info,
            "/push_tx": self.push_tx,
            "/push_transactions": self.push_transactions,
            "/get_timestamp_for_height": self.get_timestamp_for_height,
            "/set_auto_claim": self.set_auto_claim,
            "/get_auto_claim": self.get_auto_claim,
            # Wallet management
            "/get_wallets": self.get_wallets,
            "/create_new_wallet": self.create_new_wallet,
            # Wallet
            "/get_wallet_balance": self.get_wallet_balance,
            "/get_wallet_balances": self.get_wallet_balances,
            "/get_transaction": self.get_transaction,
            "/get_transactions": self.get_transactions,
            "/get_transaction_count": self.get_transaction_count,
            "/get_next_address": self.get_next_address,
            "/send_transaction": self.send_transaction,
            "/send_transaction_multi": self.send_transaction_multi,
            "/spend_clawback_coins": self.spend_clawback_coins,
            "/get_coin_records": self.get_coin_records,
            "/get_farmed_amount": self.get_farmed_amount,
            "/create_signed_transaction": self.create_signed_transaction,
            "/delete_unconfirmed_transactions": self.delete_unconfirmed_transactions,
            "/select_coins": self.select_coins,
            "/get_spendable_coins": self.get_spendable_coins,
            "/get_coin_records_by_names": self.get_coin_records_by_names,
            "/get_current_derivation_index": self.get_current_derivation_index,
            "/extend_derivation_index": self.extend_derivation_index,
            "/get_notifications": self.get_notifications,
            "/delete_notifications": self.delete_notifications,
            "/send_notification": self.send_notification,
            "/sign_message_by_address": self.sign_message_by_address,
            "/sign_message_by_id": self.sign_message_by_id,
            "/verify_signature": self.verify_signature,
            "/get_transaction_memo": self.get_transaction_memo,
            "/split_coins": self.split_coins,
            "/combine_coins": self.combine_coins,
            # CATs and trading
            "/cat_set_name": self.cat_set_name,
            "/cat_asset_id_to_name": self.cat_asset_id_to_name,
            "/cat_get_name": self.cat_get_name,
            "/get_stray_cats": self.get_stray_cats,
            "/cat_spend": self.cat_spend,
            "/cat_get_asset_id": self.cat_get_asset_id,
            "/create_offer_for_ids": self.create_offer_for_ids,
            "/get_offer_summary": self.get_offer_summary,
            "/check_offer_validity": self.check_offer_validity,
            "/take_offer": self.take_offer,
            "/get_offer": self.get_offer,
            "/get_all_offers": self.get_all_offers,
            "/get_offers_count": self.get_offers_count,
            "/cancel_offer": self.cancel_offer,
            "/cancel_offers": self.cancel_offers,
            "/get_cat_list": self.get_cat_list,
            # DID Wallet
            "/did_set_wallet_name": self.did_set_wallet_name,
            "/did_get_wallet_name": self.did_get_wallet_name,
            "/did_update_metadata": self.did_update_metadata,
            "/did_get_pubkey": self.did_get_pubkey,
            "/did_get_did": self.did_get_did,
            "/did_get_metadata": self.did_get_metadata,
            "/did_get_current_coin_info": self.did_get_current_coin_info,
            "/did_create_backup_file": self.did_create_backup_file,
            "/did_transfer_did": self.did_transfer_did,
            "/did_message_spend": self.did_message_spend,
            "/did_get_info": self.did_get_info,
            "/did_find_lost_did": self.did_find_lost_did,
            # NFT Wallet
            "/nft_mint_nft": self.nft_mint_nft,
            "/nft_count_nfts": self.nft_count_nfts,
            "/nft_get_nfts": self.nft_get_nfts,
            "/nft_get_by_did": self.nft_get_by_did,
            "/nft_set_nft_did": self.nft_set_nft_did,
            "/nft_set_nft_status": self.nft_set_nft_status,
            "/nft_get_wallet_did": self.nft_get_wallet_did,
            "/nft_get_wallets_with_dids": self.nft_get_wallets_with_dids,
            "/nft_get_info": self.nft_get_info,
            "/nft_transfer_nft": self.nft_transfer_nft,
            "/nft_add_uri": self.nft_add_uri,
            "/nft_calculate_royalties": self.nft_calculate_royalties,
            "/nft_mint_bulk": self.nft_mint_bulk,
            "/nft_set_did_bulk": self.nft_set_did_bulk,
            "/nft_transfer_bulk": self.nft_transfer_bulk,
            # Pool Wallet
            "/pw_join_pool": self.pw_join_pool,
            "/pw_self_pool": self.pw_self_pool,
            "/pw_absorb_rewards": self.pw_absorb_rewards,
            "/pw_status": self.pw_status,
            # DL Wallet
            "/create_new_dl": self.create_new_dl,
            "/dl_track_new": self.dl_track_new,
            "/dl_stop_tracking": self.dl_stop_tracking,
            "/dl_latest_singleton": self.dl_latest_singleton,
            "/dl_singletons_by_root": self.dl_singletons_by_root,
            "/dl_update_root": self.dl_update_root,
            "/dl_update_multiple": self.dl_update_multiple,
            "/dl_history": self.dl_history,
            "/dl_owned_singletons": self.dl_owned_singletons,
            "/dl_get_mirrors": self.dl_get_mirrors,
            "/dl_new_mirror": self.dl_new_mirror,
            "/dl_delete_mirror": self.dl_delete_mirror,
            "/dl_verify_proof": self.dl_verify_proof,
            # Verified Credential
            "/vc_mint": self.vc_mint,
            "/vc_get": self.vc_get,
            "/vc_get_list": self.vc_get_list,
            "/vc_spend": self.vc_spend,
            "/vc_add_proofs": self.vc_add_proofs,
            "/vc_get_proofs_for_root": self.vc_get_proofs_for_root,
            "/vc_revoke": self.vc_revoke,
            # CR-CATs
            "/crcat_approve_pending": self.crcat_approve_pending,
            # Signer Protocol
            "/gather_signing_info": self.gather_signing_info,
            "/apply_signatures": self.apply_signatures,
            "/submit_transactions": self.submit_transactions,
            # Not technically Signer Protocol but related
            "/execute_signing_instructions": self.execute_signing_instructions,
        }

    def get_connections(self, request_node_type: NodeType | None) -> list[dict[str, Any]]:
        return default_get_connections(server=self.service.server, request_node_type=request_node_type)

    async def _state_changed(self, change: str, change_data: dict[str, Any] | None) -> list[WsRpcMessage]:
        """
        Called by the WalletNode or WalletStateManager when something has changed in the wallet. This
        gives us an opportunity to send notifications to all connected clients via WebSocket.
        """
        payloads = []
        if change in {"sync_changed", "coin_added", "add_connection", "close_connection"}:
            # Metrics is the only current consumer for this event
            payloads.append(create_payload_dict(change, change_data, self.service_name, "metrics"))

        payloads.append(create_payload_dict("state_changed", change_data, self.service_name, "wallet_ui"))

        return payloads

    async def _stop_wallet(self) -> None:
        """
        Stops a currently running wallet/key, which allows starting the wallet with a new key.
        Each key has it's own wallet database.
        """
        if self.service is not None:
            self.service._close()
            await self.service._await_closed(shutting_down=False)

    async def _convert_tx_puzzle_hash(self, tx: TransactionRecord) -> TransactionRecord:
        return dataclasses.replace(
            tx,
            to_puzzle_hash=(
                await self.service.wallet_state_manager.convert_puzzle_hash(tx.wallet_id, tx.to_puzzle_hash)
            ),
        )

    async def get_latest_singleton_coin_spend(
        self, peer: WSChiaConnection, coin_id: bytes32, latest: bool = True
    ) -> tuple[CoinSpend, CoinState]:
        coin_state_list: list[CoinState] = await self.service.wallet_state_manager.wallet_node.get_coin_state(
            [coin_id], peer=peer
        )
        if coin_state_list is None or len(coin_state_list) < 1:
            raise ValueError(f"Coin record 0x{coin_id.hex()} not found")
        coin_state: CoinState = coin_state_list[0]
        if latest:
            # Find the unspent coin
            while coin_state.spent_height is not None:
                coin_state_list = await self.service.wallet_state_manager.wallet_node.fetch_children(
                    coin_state.coin.name(), peer=peer
                )
                odd_coin = None
                for coin in coin_state_list:
                    if coin.coin.amount % 2 == 1:
                        if odd_coin is not None:
                            raise ValueError("This is not a singleton, multiple children coins found.")
                        odd_coin = coin
                if odd_coin is None:
                    raise ValueError("Cannot find child coin, please wait then retry.")
                coin_state = odd_coin
        # Get parent coin
        parent_coin_state_list: list[CoinState] = await self.service.wallet_state_manager.wallet_node.get_coin_state(
            [coin_state.coin.parent_coin_info], peer=peer
        )
        if parent_coin_state_list is None or len(parent_coin_state_list) < 1:
            raise ValueError(f"Parent coin record 0x{coin_state.coin.parent_coin_info.hex()} not found")
        parent_coin_state: CoinState = parent_coin_state_list[0]
        coin_spend = await fetch_coin_spend_for_coin_state(parent_coin_state, peer)
        return coin_spend, coin_state

    ##########################################################################################
    # Key management
    ##########################################################################################

    @marshal
    async def log_in(self, request: LogIn) -> LogInResponse:
        """
        Logs in the wallet with a specific key.
        """

        if self.service.logged_in_fingerprint == request.fingerprint:
            return LogInResponse(request.fingerprint)

        await self._stop_wallet()
        started = await self.service._start_with_fingerprint(request.fingerprint)
        if started is True:
            return LogInResponse(request.fingerprint)

        raise ValueError(f"fingerprint {request.fingerprint} not found in keychain or keychain is empty")

    @marshal
    async def get_logged_in_fingerprint(self, request: Empty) -> GetLoggedInFingerprintResponse:
        return GetLoggedInFingerprintResponse(uint32.construct_optional(self.service.logged_in_fingerprint))

    @marshal
    async def get_public_keys(self, request: Empty) -> GetPublicKeysResponse:
        try:
            fingerprints = [key_data.fingerprint for key_data in await self.service.keychain_proxy.get_keys()]
        except KeychainIsLocked:
            return GetPublicKeysResponse(keyring_is_locked=True)
        except Exception as e:
            raise Exception(
                "Error while getting keys.  If the issue persists, restart all services."
                f"  Original error: {type(e).__name__}: {e}"
            ) from e
        else:
            return GetPublicKeysResponse(keyring_is_locked=False, public_key_fingerprints=fingerprints)

    async def _get_private_key(self, fingerprint: int) -> tuple[PrivateKey | None, bytes | None]:
        try:
            all_keys = await self.service.keychain_proxy.get_all_private_keys()
            for sk, seed in all_keys:
                if sk.get_g1().get_fingerprint() == fingerprint:
                    return sk, seed
        except Exception as e:
            log.error(f"Failed to get private key by fingerprint: {e}")
        return None, None

    @marshal
    async def get_private_key(self, request: GetPrivateKey) -> GetPrivateKeyResponse:
        sk, seed = await self._get_private_key(request.fingerprint)
        if sk is not None:
            s = bytes_to_mnemonic(seed) if seed is not None else None
            return GetPrivateKeyResponse(
                private_key=GetPrivateKeyFormat(
                    fingerprint=request.fingerprint,
                    sk=sk,
                    pk=sk.get_g1(),
                    farmer_pk=master_sk_to_farmer_sk(sk).get_g1(),
                    pool_pk=master_sk_to_pool_sk(sk).get_g1(),
                    seed=s,
                )
            )

        raise ValueError(f"Could not get a private key for fingerprint {request.fingerprint}")

    @marshal
    async def generate_mnemonic(self, request: Empty) -> GenerateMnemonicResponse:
        return GenerateMnemonicResponse(generate_mnemonic().split(" "))

    @marshal
    async def add_key(self, request: AddKey) -> AddKeyResponse:
        # Adding a key from 24 word mnemonic
        try:
            sk = await self.service.keychain_proxy.add_key(" ".join(request.mnemonic), label=request.label)
        except KeyError as e:
            raise ValueError(f"The word '{e.args[0]}' is incorrect.")

        fingerprint = uint32(sk.get_g1().get_fingerprint())
        await self._stop_wallet()

        # Makes sure the new key is added to config properly
        started = False
        try:
            await self.service.keychain_proxy.check_keys(self.service.root_path)
        except Exception as e:
            log.error(f"Failed to check_keys after adding a new key: {e}")
        started = await self.service._start_with_fingerprint(fingerprint=fingerprint)
        if started is True:
            return AddKeyResponse(fingerprint=fingerprint)
        raise ValueError("Failed to start")

    @marshal
    async def delete_key(self, request: DeleteKey) -> Empty:
        await self._stop_wallet()
        try:
            await self.service.keychain_proxy.delete_key_by_fingerprint(request.fingerprint)
        except Exception as e:
            log.error(f"Failed to delete key by fingerprint: {e}")
            raise e
        path = get_wallet_db_path(
            self.service.root_path,
            self.service.config,
            str(request.fingerprint),
        )
        if path.exists():
            path.unlink()
        return Empty()

    async def _check_key_used_for_rewards(
        self, new_root: Path, sk: PrivateKey, max_ph_to_search: int
    ) -> tuple[bool, bool]:
        """Checks if the given key is used for either the farmer rewards or pool rewards
        returns a tuple of two booleans
        The first is true if the key is used as the Farmer rewards, otherwise false
        The second is true if the key is used as the Pool rewards, otherwise false
        Returns both false if the key cannot be found with the given fingerprint
        """
        if sk is None:
            return False, False

        config: dict[str, Any] = load_config(new_root, "config.yaml")
        farmer_target = config["farmer"].get("xch_target_address", "")
        pool_target = config["pool"].get("xch_target_address", "")
        address_to_check: list[bytes32] = []

        try:
            farmer_decoded = decode_puzzle_hash(farmer_target)
            address_to_check.append(farmer_decoded)
        except ValueError:
            farmer_decoded = None

        try:
            pool_decoded = decode_puzzle_hash(pool_target)
            address_to_check.append(pool_decoded)
        except ValueError:
            pool_decoded = None

        found_addresses: set[bytes32] = match_address_to_sk(sk, address_to_check, max_ph_to_search)
        found_farmer = False
        found_pool = False

        if farmer_decoded is not None:
            found_farmer = farmer_decoded in found_addresses

        if pool_decoded is not None:
            found_pool = pool_decoded in found_addresses

        return found_farmer, found_pool

    @marshal
    async def check_delete_key(self, request: CheckDeleteKey) -> CheckDeleteKeyResponse:
        """Check the key use prior to possible deletion
        checks whether key is used for either farm or pool rewards
        checks if any wallets have a non-zero balance
        """
        used_for_farmer: bool = False
        used_for_pool: bool = False
        wallet_balance: bool = False

        sk, _ = await self._get_private_key(request.fingerprint)
        if sk is not None:
            used_for_farmer, used_for_pool = await self._check_key_used_for_rewards(
                self.service.root_path, sk, request.max_ph_to_search
            )

            if self.service.logged_in_fingerprint != request.fingerprint:
                await self._stop_wallet()
                await self.service._start_with_fingerprint(fingerprint=request.fingerprint)

            wallets: list[WalletInfo] = await self.service.wallet_state_manager.get_all_wallet_info_entries()
            for w in wallets:
                wallet = self.service.wallet_state_manager.wallets[w.id]
                unspent = await self.service.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(w.id)
                balance = await wallet.get_confirmed_balance(unspent)
                pending_balance = await wallet.get_unconfirmed_balance(unspent)

                if (balance + pending_balance) > 0:
                    wallet_balance = True
                    break

        return CheckDeleteKeyResponse(
            fingerprint=request.fingerprint,
            used_for_farmer_rewards=used_for_farmer,
            used_for_pool_rewards=used_for_pool,
            wallet_balance=wallet_balance,
        )

    @marshal
    async def delete_all_keys(self, request: Empty) -> Empty:
        await self._stop_wallet()
        all_key_datas = await self.service.keychain_proxy.get_keys()
        try:
            await self.service.keychain_proxy.delete_all_keys()
        except Exception as e:
            log.error(f"Failed to delete all keys: {e}")
            raise e
        for key_data in all_key_datas:
            path = get_wallet_db_path(
                self.service.root_path,
                self.service.config,
                str(key_data.fingerprint),
            )
            if path.exists():
                path.unlink()
        return Empty()

    ##########################################################################################
    # Wallet Node
    ##########################################################################################
    @marshal
    async def set_wallet_resync_on_startup(self, request: SetWalletResyncOnStartup) -> Empty:
        """
        Resync the current logged in wallet. The transaction and offer records will be kept.
        :param request: optionally pass in `enable` as bool to enable/disable resync
        :return:
        """
        assert self.service.wallet_state_manager is not None
        fingerprint = self.service.logged_in_fingerprint
        if fingerprint is not None:
            self.service.set_resync_on_startup(fingerprint, request.enable)
        else:
            raise ValueError("You need to login into wallet to use this RPC call")
        return Empty()

    @marshal
    async def get_sync_status(self, request: Empty) -> GetSyncStatusResponse:
        sync_mode = self.service.wallet_state_manager.sync_mode
        has_pending_queue_items = self.service.new_peak_queue.has_pending_data_process_items()
        syncing = sync_mode or has_pending_queue_items
        synced = await self.service.wallet_state_manager.synced()
        return GetSyncStatusResponse(synced=synced, syncing=syncing)

    @marshal
    async def get_height_info(self, request: Empty) -> GetHeightInfoResponse:
        height = await self.service.wallet_state_manager.blockchain.get_finished_sync_up_to()
        return GetHeightInfoResponse(height=height)

    @marshal
    async def push_tx(self, request: PushTX) -> Empty:
        nodes = self.service.server.get_connections(NodeType.FULL_NODE)
        if len(nodes) == 0:
            raise ValueError("Wallet is not currently connected to any full node peers")
        await self.service.push_tx(request.spend_bundle)
        return Empty()

    @tx_endpoint(push=True)
    @marshal
    async def push_transactions(
        self,
        request: PushTransactions,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> PushTransactionsResponse:
        if not action_scope.config.push:
            raise ValueError("Cannot push transactions if push is False")
        tx_removals = [c for tx in request.transactions for c in tx.removals]
        async with action_scope.use() as interface:
            interface.side_effects.transactions.extend(request.transactions)
            interface.side_effects.selected_coins.extend(tx_removals)
        if request.fee != 0:
            await self.service.wallet_state_manager.main_wallet.create_tandem_xch_tx(
                request.fee,
                action_scope,
                extra_conditions=(
                    *extra_conditions,
                    AssertConcurrentSpend(tx_removals[0].name()),
                ),
            )
        elif extra_conditions != tuple():
            raise ValueError("Cannot add conditions to a transaction if no new fee spend is being added")

        return PushTransactionsResponse([], [])  # tx_endpoint takes care of this

    @marshal
    async def get_timestamp_for_height(self, request: GetTimestampForHeight) -> GetTimestampForHeightResponse:
        return GetTimestampForHeightResponse(await self.service.get_timestamp_for_height(request.height))

    @marshal
    async def set_auto_claim(self, request: AutoClaimSettings) -> AutoClaimSettings:
        """
        Set auto claim merkle coins config
        :param request: Example {"enable": true, "tx_fee": 100000, "min_amount": 0, "batch_size": 50}
        :return:
        """
        return AutoClaimSettings.from_json_dict(self.service.set_auto_claim(request))

    @marshal
    async def get_auto_claim(self, request: Empty) -> AutoClaimSettings:
        """
        Get auto claim merkle coins config
        :param request: None
        :return:
        """
        auto_claim_settings = AutoClaimSettings.from_json_dict(
            self.service.wallet_state_manager.config.get("auto_claim", {})
        )
        return auto_claim_settings

    ##########################################################################################
    # Wallet Management
    ##########################################################################################

    @marshal
    async def get_wallets(self, request: GetWallets) -> GetWalletsResponse:
        wallet_type: WalletType | None = None
        if request.type is not None:
            wallet_type = WalletType(request.type)

        wallets: list[WalletInfo] = await self.service.wallet_state_manager.get_all_wallet_info_entries(wallet_type)
        wallet_infos: list[WalletInfoResponse] = []
        for wallet in wallets:
            if request.include_data:
                data = wallet.data
            else:
                data = ""

            if request.include_data and WalletType(wallet.type) is WalletType.CRCAT:
                crcat_info = CRCATInfo.from_bytes(bytes.fromhex(wallet.data))
                authorized_providers = crcat_info.authorized_providers
                proofs_checker_flags = crcat_info.proofs_checker.flags
            else:
                authorized_providers = []
                proofs_checker_flags = []

            wallet_infos.append(
                WalletInfoResponse(
                    wallet.id,
                    wallet.name,
                    wallet.type,
                    data,
                    authorized_providers,
                    proofs_checker_flags,
                )
            )

        return GetWalletsResponse(wallet_infos, uint32.construct_optional(self.service.logged_in_fingerprint))

    @tx_endpoint(push=True)
    @marshal
    # Semantics guarantee returning on all paths, or else an error.
    # It's probably not great to add a bunch of unreachable code for the sake of mypy.
    async def create_new_wallet(  # type: ignore[return]
        self,
        request: CreateNewWallet,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> CreateNewWalletResponse:
        wallet_state_manager = self.service.wallet_state_manager
        main_wallet = wallet_state_manager.main_wallet

        if request.wallet_type == CreateNewWalletType.CAT_WALLET:
            if request.mode == WalletCreationMode.NEW:
                if not action_scope.config.push:
                    raise ValueError("Test CAT minting must be pushed automatically")  # pragma: no cover
                async with self.service.wallet_state_manager.lock:
                    cat_wallet = await CATWallet.create_new_cat_wallet(
                        wallet_state_manager,
                        main_wallet,
                        {"identifier": "genesis_by_id"},
                        # mypy doesn't know about our __post_init__
                        request.amount,  # type: ignore[arg-type]
                        action_scope,
                        request.fee,
                        request.name,
                    )
                    asset_id = cat_wallet.get_asset_id()
                self.service.wallet_state_manager.state_changed("wallet_created")
                return CreateNewWalletResponse(
                    [], [], type=cat_wallet.type().name, asset_id=asset_id, wallet_id=cat_wallet.id()
                )

            elif request.mode == WalletCreationMode.EXISTING:
                async with self.service.wallet_state_manager.lock:
                    assert request.asset_id is not None  # mypy doesn't know about our __post_init__
                    cat_wallet = await CATWallet.get_or_create_wallet_for_cat(
                        wallet_state_manager, main_wallet, request.asset_id, request.name
                    )
                return CreateNewWalletResponse(
                    [],
                    [],
                    type=cat_wallet.type().name,
                    asset_id=request.asset_id,
                    wallet_id=cat_wallet.id(),
                )
        elif request.wallet_type == CreateNewWalletType.DID_WALLET:
            if request.did_type == DIDType.NEW:
                async with self.service.wallet_state_manager.lock:
                    did_wallet_name = None
                    if request.wallet_name is not None:
                        did_wallet_name = request.wallet_name.strip()
                    assert request.amount is not None  # mypy doesn't know about our __post_init__
                    did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
                        wallet_state_manager,
                        main_wallet,
                        request.amount,
                        action_scope,
                        request.metadata,
                        did_wallet_name,
                        request.fee,
                        extra_conditions=extra_conditions,
                    )

                my_did_id = encode_puzzle_hash(
                    bytes32.fromhex(did_wallet.get_my_DID()), AddressType.DID.hrp(self.service.config)
                )
                nft_wallet_name = did_wallet_name
                if nft_wallet_name is not None:
                    nft_wallet_name = f"{nft_wallet_name} NFT Wallet"
                await NFTWallet.create_new_nft_wallet(
                    wallet_state_manager,
                    main_wallet,
                    bytes32.fromhex(did_wallet.get_my_DID()),
                    nft_wallet_name,
                )
                return CreateNewWalletResponse(
                    [], [], type=did_wallet.type().name, my_did=my_did_id, wallet_id=did_wallet.id()
                )

            elif request.did_type == DIDType.RECOVERY:
                async with self.service.wallet_state_manager.lock:
                    assert request.backup_data is not None  # mypy doesn't know about our __post_init__
                    did_wallet = await DIDWallet.create_new_did_wallet_from_recovery(
                        wallet_state_manager, main_wallet, request.backup_data
                    )
                assert did_wallet.did_info.temp_coin is not None
                assert did_wallet.did_info.temp_puzhash is not None
                assert did_wallet.did_info.temp_pubkey is not None
                my_did = did_wallet.get_my_DID()
                coin_name = did_wallet.did_info.temp_coin.name()
                newpuzhash = did_wallet.did_info.temp_puzhash
                pubkey = did_wallet.did_info.temp_pubkey
                return CreateNewWalletResponse(
                    [],
                    [],
                    type=did_wallet.type().name,
                    my_did=my_did,
                    wallet_id=did_wallet.id(),
                    coin_name=coin_name,
                    coin_list=did_wallet.did_info.temp_coin,
                    newpuzhash=newpuzhash,
                    pubkey=G1Element.from_bytes(pubkey),
                    backup_dids=did_wallet.did_info.backup_ids,
                    num_verifications_required=did_wallet.did_info.num_of_backup_ids_needed,
                )
        elif request.wallet_type == CreateNewWalletType.NFT_WALLET:
            did_id: bytes32 | None = None
            if request.did_id is not None:
                did_id = decode_puzzle_hash(request.did_id)
            for wallet in self.service.wallet_state_manager.wallets.values():
                if wallet.type() == WalletType.NFT:
                    assert isinstance(wallet, NFTWallet)
                    if wallet.get_did() == did_id:
                        log.info("NFT wallet already existed, skipping.")
                        return CreateNewWalletResponse(
                            [],
                            [],
                            type=wallet.type().name,
                            wallet_id=wallet.id(),
                        )

            async with self.service.wallet_state_manager.lock:
                nft_wallet: NFTWallet = await NFTWallet.create_new_nft_wallet(
                    wallet_state_manager, main_wallet, did_id, request.name
                )
            return CreateNewWalletResponse(
                [],
                [],
                type=nft_wallet.type().name,
                wallet_id=nft_wallet.id(),
            )
        elif request.wallet_type == CreateNewWalletType.POOL_WALLET:
            if request.mode == WalletCreationMode.NEW:
                owner_puzzle_hash: bytes32 = await action_scope.get_puzzle_hash(self.service.wallet_state_manager)

                from chia.pools.pool_wallet_info import initial_pool_state_from_dict

                async with self.service.wallet_state_manager.lock:
                    # We assign a pseudo unique id to each pool wallet, so that each one gets its own deterministic
                    # owner and auth keys. The public keys will go on the blockchain, and the private keys can be found
                    # using the root SK and trying each index from zero. The indexes are not fully unique though,
                    # because the PoolWallet is not created until the tx gets confirmed on chain. Therefore if we
                    # make multiple pool wallets at the same time, they will have the same ID.
                    max_pwi = 1
                    for _, wallet in self.service.wallet_state_manager.wallets.items():
                        if wallet.type() == WalletType.POOLING_WALLET:
                            max_pwi += 1

                    if max_pwi + 1 >= (MAX_POOL_WALLETS - 1):
                        raise ValueError(f"Too many pool wallets ({max_pwi}), cannot create any more on this key.")

                    owner_pk: G1Element = self.service.wallet_state_manager.main_wallet.hardened_pubkey_for_path(
                        # copied from chia.wallet.derive_keys. Could maybe be an exported constant in the future.
                        [12381, 8444, 5, max_pwi]
                    )

                    assert request.initial_target_state is not None  # mypy doesn't know about our __post_init__
                    initial_target_state = initial_pool_state_from_dict(
                        request.initial_target_state, owner_pk, owner_puzzle_hash
                    )
                    assert initial_target_state is not None

                    p2_singleton_puzzle_hash, launcher_id = await PoolWallet.create_new_pool_wallet_transaction(
                        wallet_state_manager,
                        main_wallet,
                        initial_target_state,
                        action_scope,
                        request.fee,
                        request.p2_singleton_delay_time,
                        request.p2_singleton_delayed_ph,
                        extra_conditions=extra_conditions,
                    )

                    return CreateNewWalletResponse(
                        [],
                        [],
                        transaction=REPLACEABLE_TRANSACTION_RECORD,
                        total_fee=uint64(request.fee * 2),
                        launcher_id=launcher_id,
                        p2_singleton_puzzle_hash=p2_singleton_puzzle_hash,
                        # irrelevant, will be replaced in serialization
                        type=WalletType.POOLING_WALLET.name,
                        wallet_id=uint32(0),
                    )

    ##########################################################################################
    # Wallet
    ##########################################################################################

    async def _get_wallet_balance(self, wallet_id: uint32) -> BalanceResponse:
        wallet = self.service.wallet_state_manager.wallets[wallet_id]
        balance = await self.service.get_balance(wallet_id)
        wallet_balance = balance.to_json_dict()
        wallet_balance["wallet_id"] = wallet_id
        wallet_balance["wallet_type"] = wallet.type()
        if self.service.logged_in_fingerprint is not None:
            wallet_balance["fingerprint"] = self.service.logged_in_fingerprint
        if wallet.type() in {WalletType.CAT, WalletType.CRCAT, WalletType.RCAT}:
            assert isinstance(wallet, CATWallet)
            wallet_balance["asset_id"] = wallet.get_asset_id().hex()
            if wallet.type() == WalletType.CRCAT:
                assert isinstance(wallet, CRCATWallet)
                wallet_balance["pending_approval_balance"] = await wallet.get_pending_approval_balance()

        return BalanceResponse.from_json_dict(wallet_balance)

    @marshal
    async def get_wallet_balance(self, request: GetWalletBalance) -> GetWalletBalanceResponse:
        return GetWalletBalanceResponse(await self._get_wallet_balance(request.wallet_id))

    @marshal
    async def get_wallet_balances(self, request: GetWalletBalances) -> GetWalletBalancesResponse:
        if request.wallet_ids is not None:
            wallet_ids = request.wallet_ids
        else:
            wallet_ids = list(self.service.wallet_state_manager.wallets.keys())
        return GetWalletBalancesResponse(
            {wallet_id: await self._get_wallet_balance(wallet_id) for wallet_id in wallet_ids}
        )

    @marshal
    async def get_transaction(self, request: GetTransaction) -> GetTransactionResponse:
        tr: TransactionRecord | None = await self.service.wallet_state_manager.get_transaction(request.transaction_id)
        if tr is None:
            raise ValueError(f"Transaction 0x{request.transaction_id.hex()} not found")

        return GetTransactionResponse(
            await self._convert_tx_puzzle_hash(tr),
            tr.name,
        )

    @marshal
    async def get_transaction_memo(self, request: GetTransactionMemo) -> GetTransactionMemoResponse:
        transaction_id: bytes32 = request.transaction_id
        tr: TransactionRecord | None = await self.service.wallet_state_manager.get_transaction(transaction_id)
        if tr is None:
            raise ValueError(f"Transaction 0x{transaction_id.hex()} not found")
        if tr.spend_bundle is None or len(tr.spend_bundle.coin_spends) == 0:
            if tr.type == uint32(TransactionType.INCOMING_TX.value):
                # Fetch incoming tx coin spend
                peer = self.service.get_full_node_peer()
                assert len(tr.additions) == 1
                coin_state_list: list[CoinState] = await self.service.wallet_state_manager.wallet_node.get_coin_state(
                    [tr.additions[0].parent_coin_info], peer=peer
                )
                assert len(coin_state_list) == 1
                coin_spend = await fetch_coin_spend_for_coin_state(coin_state_list[0], peer)
                tr = dataclasses.replace(tr, spend_bundle=WalletSpendBundle([coin_spend], G2Element()))
            else:
                raise ValueError(f"Transaction 0x{transaction_id.hex()} doesn't have any coin spend.")
        assert tr.spend_bundle is not None
        return GetTransactionMemoResponse({transaction_id: compute_memos(tr.spend_bundle)})

    @tx_endpoint(push=False)
    @marshal
    async def split_coins(
        self, request: SplitCoins, action_scope: WalletActionScope, extra_conditions: tuple[Condition, ...] = tuple()
    ) -> SplitCoinsResponse:
        await self.service.wallet_state_manager.split_coins(
            action_scope=action_scope,
            wallet_id=request.wallet_id,
            target_coin_id=request.target_coin_id,
            amount_per_coin=request.amount_per_coin,
            number_of_coins=request.number_of_coins,
            fee=request.fee,
            extra_conditions=extra_conditions,
        )

        return SplitCoinsResponse([], [])  # tx_endpoint will take care to fill this out

    @tx_endpoint(push=False)
    @marshal
    async def combine_coins(
        self, request: CombineCoins, action_scope: WalletActionScope, extra_conditions: tuple[Condition, ...] = tuple()
    ) -> CombineCoinsResponse:
        await self.service.wallet_state_manager.combine_coins(
            action_scope=action_scope,
            wallet_id=request.wallet_id,
            number_of_coins=request.number_of_coins,
            largest_first=request.largest_first,
            coin_num_limit=request.coin_num_limit,
            fee=request.fee,
            target_coin_amount=request.target_coin_amount,
            target_coin_ids=request.target_coin_ids if request.target_coin_ids != [] else None,
            extra_conditions=extra_conditions,
        )
        return CombineCoinsResponse([], [])  # tx_endpoint will take care to fill this out

    @marshal
    async def get_transactions(self, request: GetTransactions) -> GetTransactionsResponse:
        to_puzzle_hash: bytes32 | None = None
        if request.to_address is not None:
            to_puzzle_hash = decode_puzzle_hash(request.to_address)

        transactions = await self.service.wallet_state_manager.tx_store.get_transactions_between(
            wallet_id=request.wallet_id,
            start=uint16(0) if request.start is None else request.start,
            end=uint16(50) if request.end is None else request.end,
            sort_key=request.sort_key,
            reverse=request.reverse,
            to_puzzle_hash=to_puzzle_hash,
            type_filter=request.type_filter,
            confirmed=request.confirmed,
        )
        tx_list = []
        # Format for clawback transactions
        for tr in transactions:
            tx = (await self._convert_tx_puzzle_hash(tr)).to_json_dict()
            tx_list.append(tx)
            if tx["type"] not in CLAWBACK_INCOMING_TRANSACTION_TYPES:
                continue
            coin: Coin = tr.additions[0]
            record: WalletCoinRecord | None = await self.service.wallet_state_manager.coin_store.get_coin_record(
                coin.name()
            )
            if record is None:
                log.error(f"Cannot find coin record for type {tx['type']} transaction {tx['name']}")
                continue
            try:
                tx["metadata"] = record.parsed_metadata().to_json_dict()
            except ValueError as e:
                log.error(f"Could not parse coin record metadata: {type(e).__name__} {e}")
                continue
            tx["metadata"]["coin_id"] = coin.name().hex()
            tx["metadata"]["spent"] = record.spent
        return GetTransactionsResponse(
            transactions=[TransactionRecordWithMetadata.from_json_dict(tx) for tx in tx_list],
            wallet_id=request.wallet_id,
        )

    @marshal
    async def get_transaction_count(self, request: GetTransactionCount) -> GetTransactionCountResponse:
        count = await self.service.wallet_state_manager.tx_store.get_transaction_count_for_wallet(
            request.wallet_id, confirmed=request.confirmed, type_filter=request.type_filter
        )
        return GetTransactionCountResponse(
            request.wallet_id,
            uint16(count),
        )

    @marshal
    async def get_next_address(self, request: GetNextAddress) -> GetNextAddressResponse:
        """
        Returns a new address
        """
        wallet = self.service.wallet_state_manager.wallets[request.wallet_id]
        selected = self.service.config["selected_network"]
        prefix = self.service.config["network_overrides"]["config"][selected]["address_prefix"]
        if wallet.type() in {WalletType.STANDARD_WALLET, WalletType.CAT, WalletType.CRCAT, WalletType.RCAT}:
            async with self.service.wallet_state_manager.new_action_scope(
                DEFAULT_TX_CONFIG, push=request.save_derivations
            ) as action_scope:
                raw_puzzle_hash = await action_scope.get_puzzle_hash(
                    self.service.wallet_state_manager, override_reuse_puzhash_with=not request.new_address
                )
            address = encode_puzzle_hash(raw_puzzle_hash, prefix)
        else:
            raise ValueError(f"Wallet type {wallet.type()} cannot create puzzle hashes")

        return GetNextAddressResponse(
            request.wallet_id,
            address,
        )

    @tx_endpoint(push=True)
    @marshal
    async def send_transaction(
        self,
        request: SendTransaction,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> SendTransactionResponse:
        wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=Wallet)

        # TODO: Add support for multiple puzhash/amount/memo sets
        selected_network = self.service.config["selected_network"]
        expected_prefix = self.service.config["network_overrides"]["config"][selected_network]["address_prefix"]
        if request.address[0 : len(expected_prefix)] != expected_prefix:
            raise ValueError("Unexpected Address Prefix")

        await wallet.generate_signed_transaction(
            [request.amount],
            [decode_puzzle_hash(request.address)],
            action_scope,
            request.fee,
            memos=[[mem.encode("utf-8") for mem in request.memos]],
            puzzle_decorator_override=[request.puzzle_decorator[0].to_json_dict()]
            if request.puzzle_decorator is not None
            else None,
            extra_conditions=extra_conditions,
        )

        # Transaction may not have been included in the mempool yet. Use get_transaction to check.
        # tx_endpoint will take care of the default values here
        return SendTransactionResponse([], [], transaction=REPLACEABLE_TRANSACTION_RECORD, transaction_id=bytes32.zeros)

    @tx_endpoint(push=True)
    @marshal
    async def send_transaction_multi(
        self,
        request: SendTransactionMulti,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> SendTransactionMultiResponse:
        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced before sending transactions")

        wallet = self.service.wallet_state_manager.wallets[request.wallet_id]

        async with self.service.wallet_state_manager.lock:
            if issubclass(type(wallet), CATWallet):
                await self.cat_spend(
                    request.convert_to_proxy(CATSpend).json_serialize_for_transport(
                        action_scope.config.tx_config, extra_conditions, ConditionValidTimes()
                    ),
                    hold_lock=False,
                    action_scope_override=action_scope,
                )
            else:
                await self.create_signed_transaction(
                    request.convert_to_proxy(CreateSignedTransaction).json_serialize_for_transport(
                        action_scope.config.tx_config, extra_conditions, ConditionValidTimes()
                    ),
                    hold_lock=False,
                    action_scope_override=action_scope,
                )

        # tx_endpoint will take care of these values
        return SendTransactionMultiResponse(
            [], [], transaction=REPLACEABLE_TRANSACTION_RECORD, transaction_id=bytes32.zeros
        )

    @tx_endpoint(push=True, merge_spends=False)
    @marshal
    async def spend_clawback_coins(
        self,
        request: SpendClawbackCoins,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> SpendClawbackCoinsResponse:
        """Spend clawback coins that were sent (to claw them back) or received (to claim them).

        :param coin_ids: list of coin ids to be spent
        :param batch_size: number of coins to spend per bundle
        :param fee: transaction fee in mojos
        :return:
        """
        coin_records = await self.service.wallet_state_manager.coin_store.get_coin_records(
            coin_id_filter=HashFilter.include(request.coin_ids),
            coin_type=CoinType.CLAWBACK,
            wallet_type=WalletType.STANDARD_WALLET,
            spent_range=UInt32Range(stop=uint32(0)),
        )

        batch_size = (
            request.batch_size
            if request.batch_size is not None
            else self.service.wallet_state_manager.config.get("auto_claim", {}).get("batch_size", 50)
        )
        records_list = list(coin_records.coin_id_to_record.values())
        for i in range(0, len(records_list), batch_size):
            try:
                coin_batch = {
                    coin_record.coin: coin_record.parsed_metadata() for coin_record in records_list[i : i + batch_size]
                }
            except WalletCoinRecordMetadataParsingError as e:
                log.error("Failed to spend clawback coin: %s", e)
                continue
            await self.service.wallet_state_manager.spend_clawback_coins(
                # Semantically, we're guaranteed the right type here, but the typing isn't there
                coin_batch,  # type: ignore[arg-type]
                request.fee,
                action_scope,
                request.force,
                extra_conditions=extra_conditions,
            )

        # tx_endpoint will fill in the default values here
        return SpendClawbackCoinsResponse([], [], transaction_ids=[])

    @marshal
    async def delete_unconfirmed_transactions(self, request: DeleteUnconfirmedTransactions) -> Empty:
        if request.wallet_id not in self.service.wallet_state_manager.wallets:
            raise ValueError(f"Wallet id {request.wallet_id} does not exist")
        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced.")

        async with self.service.wallet_state_manager.db_wrapper.writer():
            await self.service.wallet_state_manager.tx_store.delete_unconfirmed_transactions(request.wallet_id)
            wallet = self.service.wallet_state_manager.wallets[request.wallet_id]
            if wallet.type() == WalletType.POOLING_WALLET.value:
                assert isinstance(wallet, PoolWallet)
                wallet.target_state = None
            return Empty()

    @marshal
    async def select_coins(
        self,
        request: SelectCoins,
    ) -> SelectCoinsResponse:
        assert self.service.logged_in_fingerprint is not None

        # Some backwards compat fill-ins
        if request.excluded_coin_ids is None:
            if request.exclude_coins is not None:
                request = request.override(
                    excluded_coin_ids=[c.name() for c in request.exclude_coins],
                    exclude_coins=None,
                )

        # don't love this snippet of code
        # but I think action scopes need to accept CoinSelectionConfigs
        # instead of solely TXConfigs in order for this to be less ugly
        autofilled_cs_config = request.autofill(
            constants=self.service.wallet_state_manager.constants,
        )
        tx_config = DEFAULT_TX_CONFIG.override(
            **{
                field.name: getattr(autofilled_cs_config, field.name)
                for field in dataclasses.fields(autofilled_cs_config)
            }
        )

        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced before selecting coins")

        wallet = self.service.wallet_state_manager.wallets[request.wallet_id]
        async with self.service.wallet_state_manager.new_action_scope(tx_config, push=False) as action_scope:
            selected_coins = await wallet.select_coins(request.amount, action_scope)

        return SelectCoinsResponse(coins=list(selected_coins))

    @marshal
    async def get_spendable_coins(self, request: GetSpendableCoins) -> GetSpendableCoinsResponse:
        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced before getting all coins")

        state_mgr = self.service.wallet_state_manager
        async with state_mgr.lock:
            # Removals
            unconfirmed_removals = await state_mgr.unconfirmed_additions_or_removals_for_wallet(
                wallet_id=request.wallet_id, get="removals"
            )
            unconfirmed_removal_ids = {coin.name() for coin in unconfirmed_removals}
            removal_records: list[CoinRecord] = []
            for coin_record in (
                await state_mgr.coin_store.get_coin_records(
                    coin_id_filter=HashFilter.include(list(unconfirmed_removal_ids))
                )
            ).records:
                removal_records.append(await state_mgr.get_coin_record_by_wallet_record(coin_record))

            # Additions
            unconfirmed_additions = await state_mgr.unconfirmed_additions_or_removals_for_wallet(
                wallet_id=request.wallet_id, get="additions"
            )

            # Spendable coins
            unfiltered_spendable_coin_records = await state_mgr.get_spendable_coins_for_wallet(
                request.wallet_id, pending_removals=unconfirmed_removal_ids
            )
            filtered_spendable_coins = request.autofill(
                constants=self.service.wallet_state_manager.constants
            ).filter_coins({cr.coin for cr in unfiltered_spendable_coin_records})
            filtered_spendable_coin_records = list(
                cr for cr in unfiltered_spendable_coin_records if cr.coin in filtered_spendable_coins
            )
            valid_spendable_cr: list[CoinRecord] = []
            for coin_record in filtered_spendable_coin_records:
                valid_spendable_cr.append(await state_mgr.get_coin_record_by_wallet_record(coin_record))

        return GetSpendableCoinsResponse(
            confirmed_records=valid_spendable_cr,
            unconfirmed_removals=removal_records,
            unconfirmed_additions=list(unconfirmed_additions),
        )

    @marshal
    async def get_coin_records_by_names(self, request: GetCoinRecordsByNames) -> GetCoinRecordsByNamesResponse:
        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced before finding coin information")

        kwargs: dict[str, Any] = {
            "coin_id_filter": HashFilter.include(request.names),
        }

        confirmed_range = UInt32Range()
        if request.start_height is not None:
            confirmed_range = dataclasses.replace(confirmed_range, start=request.start_height)
        if request.end_height is not None:
            confirmed_range = dataclasses.replace(confirmed_range, stop=request.end_height)
        if confirmed_range != UInt32Range():
            kwargs["confirmed_range"] = confirmed_range

        if not request.include_spent_coins:
            kwargs["spent_range"] = unspent_range

        async with self.service.wallet_state_manager.lock:
            coin_records: list[CoinRecord] = await self.service.wallet_state_manager.get_coin_records_by_coin_ids(
                **kwargs
            )
            missed_coins: list[str] = [
                "0x" + c_id.hex() for c_id in request.names if c_id not in [cr.name for cr in coin_records]
            ]
            if missed_coins:
                raise ValueError(f"Coin ID's: {missed_coins} not found.")

        return GetCoinRecordsByNamesResponse(coin_records)

    @marshal
    async def get_current_derivation_index(self, request: Empty) -> GetCurrentDerivationIndexResponse:
        assert self.service.wallet_state_manager is not None

        index: uint32 | None = await self.service.wallet_state_manager.puzzle_store.get_last_derivation_path()

        return GetCurrentDerivationIndexResponse(index)

    @marshal
    async def extend_derivation_index(self, request: ExtendDerivationIndex) -> ExtendDerivationIndexResponse:
        assert self.service.wallet_state_manager is not None

        # Require that the wallet is fully synced
        synced = await self.service.wallet_state_manager.synced()
        if synced is False:
            raise ValueError("Wallet needs to be fully synced before extending derivation index")

        current: uint32 | None = await self.service.wallet_state_manager.puzzle_store.get_last_derivation_path()

        # Additional sanity check that the wallet is synced
        if current is None:
            raise ValueError("No current derivation record found, unable to extend index")

        # Require that the new index is greater than the current index
        if request.index <= current:
            raise ValueError(f"New derivation index must be greater than current index: {current}")

        if request.index - current > MAX_DERIVATION_INDEX_DELTA:
            raise ValueError(
                "Too many derivations requested. "
                f"Use a derivation index less than {current + MAX_DERIVATION_INDEX_DELTA + 1}"
            )

        # Since we've bumping the derivation index without having found any new puzzles, we want
        # to preserve the current last used index, so we call create_more_puzzle_hashes with
        # mark_existing_as_used=False
        result = await self.service.wallet_state_manager.create_more_puzzle_hashes(
            from_zero=False, mark_existing_as_used=False, up_to_index=request.index, num_additional_phs=0
        )
        await result.commit(self.service.wallet_state_manager)

        updated_index = await self.service.wallet_state_manager.puzzle_store.get_last_derivation_path()

        return ExtendDerivationIndexResponse(updated_index)

    @marshal
    async def get_notifications(self, request: GetNotifications) -> GetNotificationsResponse:
        return GetNotificationsResponse(
            await self.service.wallet_state_manager.notification_manager.notification_store.get_notifications(
                coin_ids=request.ids, pagination=(request.start, request.end)
            )
        )

    @marshal
    async def delete_notifications(self, request: DeleteNotifications) -> Empty:
        await self.service.wallet_state_manager.notification_manager.notification_store.delete_notifications(
            coin_ids=request.ids
        )

        return Empty()

    @tx_endpoint(push=True)
    @marshal
    async def send_notification(
        self,
        request: SendNotification,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> SendNotificationResponse:
        await self.service.wallet_state_manager.notification_manager.send_new_notification(
            request.target,
            request.message,
            request.amount,
            action_scope,
            request.fee,
            extra_conditions=extra_conditions,
        )

        # tx_endpoint will take care of these default values
        return SendNotificationResponse([], [], tx=REPLACEABLE_TRANSACTION_RECORD)

    @marshal
    async def verify_signature(self, request: VerifySignature) -> VerifySignatureResponse:
        return verify_signature(
            signing_mode=request.signing_mode_enum,
            public_key=request.pubkey,
            message=request.message,
            signature=request.signature,
            address=request.address,
        )

    @marshal
    async def sign_message_by_address(self, request: SignMessageByAddress) -> SignMessageByAddressResponse:
        """
        Given a derived P2 address, sign the message by its private key.
        :param request:
        :return:
        """
        synthetic_secret_key = self.service.wallet_state_manager.main_wallet.convert_secret_key_to_synthetic(
            await self.service.wallet_state_manager.get_private_key(decode_puzzle_hash(request.address))
        )
        signing_response = sign_message(
            secret_key=synthetic_secret_key,
            message=request.message,
            mode=request.signing_mode_enum,
        )
        return SignMessageByAddressResponse(
            pubkey=signing_response.pubkey,
            signature=signing_response.signature,
            signing_mode=request.signing_mode_enum.value,
        )

    @marshal
    async def sign_message_by_id(self, request: SignMessageByID) -> SignMessageByIDResponse:
        """
        Given a NFT/DID ID, sign the message by the P2 private key.
        :param request:
        :return:
        """
        entity_id: bytes32 = decode_puzzle_hash(request.id)
        if is_valid_address(request.id, {AddressType.DID}, self.service.config):
            did_wallet: DIDWallet | None = None
            for wallet in self.service.wallet_state_manager.wallets.values():
                if wallet.type() == WalletType.DECENTRALIZED_ID.value:
                    assert isinstance(wallet, DIDWallet)
                    assert wallet.did_info.origin_coin is not None
                    if wallet.did_info.origin_coin.name() == entity_id:
                        did_wallet = wallet
                        break
            if did_wallet is None:
                raise ValueError(f"DID for {entity_id.hex()} doesn't exist.")
            synthetic_secret_key = self.service.wallet_state_manager.main_wallet.convert_secret_key_to_synthetic(
                await self.service.wallet_state_manager.get_private_key(await did_wallet.current_p2_puzzle_hash())
            )
            latest_coin_id = (await did_wallet.get_coin()).name()
            signing_response = sign_message(
                secret_key=synthetic_secret_key,
                message=request.message,
                mode=request.signing_mode_enum,
            )
            return SignMessageByIDResponse(
                pubkey=signing_response.pubkey,
                signature=signing_response.signature,
                signing_mode=request.signing_mode_enum.value,
                latest_coin_id=latest_coin_id,
            )
        elif is_valid_address(request.id, {AddressType.NFT}, self.service.config):
            nft_wallet: NFTWallet | None = None
            target_nft: NFTCoinInfo | None = None
            for wallet in self.service.wallet_state_manager.wallets.values():
                if wallet.type() == WalletType.NFT.value:
                    assert isinstance(wallet, NFTWallet)
                    nft: NFTCoinInfo | None = await wallet.get_nft(entity_id)
                    if nft is not None:
                        nft_wallet = wallet
                        target_nft = nft
                        break
            if nft_wallet is None or target_nft is None:
                raise ValueError(f"NFT for {entity_id.hex()} doesn't exist.")

            assert isinstance(nft_wallet, NFTWallet)
            synthetic_secret_key = self.service.wallet_state_manager.main_wallet.convert_secret_key_to_synthetic(
                await self.service.wallet_state_manager.get_private_key(
                    await nft_wallet.current_p2_puzzle_hash(target_nft)
                )
            )
            latest_coin_id = target_nft.coin.name()
            signing_response = sign_message(
                secret_key=synthetic_secret_key,
                message=request.message,
                mode=request.signing_mode_enum,
            )
            return SignMessageByIDResponse(
                pubkey=signing_response.pubkey,
                signature=signing_response.signature,
                signing_mode=request.signing_mode_enum.value,
                latest_coin_id=latest_coin_id,
            )
        else:
            raise ValueError(f"Unknown ID type, {request.id}")

    ##########################################################################################
    # CATs and Trading
    ##########################################################################################

    @marshal
    async def get_cat_list(self, request: Empty) -> GetCATListResponse:
        return GetCATListResponse([DefaultCAT.from_json_dict(default_cat) for default_cat in DEFAULT_CATS.values()])

    @marshal
    async def cat_set_name(self, request: CATSetName) -> CATSetNameResponse:
        wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=CATWallet)
        await wallet.set_name(request.name)
        return CATSetNameResponse(wallet_id=request.wallet_id)

    @marshal
    async def cat_get_name(self, request: CATGetName) -> CATGetNameResponse:
        wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=CATWallet)
        name: str = wallet.get_name()
        return CATGetNameResponse(wallet_id=request.wallet_id, name=name)

    @marshal
    async def get_stray_cats(self, request: Empty) -> GetStrayCATsResponse:
        """
        Get a list of all unacknowledged CATs
        :param request: RPC request
        :return: A list of unacknowledged CATs
        """
        cats = await self.service.wallet_state_manager.interested_store.get_unacknowledged_tokens()
        return GetStrayCATsResponse(stray_cats=[StrayCAT.from_json_dict(cat) for cat in cats])

    @tx_endpoint(push=True)
    @marshal
    async def cat_spend(
        self,
        request: CATSpend,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
        hold_lock: bool = True,
    ) -> CATSpendResponse:
        wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=CATWallet)

        amounts: list[uint64] = []
        puzzle_hashes: list[bytes32] = []
        memos: list[list[bytes]] = []
        if request.additions is not None:
            for addition in request.additions:
                if addition.amount > self.service.constants.MAX_COIN_AMOUNT:
                    raise ValueError(f"Coin amount cannot exceed {self.service.constants.MAX_COIN_AMOUNT}")
                amounts.append(addition.amount)
                puzzle_hashes.append(addition.puzzle_hash)
                if addition.memos is not None:
                    memos.append([mem.encode("utf-8") for mem in addition.memos])
        else:
            # Our __post_init__ guards against these not being None
            amounts.append(request.amount)  # type: ignore[arg-type]
            puzzle_hashes.append(decode_puzzle_hash(request.inner_address))  # type: ignore[arg-type]
            if request.memos is not None:
                memos.append([mem.encode("utf-8") for mem in request.memos])
        coins: set[Coin] | None = None
        if request.coins is not None and len(request.coins) > 0:
            coins = set(request.coins)

        if hold_lock:
            async with self.service.wallet_state_manager.lock:
                await wallet.generate_signed_transaction(
                    amounts,
                    puzzle_hashes,
                    action_scope,
                    request.fee,
                    cat_discrepancy=request.cat_discrepancy,
                    coins=coins,
                    memos=memos if memos else None,
                    extra_conditions=extra_conditions,
                )
        else:
            await wallet.generate_signed_transaction(
                amounts,
                puzzle_hashes,
                action_scope,
                request.fee,
                cat_discrepancy=request.cat_discrepancy,
                coins=coins,
                memos=memos if memos else None,
                extra_conditions=extra_conditions,
            )

        # tx_endpoint will fill in these default values
        return CATSpendResponse([], [], transaction=REPLACEABLE_TRANSACTION_RECORD, transaction_id=bytes32.zeros)

    @marshal
    async def cat_get_asset_id(self, request: CATGetAssetID) -> CATGetAssetIDResponse:
        wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=CATWallet)
        asset_id = wallet.get_asset_id()
        return CATGetAssetIDResponse(asset_id=asset_id, wallet_id=request.wallet_id)

    @marshal
    async def cat_asset_id_to_name(self, request: CATAssetIDToName) -> CATAssetIDToNameResponse:
        wallet = await self.service.wallet_state_manager.get_wallet_for_asset_id(request.asset_id)
        if wallet is None:
            if request.asset_id.hex() in DEFAULT_CATS:
                return CATAssetIDToNameResponse(wallet_id=None, name=DEFAULT_CATS[request.asset_id.hex()]["name"])
            else:
                return CATAssetIDToNameResponse(wallet_id=None, name=None)
        else:
            return CATAssetIDToNameResponse(wallet_id=wallet.id(), name=wallet.get_name())

    @tx_endpoint(push=False)
    @marshal
    async def create_offer_for_ids(
        self,
        request: CreateOfferForIDs,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> CreateOfferForIDsResponse:
        if action_scope.config.push:
            raise ValueError("Cannot push an incomplete spend")

        # This driver_dict construction is to maintain backward compatibility where everything is assumed to be a CAT
        driver_dict: dict[bytes32, PuzzleInfo] = {}
        if request.driver_dict is None:
            for key, amount in request.offer_spec.items():
                if amount > 0 and isinstance(key, bytes32):
                    driver_dict[key] = PuzzleInfo({"type": AssetType.CAT.value, "tail": "0x" + key.hex()})
        else:
            driver_dict = request.driver_dict

        async with self.service.wallet_state_manager.lock:
            result = await self.service.wallet_state_manager.trade_manager.create_offer_for_ids(
                request.offer_spec,
                action_scope,
                driver_dict,
                solver=request.solver,
                fee=request.fee,
                validate_only=request.validate_only,
                extra_conditions=extra_conditions,
            )

        return CreateOfferForIDsResponse(
            [],
            [],
            offer=Offer.from_bytes(result[1].offer),
            trade_record=result[1],
        )

    @marshal
    async def get_offer_summary(self, request: GetOfferSummary) -> GetOfferSummaryResponse:
        dl_summary = None
        if not request.advanced:
            dl_summary = await self.service.wallet_state_manager.trade_manager.get_dl_offer_summary(
                request.parsed_offer
            )
        if dl_summary is not None:
            response = GetOfferSummaryResponse(
                data_layer_summary=dl_summary,
                id=request.parsed_offer.name(),
            )
        else:
            offered, requested, infos, valid_times = request.parsed_offer.summary()
            response = GetOfferSummaryResponse(
                summary=OfferSummary(
                    offered=offered,
                    requested=requested,
                    fees=uint64(request.parsed_offer.fees()),
                    infos=infos,
                    additions=[c.name() for c in request.parsed_offer.additions()],
                    removals=[c.name() for c in request.parsed_offer.removals()],
                    valid_times=valid_times.only_absolutes(),
                ),
                id=request.parsed_offer.name(),
            )

        # This is a bit of a hack in favor of returning some more manageable information about CR-CATs
        # A more general solution surely exists, but I'm not sure what it is right now
        return dataclasses.replace(
            response,
            summary=dataclasses.replace(
                response.summary,
                infos={
                    key: (
                        PuzzleInfo(
                            {
                                **info.info,
                                "also": {
                                    **info.info["also"],
                                    "flags": ProofsChecker.from_program(
                                        uncurry_puzzle(Program(assemble(info.info["also"]["proofs_checker"])))
                                    ).flags,
                                },
                            }
                        )
                        if "also" in info.info and "proofs_checker" in info.info["also"]
                        else info
                    )
                    for key, info in response.summary.infos.items()
                },
            )
            if response.summary is not None
            else None,
        )

    @marshal
    async def check_offer_validity(self, request: CheckOfferValidity) -> CheckOfferValidityResponse:
        offer = Offer.from_bech32(request.offer)
        peer = self.service.get_full_node_peer()
        return CheckOfferValidityResponse(
            valid=(await self.service.wallet_state_manager.trade_manager.check_offer_validity(offer, peer)),
            id=offer.name(),
        )

    @tx_endpoint(push=True)
    @marshal
    async def take_offer(
        self,
        request: TakeOffer,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> TakeOfferResponse:
        peer = self.service.get_full_node_peer()
        trade_record = await self.service.wallet_state_manager.trade_manager.respond_to_offer(
            request.parsed_offer,
            peer,
            action_scope,
            fee=request.fee,
            solver=request.solver,
            extra_conditions=extra_conditions,
        )

        async with action_scope.use() as interface:
            interface.side_effects.signing_responses.append(
                SigningResponse(bytes(request.parsed_offer._bundle.aggregated_signature), trade_record.trade_id)
            )

        return TakeOfferResponse(
            [],  # tx_endpoint will fill in this default value
            [],  # tx_endpoint will fill in this default value
            Offer.from_bytes(trade_record.offer),
            trade_record,
        )

    @marshal
    async def get_offer(self, request: GetOffer) -> GetOfferResponse:
        trade_mgr = self.service.wallet_state_manager.trade_manager

        trade_record: TradeRecord | None = await trade_mgr.get_trade_by_id(request.trade_id)
        if trade_record is None:
            raise ValueError(f"No trade with trade id: {request.trade_id.hex()}")

        offer_to_return: bytes = trade_record.offer if trade_record.taken_offer is None else trade_record.taken_offer
        offer: str | None = Offer.from_bytes(offer_to_return).to_bech32() if request.file_contents else None
        return GetOfferResponse(
            offer,
            trade_record,
        )

    @marshal
    async def get_all_offers(self, request: GetAllOffers) -> GetAllOffersResponse:
        trade_mgr = self.service.wallet_state_manager.trade_manager

        all_trades = await trade_mgr.trade_store.get_trades_between(
            request.start,
            request.end,
            sort_key=request.sort_key,
            reverse=request.reverse,
            exclude_my_offers=request.exclude_my_offers,
            exclude_taken_offers=request.exclude_taken_offers,
            include_completed=request.include_completed,
        )
        result = []
        offer_values: list[str] | None = [] if request.file_contents else None
        for trade in all_trades:
            result.append(trade)
            if request.file_contents:
                offer_to_return: bytes = trade.offer if trade.taken_offer is None else trade.taken_offer
                # semantics guarantee this to be not None
                offer_values.append(Offer.from_bytes(offer_to_return).to_bech32())  # type: ignore[union-attr]

        return GetAllOffersResponse(
            trade_records=result,
            offers=offer_values,
        )

    @marshal
    async def get_offers_count(self, request: Empty) -> GetOffersCountResponse:
        trade_mgr = self.service.wallet_state_manager.trade_manager

        (total, my_offers_count, taken_offers_count) = await trade_mgr.trade_store.get_trades_count()

        return GetOffersCountResponse(
            total=uint16(total), my_offers_count=uint16(my_offers_count), taken_offers_count=uint16(taken_offers_count)
        )

    @tx_endpoint(push=True)
    @marshal
    async def cancel_offer(
        self,
        request: CancelOffer,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> CancelOfferResponse:
        wsm = self.service.wallet_state_manager
        async with self.service.wallet_state_manager.lock:
            await wsm.trade_manager.cancel_pending_offers(
                [request.trade_id],
                action_scope,
                fee=request.fee,
                secure=request.secure,
                extra_conditions=extra_conditions,
            )

        return CancelOfferResponse([], [])  # tx_endpoint will fill in default values here

    @tx_endpoint(push=True, merge_spends=False)
    @marshal
    async def cancel_offers(
        self,
        request: CancelOffers,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> CancelOffersResponse:
        trade_mgr = self.service.wallet_state_manager.trade_manager
        log.info(f"Start cancelling offers for  {'all' if request.cancel_all else 'asset_id: ' + request.asset_id} ...")
        # Traverse offers page by page
        for start in count(0, request.batch_size):
            records = {
                record.trade_id: record
                for record in await trade_mgr.trade_store.get_trades_between(
                    start,
                    start + request.batch_size,
                    reverse=True,
                    exclude_my_offers=False,
                    exclude_taken_offers=True,
                    include_completed=False,
                )
                if request.cancel_all
                or (record.offer != b"" and request.query_key in Offer.from_bytes(record.offer).arbitrage())
            }

            if records == {}:
                break

            async with self.service.wallet_state_manager.lock:
                await trade_mgr.cancel_pending_offers(
                    list(records.keys()),
                    action_scope,
                    request.batch_fee,
                    request.secure,
                    records,
                    extra_conditions=extra_conditions,
                )

            log.info(f"Created offer cancellations for {start} to {start + request.batch_size} ...")

        return CancelOffersResponse([], [])  # tx_endpoint wrapper will take care of this

    ##########################################################################################
    # Distributed Identities
    ##########################################################################################

    @marshal
    async def did_set_wallet_name(self, request: DIDSetWalletName) -> DIDSetWalletNameResponse:
        wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=DIDWallet)
        await wallet.set_name(request.name)
        return DIDSetWalletNameResponse(request.wallet_id)

    @marshal
    async def did_get_wallet_name(self, request: DIDGetWalletName) -> DIDGetWalletNameResponse:
        wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=DIDWallet)
        return DIDGetWalletNameResponse(request.wallet_id, wallet.get_name())

    @tx_endpoint(push=False)
    @marshal
    async def did_message_spend(
        self,
        request: DIDMessageSpend,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> DIDMessageSpendResponse:
        wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=DIDWallet)

        await wallet.create_message_spend(
            action_scope,
            extra_conditions=(
                *extra_conditions,
                *(CreateCoinAnnouncement(ca) for ca in request.coin_announcements),
                *(CreatePuzzleAnnouncement(pa) for pa in request.puzzle_announcements),
            ),
        )

        # tx_endpoint will take care of the default values here
        return DIDMessageSpendResponse([], [], WalletSpendBundle([], G2Element()))

    @marshal
    async def did_get_info(self, request: DIDGetInfo) -> DIDGetInfoResponse:
        if request.coin_id.startswith(AddressType.DID.hrp(self.service.config)):
            coin_id = decode_puzzle_hash(request.coin_id)
        else:
            coin_id = bytes32.from_hexstr(request.coin_id)
        # Get coin state
        peer = self.service.get_full_node_peer()
        coin_spend, coin_state = await self.get_latest_singleton_coin_spend(peer, coin_id, request.latest)
        uncurried = uncurry_puzzle(coin_spend.puzzle_reveal)
        curried_args = match_did_puzzle(uncurried.mod, uncurried.args)
        if curried_args is None:
            raise ValueError("The coin is not a DID.")
        p2_puzzle, recovery_list_hash, num_verification, singleton_struct, metadata = curried_args
        recovery_list_hash_bytes = recovery_list_hash.as_atom()
        launcher_id = bytes32(singleton_struct.rest().first().as_atom())
        uncurried_p2 = uncurry_puzzle(p2_puzzle)
        (public_key,) = uncurried_p2.args.as_iter()
        memos = compute_memos(WalletSpendBundle([coin_spend], G2Element()))
        hints = []
        coin_memos = memos.get(coin_state.coin.name())
        if coin_memos is not None:
            for memo in coin_memos:
                hints.append(memo)
        return DIDGetInfoResponse(
            did_id=encode_puzzle_hash(launcher_id, AddressType.DID.hrp(self.service.config)),
            latest_coin=coin_state.coin.name(),
            p2_address=encode_puzzle_hash(p2_puzzle.get_tree_hash(), AddressType.XCH.hrp(self.service.config)),
            public_key=public_key.as_atom(),
            recovery_list_hash=bytes32(recovery_list_hash_bytes) if recovery_list_hash_bytes != b"" else None,
            num_verification=uint16(num_verification.as_int()),
            metadata=did_program_to_metadata(metadata),
            launcher_id=launcher_id,
            full_puzzle=Program.from_serialized(coin_spend.puzzle_reveal),
            solution=Program.from_serialized(coin_spend.solution),
            hints=hints,
        )

    @marshal
    async def did_find_lost_did(self, request: DIDFindLostDID) -> DIDFindLostDIDResponse:
        """
        Recover a missing or unspendable DID wallet by a coin id of the DID
        :param coin_id: It can be DID ID, launcher coin ID or any coin ID of the DID you want to find.
        The latest coin ID will take less time.
        :return:
        """
        # Check if we have a DID wallet for this
        if request.coin_id.startswith(AddressType.DID.hrp(self.service.config)):
            coin_id = decode_puzzle_hash(request.coin_id)
        else:
            coin_id = bytes32.from_hexstr(request.coin_id)
        # Get coin state
        peer = self.service.get_full_node_peer()
        coin_spend, coin_state = await self.get_latest_singleton_coin_spend(peer, coin_id)
        uncurried = uncurry_puzzle(coin_spend.puzzle_reveal)
        curried_args = match_did_puzzle(uncurried.mod, uncurried.args)
        if curried_args is None:
            raise ValueError("The coin is not a DID.")
        p2_puzzle, recovery_list_hash, num_verification, singleton_struct, metadata = curried_args
        num_verification_int: uint16 | None = uint16(num_verification.as_int())
        assert num_verification_int is not None
        did_data: DIDCoinData = DIDCoinData(
            p2_puzzle,
            bytes32(recovery_list_hash.as_atom()) if recovery_list_hash != Program.NIL else None,
            num_verification_int,
            singleton_struct,
            metadata,
            get_inner_puzzle_from_singleton(coin_spend.puzzle_reveal),
            coin_state,
        )
        hinted_coins, _ = compute_spend_hints_and_additions(coin_spend)
        # Hint is required, if it doesn't have any hint then it should be invalid
        hint: bytes32 | None = None
        for hinted_coin in hinted_coins.values():
            if hinted_coin.coin.amount % 2 == 1 and hinted_coin.hint is not None:
                hint = hinted_coin.hint
                break
        derivation_record = None
        if hint is not None:
            derivation_record = (
                await self.service.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(hint)
            )
        if derivation_record is None:
            # This is an invalid DID, check if we are owner
            derivation_record = (
                await self.service.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(
                    p2_puzzle.get_tree_hash()
                )
            )

        launcher_id = bytes32(singleton_struct.rest().first().as_atom())
        if derivation_record is None:
            raise ValueError(f"This DID {launcher_id} does not belong to the connected wallet")
        else:
            our_inner_puzzle: Program = self.service.wallet_state_manager.main_wallet.puzzle_for_pk(
                derivation_record.pubkey
            )
            did_puzzle = DID_INNERPUZ_MOD.curry(
                our_inner_puzzle, recovery_list_hash, num_verification, singleton_struct, metadata
            )
            full_puzzle = create_singleton_puzzle(did_puzzle, launcher_id)
            did_puzzle_empty_recovery = DID_INNERPUZ_MOD.curry(
                our_inner_puzzle, NIL_TREEHASH, uint64(0), singleton_struct, metadata
            )
            # Check if we have the DID wallet
            did_wallet: DIDWallet | None = None
            for wallet in self.service.wallet_state_manager.wallets.values():
                if isinstance(wallet, DIDWallet):
                    assert wallet.did_info.origin_coin is not None
                    if wallet.did_info.origin_coin.name() == launcher_id:
                        did_wallet = wallet
                        break

            full_puzzle_empty_recovery = create_singleton_puzzle(did_puzzle_empty_recovery, launcher_id)
            if full_puzzle.get_tree_hash() != coin_state.coin.puzzle_hash:
                # It's unclear whether this path is ever reached, and there is no coverage in the DID wallet tests
                if full_puzzle_empty_recovery.get_tree_hash() == coin_state.coin.puzzle_hash:
                    did_puzzle = did_puzzle_empty_recovery
                elif (
                    did_wallet is not None
                    and did_wallet.did_info.current_inner is not None
                    and create_singleton_puzzle(did_wallet.did_info.current_inner, launcher_id).get_tree_hash()
                    == coin_state.coin.puzzle_hash
                ):
                    # Check if the old wallet has the inner puzzle
                    did_puzzle = did_wallet.did_info.current_inner
                else:
                    # Try override
                    if request.recovery_list_hash is not None:
                        recovery_list_hash = Program.from_bytes(request.recovery_list_hash)
                    if request.num_verification is not None:
                        num_verification_int = request.num_verification
                    if request.metadata is not None:
                        metadata = metadata_to_program(request.metadata)
                    did_puzzle = DID_INNERPUZ_MOD.curry(
                        our_inner_puzzle, recovery_list_hash, num_verification, singleton_struct, metadata
                    )
                    full_puzzle = create_singleton_puzzle(did_puzzle, launcher_id)
                    matched = True
                    if full_puzzle.get_tree_hash() != coin_state.coin.puzzle_hash:
                        matched = False
                        # Brute force addresses
                        index = 0
                        derivation_record = await self.service.wallet_state_manager.puzzle_store.get_derivation_record(
                            uint32(index), uint32(1), False
                        )
                        while derivation_record is not None:
                            our_inner_puzzle = self.service.wallet_state_manager.main_wallet.puzzle_for_pk(
                                derivation_record.pubkey
                            )
                            did_puzzle = DID_INNERPUZ_MOD.curry(
                                our_inner_puzzle, recovery_list_hash, num_verification, singleton_struct, metadata
                            )
                            full_puzzle = create_singleton_puzzle(did_puzzle, launcher_id)
                            if full_puzzle.get_tree_hash() == coin_state.coin.puzzle_hash:
                                matched = True
                                break
                            index += 1
                            derivation_record = (
                                await self.service.wallet_state_manager.puzzle_store.get_derivation_record(
                                    uint32(index), uint32(1), False
                                )
                            )

                    if not matched:
                        raise RuntimeError(
                            f"Cannot recover DID {launcher_id} "
                            f"because the last spend updated recovery_list_hash/num_verification/metadata."
                        )

            if did_wallet is None:
                # Create DID wallet
                response: list[CoinState] = await self.service.get_coin_state([launcher_id], peer=peer)
                if len(response) == 0:
                    raise ValueError(f"Could not find the launch coin with ID: {launcher_id}")
                launcher_coin: CoinState = response[0]
                did_wallet = await DIDWallet.create_new_did_wallet_from_coin_spend(
                    self.service.wallet_state_manager,
                    self.service.wallet_state_manager.main_wallet,
                    launcher_coin.coin,
                    did_puzzle,
                    coin_spend,
                    f"DID {encode_puzzle_hash(launcher_id, AddressType.DID.hrp(self.service.config))}",
                )
            else:
                assert did_wallet.did_info.current_inner is not None
                if did_wallet.did_info.current_inner.get_tree_hash() != did_puzzle.get_tree_hash():
                    # Inner DID puzzle doesn't match, we need to update the DID info
                    full_solution: Program = Program.from_bytes(bytes(coin_spend.solution))
                    inner_solution: Program = full_solution.rest().rest().first()
                    recovery_list: list[bytes32] = []
                    backup_required: int = num_verification.as_int()
                    if not did_recovery_is_nil(recovery_list_hash):
                        try:
                            for did in inner_solution.rest().rest().rest().rest().rest().as_python():
                                recovery_list.append(did[0])
                        except Exception:
                            # We cannot recover the recovery list, but it's okay to leave it blank
                            pass
                    did_info: DIDInfo = DIDInfo(
                        did_wallet.did_info.origin_coin,
                        recovery_list,
                        uint64(backup_required),
                        [],
                        did_puzzle,
                        None,
                        None,
                        None,
                        False,
                        json.dumps(did_wallet_puzzles.did_program_to_metadata(metadata)),
                    )
                    await did_wallet.save_info(did_info)
                    await self.service.wallet_state_manager.update_wallet_puzzle_hashes(did_wallet.wallet_info.id)

            try:
                coin = await did_wallet.get_coin()
                if coin.name() == coin_state.coin.name():
                    return DIDFindLostDIDResponse(coin.name())
            except RuntimeError:
                # We don't have any coin for this wallet, add the coin
                pass

            wallet_id = did_wallet.id()
            wallet_type = did_wallet.type()
            assert coin_state.created_height is not None
            coin_record: WalletCoinRecord = WalletCoinRecord(
                coin_state.coin, uint32(coin_state.created_height), uint32(0), False, False, wallet_type, wallet_id
            )
            await self.service.wallet_state_manager.coin_store.add_coin_record(coin_record, coin_state.coin.name())
            await did_wallet.coin_added(
                coin_state.coin,
                uint32(coin_state.created_height),
                peer,
                did_data,
            )
            return DIDFindLostDIDResponse(coin_state.coin.name())

    @tx_endpoint(push=True)
    @marshal
    async def did_update_metadata(
        self,
        request: DIDUpdateMetadata,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> DIDUpdateMetadataResponse:
        wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=DIDWallet)
        async with self.service.wallet_state_manager.lock:
            update_success = await wallet.update_metadata(request.metadata)
            # Update coin with new ID info
            if update_success:
                await wallet.create_update_spend(action_scope, request.fee, extra_conditions=extra_conditions)
                # tx_endpoint wrapper will take care of these default values
                return DIDUpdateMetadataResponse(
                    [],
                    [],
                    wallet_id=request.wallet_id,
                    spend_bundle=WalletSpendBundle([], G2Element()),
                )
            else:
                raise ValueError(f"Couldn't update metadata with input: {request.metadata}")

    @marshal
    async def did_get_did(self, request: DIDGetDID) -> DIDGetDIDResponse:
        wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=DIDWallet)
        my_did: str = encode_puzzle_hash(bytes32.fromhex(wallet.get_my_DID()), AddressType.DID.hrp(self.service.config))
        async with self.service.wallet_state_manager.lock:
            try:
                coin = await wallet.get_coin()
                return DIDGetDIDResponse(wallet_id=request.wallet_id, my_did=my_did, coin_id=coin.name())
            except RuntimeError:
                return DIDGetDIDResponse(wallet_id=request.wallet_id, my_did=my_did)

    @marshal
    async def did_get_metadata(self, request: DIDGetMetadata) -> DIDGetMetadataResponse:
        wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=DIDWallet)
        metadata = json.loads(wallet.did_info.metadata)
        return DIDGetMetadataResponse(
            wallet_id=request.wallet_id,
            metadata=metadata,
        )

    @marshal
    async def did_get_pubkey(self, request: DIDGetPubkey) -> DIDGetPubkeyResponse:
        wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=DIDWallet)
        return DIDGetPubkeyResponse(
            (await wallet.wallet_state_manager.get_unused_derivation_record(request.wallet_id)).pubkey
        )

    @marshal
    async def did_get_current_coin_info(self, request: DIDGetCurrentCoinInfo) -> DIDGetCurrentCoinInfoResponse:
        did_wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=DIDWallet)
        my_did = encode_puzzle_hash(
            bytes32.from_hexstr(did_wallet.get_my_DID()), AddressType.DID.hrp(self.service.config)
        )

        assert did_wallet.did_info.current_inner is not None
        parent_coin = await did_wallet.get_coin()
        assert my_did is not None
        return DIDGetCurrentCoinInfoResponse(
            wallet_id=request.wallet_id,
            my_did=my_did,
            did_parent=parent_coin.parent_coin_info,
            did_innerpuz=did_wallet.did_info.current_inner.get_tree_hash(),
            did_amount=parent_coin.amount,
        )

    @marshal
    async def did_create_backup_file(self, request: DIDCreateBackupFile) -> DIDCreateBackupFileResponse:
        did_wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=DIDWallet)
        return DIDCreateBackupFileResponse(wallet_id=request.wallet_id, backup_data=did_wallet.create_backup())

    @tx_endpoint(push=True)
    @marshal
    async def did_transfer_did(
        self,
        request: DIDTransferDID,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> DIDTransferDIDResponse:
        did_wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=DIDWallet)
        puzzle_hash: bytes32 = decode_puzzle_hash(request.inner_address)
        async with self.service.wallet_state_manager.lock:
            await did_wallet.transfer_did(
                puzzle_hash,
                request.fee,
                action_scope,
                extra_conditions=extra_conditions,
            )

        # The tx_endpoint wrapper will take care of these default values
        return DIDTransferDIDResponse([], [], transaction=REPLACEABLE_TRANSACTION_RECORD, transaction_id=bytes32.zeros)

    ##########################################################################################
    # NFT Wallet
    ##########################################################################################
    @tx_endpoint(push=True)
    @marshal
    async def nft_mint_nft(
        self,
        request: NFTMintNFTRequest,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> NFTMintNFTResponse:
        log.debug("Got minting RPC request: %s", request)
        assert self.service.wallet_state_manager
        nft_wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=NFTWallet)
        if request.royalty_amount == 10000:
            raise ValueError("Royalty percentage cannot be 100%")
        if request.royalty_address is not None:
            royalty_puzhash = decode_puzzle_hash(request.royalty_address)
        else:
            royalty_puzhash = await action_scope.get_puzzle_hash(self.service.wallet_state_manager)
        if request.target_address is not None:
            target_puzhash = decode_puzzle_hash(request.target_address)
        else:
            target_puzhash = await action_scope.get_puzzle_hash(self.service.wallet_state_manager)
        metadata_list = [
            ("u", request.uris),
            ("h", request.hash),
            ("mu", request.meta_uris),
            ("lu", request.license_uris),
            ("sn", request.edition_number),
            ("st", request.edition_total),
        ]
        if request.meta_hash is not None:
            metadata_list.append(("mh", request.meta_hash))
        if request.license_hash is not None:
            metadata_list.append(("lh", request.license_hash))
        metadata = Program.to(metadata_list)
        if request.did_id is not None:
            if request.did_id == "":
                did_id: bytes | None = b""
            else:
                did_id = decode_puzzle_hash(request.did_id)
        else:
            did_id = request.did_id

        nft_id = await nft_wallet.generate_new_nft(
            metadata,
            action_scope,
            target_puzhash,
            royalty_puzhash,
            request.royalty_amount,
            did_id,
            request.fee,
            extra_conditions=extra_conditions,
        )
        nft_id_bech32 = encode_puzzle_hash(nft_id, AddressType.NFT.hrp(self.service.config))
        return NFTMintNFTResponse(
            [],
            [],
            wallet_id=request.wallet_id,
            spend_bundle=WalletSpendBundle([], G2Element()),  # tx_endpoint wrapper will take care of this
            nft_id=nft_id_bech32,
        )

    @marshal
    async def nft_count_nfts(self, request: NFTCountNFTs) -> NFTCountNFTsResponse:
        count = 0
        if request.wallet_id is not None:
            count = await self.service.wallet_state_manager.get_wallet(
                id=request.wallet_id, required_type=NFTWallet
            ).get_nft_count()
        else:
            count = await self.service.wallet_state_manager.nft_store.count()
        return NFTCountNFTsResponse(request.wallet_id, uint64(count))

    @marshal
    async def nft_get_nfts(self, request: NFTGetNFTs) -> NFTGetNFTsResponse:
        nfts: list[NFTCoinInfo] = []
        if request.wallet_id is not None:
            nft_wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=NFTWallet)
        else:
            nft_wallet = None
        nft_info_list = []
        if nft_wallet is not None:
            nfts = await nft_wallet.get_current_nfts(start_index=request.start_index, count=request.num)
        else:
            nfts = await self.service.wallet_state_manager.nft_store.get_nft_list(
                start_index=request.start_index, count=request.num
            )
        for nft in nfts:
            nft_info = await nft_puzzle_utils.get_nft_info_from_puzzle(nft, self.service.wallet_state_manager.config)
            nft_info_list.append(nft_info)
        return NFTGetNFTsResponse(request.wallet_id, nft_info_list)

    @tx_endpoint(push=True)
    @marshal
    async def nft_set_nft_did(
        self,
        request: NFTSetNFTDID,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> NFTSetNFTDIDResponse:
        nft_wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=NFTWallet)
        if request.did_id is not None:
            did_id: bytes = decode_puzzle_hash(request.did_id)
        else:
            did_id = b""
        nft_coin_info = await nft_wallet.get_nft_coin_by_id(request.nft_coin_id)
        if not (
            await nft_puzzle_utils.get_nft_info_from_puzzle(nft_coin_info, self.service.wallet_state_manager.config)
        ).supports_did:
            raise ValueError("The NFT doesn't support setting a DID.")

        await nft_wallet.set_nft_did(
            nft_coin_info,
            did_id,
            action_scope,
            fee=request.fee,
            extra_conditions=extra_conditions,
        )
        # tx_endpoint wrapper takes care of setting most of these default values
        return NFTSetNFTDIDResponse([], [], request.wallet_id, WalletSpendBundle([], G2Element()))

    @tx_endpoint(push=True)
    @marshal
    async def nft_set_did_bulk(
        self,
        request: NFTSetDIDBulk,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> NFTSetDIDBulkResponse:
        """
        Bulk set DID for NFTs across different wallets.
        accepted `request` dict keys:
         - required `nft_coin_list`: [{"nft_coin_id": COIN_ID/NFT_ID, "wallet_id": WALLET_ID},....]
         - optional `fee`, in mojos, defaults to 0
         - optional `did_id`, defaults to no DID, meaning it will reset the NFT's DID
        :param request:
        :return:
        """
        if len(request.nft_coin_list) > MAX_NFT_CHUNK_SIZE:
            raise ValueError(f"You can only set {MAX_NFT_CHUNK_SIZE} NFTs at once")

        if request.did_id is not None:
            did_id: bytes = decode_puzzle_hash(request.did_id)
        else:
            did_id = b""
        nft_dict: dict[uint32, list[NFTCoinInfo]] = {}
        coin_ids = []
        nft_ids = []

        nft_wallet: NFTWallet
        for nft_coin in request.nft_coin_list:
            nft_wallet = self.service.wallet_state_manager.get_wallet(id=nft_coin.wallet_id, required_type=NFTWallet)
            if nft_coin.nft_coin_id.startswith(AddressType.NFT.hrp(self.service.config)):
                nft_coin_info = await nft_wallet.get_nft(decode_puzzle_hash(nft_coin.nft_coin_id))
            else:
                nft_coin_info = await nft_wallet.get_nft_coin_by_id(bytes32.from_hexstr(nft_coin.nft_coin_id))
            assert nft_coin_info is not None
            if not (
                await nft_puzzle_utils.get_nft_info_from_puzzle(nft_coin_info, self.service.wallet_state_manager.config)
            ).supports_did:
                log.warning(f"Skipping NFT {nft_coin_info.nft_id.hex()}, doesn't support setting a DID.")
                continue
            if nft_coin.wallet_id in nft_dict:
                nft_dict[nft_coin.wallet_id].append(nft_coin_info)
            else:
                nft_dict[nft_coin.wallet_id] = [nft_coin_info]
            nft_ids.append(nft_coin_info.nft_id)
        first = True
        for wallet_id, nft_list in nft_dict.items():
            nft_wallet = self.service.wallet_state_manager.get_wallet(id=wallet_id, required_type=NFTWallet)
            if not first:
                await nft_wallet.set_bulk_nft_did(nft_list, did_id, action_scope, extra_conditions=extra_conditions)
            else:
                await nft_wallet.set_bulk_nft_did(
                    nft_list, did_id, action_scope, request.fee, nft_ids, extra_conditions=extra_conditions
                )
            for coin in nft_list:
                coin_ids.append(coin.coin.name())
            first = False

        for id in coin_ids:
            await nft_wallet.update_coin_status(id, True)
        for wallet_id in nft_dict.keys():
            self.service.wallet_state_manager.state_changed("nft_coin_did_set", wallet_id)

        async with action_scope.use() as interface:
            return NFTSetDIDBulkResponse(
                [],
                [],
                wallet_id=list(nft_dict.keys()),
                spend_bundle=WalletSpendBundle([], G2Element()),
                tx_num=uint16(len(interface.side_effects.transactions)),
            )

    @tx_endpoint(push=True)
    @marshal
    async def nft_transfer_bulk(
        self,
        request: NFTTransferBulk,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> NFTTransferBulkResponse:
        """
        Bulk transfer NFTs to an address.
        accepted `request` dict keys:
         - required `nft_coin_list`: [{"nft_coin_id": COIN_ID/NFT_ID, "wallet_id": WALLET_ID},....]
         - required `target_address`, Transfer NFTs to this address
         - optional `fee`, in mojos, defaults to 0
        :param request:
        :return:
        """
        if len(request.nft_coin_list) > MAX_NFT_CHUNK_SIZE:
            raise ValueError(f"You can only transfer {MAX_NFT_CHUNK_SIZE} NFTs at once")
        address = request.target_address
        puzzle_hash = decode_puzzle_hash(address)
        nft_dict: dict[uint32, list[NFTCoinInfo]] = {}
        coin_ids = []

        nft_wallet: NFTWallet
        for nft_coin in request.nft_coin_list:
            nft_wallet = self.service.wallet_state_manager.get_wallet(id=nft_coin.wallet_id, required_type=NFTWallet)
            nft_coin_id = nft_coin.nft_coin_id
            if nft_coin_id.startswith(AddressType.NFT.hrp(self.service.config)):
                nft_coin_info = await nft_wallet.get_nft(decode_puzzle_hash(nft_coin_id))
            else:
                nft_coin_info = await nft_wallet.get_nft_coin_by_id(bytes32.from_hexstr(nft_coin_id))
            assert nft_coin_info is not None
            if nft_coin.wallet_id in nft_dict:
                nft_dict[nft_coin.wallet_id].append(nft_coin_info)
            else:
                nft_dict[nft_coin.wallet_id] = [nft_coin_info]
        first = True
        for wallet_id, nft_list in nft_dict.items():
            nft_wallet = self.service.wallet_state_manager.get_wallet(id=wallet_id, required_type=NFTWallet)
            if not first:
                await nft_wallet.bulk_transfer_nft(
                    nft_list, puzzle_hash, action_scope, extra_conditions=extra_conditions
                )
            else:
                await nft_wallet.bulk_transfer_nft(
                    nft_list, puzzle_hash, action_scope, request.fee, extra_conditions=extra_conditions
                )
            for coin in nft_list:
                coin_ids.append(coin.coin.name())
            first = False

        for id in coin_ids:
            await nft_wallet.update_coin_status(id, True)
        for wallet_id in nft_dict.keys():
            self.service.wallet_state_manager.state_changed("nft_coin_did_set", wallet_id)
        async with action_scope.use() as interface:
            return NFTTransferBulkResponse(
                [],
                [],
                wallet_id=list(nft_dict.keys()),
                spend_bundle=WalletSpendBundle([], G2Element()),
                tx_num=uint16(len(interface.side_effects.transactions)),
            )

    @marshal
    async def nft_get_by_did(self, request: NFTGetByDID) -> NFTGetByDIDResponse:
        did_id: bytes32 | None = None
        if request.did_id is not None:
            did_id = decode_puzzle_hash(request.did_id)
        for wallet in self.service.wallet_state_manager.wallets.values():
            if isinstance(wallet, NFTWallet) and wallet.get_did() == did_id:
                return NFTGetByDIDResponse(uint32(wallet.wallet_id))
        raise ValueError(f"Cannot find a NFT wallet DID = {did_id}")

    @marshal
    async def nft_get_wallet_did(self, request: NFTGetWalletDID) -> NFTGetWalletDIDResponse:
        nft_wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=NFTWallet)
        did_bytes: bytes32 | None = nft_wallet.get_did()
        did_id = ""
        if did_bytes is not None:
            did_id = encode_puzzle_hash(did_bytes, AddressType.DID.hrp(self.service.config))
        return NFTGetWalletDIDResponse(None if len(did_id) == 0 else did_id)

    @marshal
    async def nft_get_wallets_with_dids(self, request: Empty) -> NFTGetWalletsWithDIDsResponse:
        all_wallets = self.service.wallet_state_manager.wallets.values()
        did_wallets_by_did_id: dict[bytes32, uint32] = {}

        for wallet in all_wallets:
            if wallet.type() == WalletType.DECENTRALIZED_ID:
                assert isinstance(wallet, DIDWallet)
                if wallet.did_info.origin_coin is not None:
                    did_wallets_by_did_id[wallet.did_info.origin_coin.name()] = wallet.id()

        did_nft_wallets: list[NFTWalletWithDID] = []
        for wallet in all_wallets:
            if isinstance(wallet, NFTWallet):
                nft_wallet_did: bytes32 | None = wallet.get_did()
                if nft_wallet_did is not None:
                    did_wallet_id: uint32 = did_wallets_by_did_id.get(nft_wallet_did, uint32(0))
                    if did_wallet_id == 0:
                        log.warning(f"NFT wallet {wallet.id()} has DID {nft_wallet_did.hex()} but no DID wallet")
                    else:
                        did_nft_wallets.append(
                            NFTWalletWithDID(
                                wallet_id=wallet.id(),
                                did_id=encode_puzzle_hash(nft_wallet_did, AddressType.DID.hrp(self.service.config)),
                                did_wallet_id=did_wallet_id,
                            )
                        )
        return NFTGetWalletsWithDIDsResponse(did_nft_wallets)

    @marshal
    async def nft_set_nft_status(self, request: NFTSetNFTStatus) -> Empty:
        assert self.service.wallet_state_manager is not None
        nft_wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=NFTWallet)
        await nft_wallet.update_coin_status(request.coin_id, request.in_transaction)
        return Empty()

    @tx_endpoint(push=True)
    @marshal
    async def nft_transfer_nft(
        self,
        request: NFTTransferNFT,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> NFTTransferNFTResponse:
        puzzle_hash = decode_puzzle_hash(request.target_address)
        nft_wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=NFTWallet)
        nft_coin_id = request.nft_coin_id
        if nft_coin_id.startswith(AddressType.NFT.hrp(self.service.config)):
            nft_coin_info = await nft_wallet.get_nft(decode_puzzle_hash(nft_coin_id))
        else:
            nft_coin_info = await nft_wallet.get_nft_coin_by_id(bytes32.from_hexstr(nft_coin_id))
        assert nft_coin_info is not None

        await nft_wallet.generate_signed_transaction(
            [uint64(nft_coin_info.coin.amount)],
            [puzzle_hash],
            action_scope,
            coins={nft_coin_info.coin},
            fee=request.fee,
            new_owner=b"",
            new_did_inner_hash=b"",
            extra_conditions=extra_conditions,
        )
        await nft_wallet.update_coin_status(nft_coin_info.coin.name(), True)
        # tx_endpoint takes care of filling in default values here
        return NFTTransferNFTResponse([], [], request.wallet_id, WalletSpendBundle([], G2Element()))

    @marshal
    async def nft_get_info(self, request: NFTGetInfo) -> NFTGetInfoResponse:
        if request.coin_id.startswith(AddressType.NFT.hrp(self.service.config)):
            coin_id = decode_puzzle_hash(request.coin_id)
        else:
            try:
                coin_id = bytes32.from_hexstr(request.coin_id)
            except ValueError:
                raise ValueError(f"Invalid Coin ID format for 'coin_id': {request.coin_id!r}")
        # Get coin state
        peer = self.service.get_full_node_peer()
        coin_spend, coin_state = await self.get_latest_singleton_coin_spend(peer, coin_id, request.latest)
        # convert to NFTInfo
        # Check if the metadata is updated
        full_puzzle: Program = Program.from_bytes(bytes(coin_spend.puzzle_reveal))

        uncurried_nft: UncurriedNFT | None = UncurriedNFT.uncurry(*full_puzzle.uncurry())
        if uncurried_nft is None:
            raise ValueError("The coin is not a NFT.")
        metadata, p2_puzzle_hash = get_metadata_and_phs(uncurried_nft, coin_spend.solution)
        # Note: This is not the actual unspent NFT full puzzle.
        # There is no way to rebuild the full puzzle in a different wallet.
        # But it shouldn't have impact on generating the NFTInfo, since inner_puzzle is not used there.
        if uncurried_nft.supports_did:
            inner_puzzle = nft_puzzle_utils.recurry_nft_puzzle(
                uncurried_nft, Program.from_serialized(coin_spend.solution), uncurried_nft.p2_puzzle
            )
        else:
            inner_puzzle = uncurried_nft.p2_puzzle

        full_puzzle = nft_puzzle_utils.create_full_puzzle(
            uncurried_nft.singleton_launcher_id,
            metadata,
            bytes32(uncurried_nft.metadata_updater_hash.as_atom()),
            inner_puzzle,
        )

        # Get launcher coin
        launcher_coin: list[CoinState] = await self.service.wallet_state_manager.wallet_node.get_coin_state(
            [uncurried_nft.singleton_launcher_id], peer=peer
        )
        if launcher_coin is None or len(launcher_coin) < 1 or launcher_coin[0].spent_height is None:
            raise ValueError(f"Launcher coin record 0x{uncurried_nft.singleton_launcher_id.hex()} not found")
        minter_did = await self.service.wallet_state_manager.get_minter_did(launcher_coin[0].coin, peer)

        nft_info: NFTInfo = await nft_puzzle_utils.get_nft_info_from_puzzle(
            NFTCoinInfo(
                uncurried_nft.singleton_launcher_id,
                coin_state.coin,
                None,
                full_puzzle,
                uint32(launcher_coin[0].spent_height),
                minter_did,
                uint32(coin_state.created_height) if coin_state.created_height else uint32(0),
            ),
            self.service.wallet_state_manager.config,
        )
        # This is a bit hacky, it should just come out like this, but this works for this RPC
        nft_info = dataclasses.replace(nft_info, p2_address=p2_puzzle_hash)
        return NFTGetInfoResponse(nft_info)

    @tx_endpoint(push=True)
    @marshal
    async def nft_add_uri(
        self,
        request: NFTAddURI,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> NFTAddURIResponse:
        # Note metadata updater can only add one uri for one field per spend.
        # If you want to add multiple uris for one field, you need to spend multiple times.
        nft_wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=NFTWallet)
        if request.nft_coin_id.startswith(AddressType.NFT.hrp(self.service.config)):
            nft_coin_id = decode_puzzle_hash(request.nft_coin_id)
        else:
            nft_coin_id = bytes32.from_hexstr(request.nft_coin_id)
        nft_coin_info = await nft_wallet.get_nft_coin_by_id(nft_coin_id)

        await nft_wallet.update_metadata(
            nft_coin_info, request.key, request.uri, action_scope, fee=request.fee, extra_conditions=extra_conditions
        )
        # tx_endpoint takes care of setting the default values here
        return NFTAddURIResponse([], [], request.wallet_id, WalletSpendBundle([], G2Element()))

    @marshal
    async def nft_calculate_royalties(self, request: NFTCalculateRoyalties) -> NFTCalculateRoyaltiesResponse:
        return NFTCalculateRoyaltiesResponse.from_json_dict(
            NFTWallet.royalty_calculation(
                {
                    asset.asset: (asset.royalty_address, uint16(asset.royalty_percentage))
                    for asset in request.royalty_assets
                },
                {asset.asset: asset.amount for asset in request.fungible_assets},
            )
        )

    @tx_endpoint(push=False)
    @marshal
    async def nft_mint_bulk(
        self,
        request: NFTMintBulk,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> NFTMintBulkResponse:
        if action_scope.config.push:
            raise ValueError("Automatic pushing of nft minting transactions not yet available")  # pragma: no cover
        nft_wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=NFTWallet)
        if request.royalty_address in {None, ""}:
            royalty_puzhash = await action_scope.get_puzzle_hash(self.service.wallet_state_manager)
        else:
            assert request.royalty_address is not None  # hello mypy
            royalty_puzhash = decode_puzzle_hash(request.royalty_address)
        metadata_list = []
        for meta in request.metadata_list:
            nft_metadata = [
                ("u", meta.uris),
                ("h", meta.hash),
                ("mu", meta.meta_uris),
                ("lu", meta.license_uris),
                ("sn", meta.edition_number),
                ("st", meta.edition_total),
            ]
            if meta.meta_hash is not None:
                nft_metadata.append(("mh", meta.meta_hash))
            if meta.license_hash is not None:
                nft_metadata.append(("lh", meta.license_hash))
            metadata_program = Program.to(nft_metadata)
            metadata_dict = {
                "program": metadata_program,
                "royalty_pc": request.royalty_percentage,
                "royalty_ph": royalty_puzhash,
            }
            metadata_list.append(metadata_dict)
        target_list = [decode_puzzle_hash(target) for target in request.target_list]
        if request.xch_change_target is not None:
            if request.xch_change_target.startswith(AddressType.XCH.hrp(self.service.config)):
                xch_change_ph = decode_puzzle_hash(request.xch_change_target)
            else:
                xch_change_ph = bytes32.from_hexstr(request.xch_change_target)
        else:
            xch_change_ph = None

        if request.mint_from_did:
            await nft_wallet.mint_from_did(
                metadata_list,
                mint_number_start=request.mint_number_start,
                mint_total=request.mint_total,
                target_list=target_list,
                xch_coins=set(request.xch_coins) if request.xch_coins is not None else None,
                xch_change_ph=xch_change_ph,
                new_innerpuzhash=request.new_innerpuzhash,
                new_p2_puzhash=request.new_p2_puzhash,
                did_coin=request.did_coin,
                did_lineage_parent=request.did_lineage_parent,
                fee=request.fee,
                action_scope=action_scope,
                extra_conditions=extra_conditions,
            )
        else:
            await nft_wallet.mint_from_xch(
                metadata_list,
                mint_number_start=request.mint_number_start,
                mint_total=request.mint_total,
                target_list=target_list,
                xch_coins=set(request.xch_coins) if request.xch_coins is not None else None,
                xch_change_ph=xch_change_ph,
                fee=request.fee,
                action_scope=action_scope,
                extra_conditions=extra_conditions,
            )
        async with action_scope.use() as interface:
            sb = WalletSpendBundle.aggregate(
                [tx.spend_bundle for tx in interface.side_effects.transactions if tx.spend_bundle is not None]
                + [sb for sb in interface.side_effects.extra_spends]
            )
        nft_id_list = []
        for cs in sb.coin_spends:
            if cs.coin.puzzle_hash == SINGLETON_LAUNCHER_PUZZLE_HASH:
                nft_id_list.append(encode_puzzle_hash(cs.coin.name(), AddressType.NFT.hrp(self.service.config)))

        # tx_endpoint will take care of the default values here
        return NFTMintBulkResponse(
            [],
            [],
            WalletSpendBundle([], G2Element()),
            nft_id_list,
        )

    async def get_coin_records(self, request: dict[str, Any]) -> EndpointResult:
        parsed_request = GetCoinRecords.from_json_dict(request)

        if parsed_request.limit != uint32.MAXIMUM and parsed_request.limit > self.max_get_coin_records_limit:
            raise ValueError(f"limit of {self.max_get_coin_records_limit} exceeded: {parsed_request.limit}")

        for filter_name, filter in {
            "coin_id_filter": parsed_request.coin_id_filter,
            "puzzle_hash_filter": parsed_request.puzzle_hash_filter,
            "parent_coin_id_filter": parsed_request.parent_coin_id_filter,
            "amount_filter": parsed_request.amount_filter,
        }.items():
            if filter is None:
                continue
            if len(filter.values) > self.max_get_coin_records_filter_items:
                raise ValueError(
                    f"{filter_name} max items {self.max_get_coin_records_filter_items} exceeded: {len(filter.values)}"
                )

        result = await self.service.wallet_state_manager.coin_store.get_coin_records(
            offset=parsed_request.offset,
            limit=parsed_request.limit,
            wallet_id=parsed_request.wallet_id,
            wallet_type=None if parsed_request.wallet_type is None else WalletType(parsed_request.wallet_type),
            coin_type=None if parsed_request.coin_type is None else CoinType(parsed_request.coin_type),
            coin_id_filter=parsed_request.coin_id_filter,
            puzzle_hash_filter=parsed_request.puzzle_hash_filter,
            parent_coin_id_filter=parsed_request.parent_coin_id_filter,
            amount_filter=parsed_request.amount_filter,
            amount_range=parsed_request.amount_range,
            confirmed_range=parsed_request.confirmed_range,
            spent_range=parsed_request.spent_range,
            order=CoinRecordOrder(parsed_request.order),
            reverse=parsed_request.reverse,
            include_total_count=parsed_request.include_total_count,
        )

        return {
            "coin_records": [coin_record.to_json_dict_parsed_metadata() for coin_record in result.records],
            "total_count": result.total_count,
        }

    async def get_farmed_amount(self, request: dict[str, Any]) -> EndpointResult:
        tx_records: list[TransactionRecord] = await self.service.wallet_state_manager.tx_store.get_farming_rewards()
        amount = 0
        pool_reward_amount = 0
        farmer_reward_amount = 0
        fee_amount = 0
        blocks_won = 0
        last_height_farmed = uint32(0)

        include_pool_rewards = request.get("include_pool_rewards", False)

        for record in tx_records:
            if record.wallet_id not in self.service.wallet_state_manager.wallets:
                continue
            if record.type == TransactionType.COINBASE_REWARD.value:
                if (
                    not include_pool_rewards
                    and self.service.wallet_state_manager.wallets[record.wallet_id].type() == WalletType.POOLING_WALLET
                ):
                    # Don't add pool rewards for pool wallets unless explicitly requested
                    continue
                pool_reward_amount += record.amount
            height = record.height_farmed(self.service.constants.GENESIS_CHALLENGE)
            # .get_farming_rewards() above queries for only confirmed records.  This
            # could be hinted by making TransactionRecord generic but streamable can't
            # handle that presently.  Existing code would have raised an exception
            # anyway if this were to fail and we already have an assert below.
            assert height is not None
            if record.type == TransactionType.FEE_REWARD.value:
                base_farmer_reward = calculate_base_farmer_reward(height)
                fee_amount += record.amount - base_farmer_reward
                farmer_reward_amount += base_farmer_reward
                blocks_won += 1
            last_height_farmed = max(last_height_farmed, height)
            amount += record.amount

        last_time_farmed = uint64(
            await self.service.get_timestamp_for_height(last_height_farmed) if last_height_farmed > 0 else 0
        )
        assert amount == pool_reward_amount + farmer_reward_amount + fee_amount
        return {
            "farmed_amount": amount,
            "pool_reward_amount": pool_reward_amount,
            "farmer_reward_amount": farmer_reward_amount,
            "fee_amount": fee_amount,
            "last_height_farmed": last_height_farmed,
            "last_time_farmed": last_time_farmed,
            "blocks_won": blocks_won,
        }

    @tx_endpoint(push=False)
    @marshal
    async def create_signed_transaction(
        self,
        request: CreateSignedTransaction,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
        hold_lock: bool = True,
    ) -> CreateSignedTransactionsResponse:
        if request.wallet_id is not None:
            wallet = self.service.wallet_state_manager.wallets[request.wallet_id]
        else:
            wallet = self.service.wallet_state_manager.main_wallet

        assert isinstance(wallet, (Wallet, CATWallet, CRCATWallet, RCATWallet)), (
            "create_signed_transaction only works for standard and CAT wallets"
        )

        if len(request.additions) < 1:
            raise ValueError("Specify additions list")

        amount_0: uint64 = uint64(request.additions[0].amount)
        assert amount_0 <= self.service.constants.MAX_COIN_AMOUNT
        puzzle_hash_0 = request.additions[0].puzzle_hash
        if len(puzzle_hash_0) != 32:
            raise ValueError(f"Address must be 32 bytes. {puzzle_hash_0.hex()}")

        memos_0 = (
            [] if request.additions[0].memos is None else [mem.encode("utf-8") for mem in request.additions[0].memos]
        )

        additional_outputs: list[CreateCoin] = []
        for addition in request.additions[1:]:
            if addition.amount > self.service.constants.MAX_COIN_AMOUNT:
                raise ValueError(f"Coin amount cannot exceed {self.service.constants.MAX_COIN_AMOUNT}")
            memos = [] if addition.memos is None else [mem.encode("utf-8") for mem in addition.memos]
            additional_outputs.append(CreateCoin(addition.puzzle_hash, addition.amount, memos))

        async def _generate_signed_transaction() -> CreateSignedTransactionsResponse:
            await wallet.generate_signed_transaction(
                [amount_0] + [output.amount for output in additional_outputs],
                [bytes32(puzzle_hash_0)] + [output.puzzle_hash for output in additional_outputs],
                action_scope,
                request.fee,
                coins=request.coin_set,
                memos=[memos_0] + [output.memos if output.memos is not None else [] for output in additional_outputs],
                extra_conditions=(
                    *extra_conditions,
                    *request.asserted_coin_announcements,
                    *request.asserted_puzzle_announcements,
                ),
            )
            # tx_endpoint wrapper will take care of these default values
            return CreateSignedTransactionsResponse([], [], [], REPLACEABLE_TRANSACTION_RECORD)

        if hold_lock:
            async with self.service.wallet_state_manager.lock:
                return await _generate_signed_transaction()
        else:
            return await _generate_signed_transaction()

    ##########################################################################################
    # Pool Wallet
    ##########################################################################################
    @tx_endpoint(push=True)
    @marshal
    async def pw_join_pool(
        self,
        request: PWJoinPool,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> PWJoinPoolResponse:
        wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=PoolWallet)

        pool_wallet_info: PoolWalletInfo = await wallet.get_current_state()
        if (
            pool_wallet_info.current.state == FARMING_TO_POOL.value
            and pool_wallet_info.current.pool_url == request.pool_url
        ):
            raise ValueError(f"Already farming to pool {pool_wallet_info.current.pool_url}")

        owner_pubkey = pool_wallet_info.current.owner_pubkey
        new_target_state: PoolState = create_pool_state(
            FARMING_TO_POOL,
            request.target_puzzlehash,
            owner_pubkey,
            request.pool_url,
            request.relative_lock_height,
        )

        total_fee = await wallet.join_pool(new_target_state, request.fee, action_scope)
        # tx_endpoint will take care of filling in these default values
        return PWJoinPoolResponse(
            [],
            [],
            total_fee=total_fee,
            transaction=REPLACEABLE_TRANSACTION_RECORD,
            fee_transaction=REPLACEABLE_TRANSACTION_RECORD,
        )

    @tx_endpoint(push=True)
    @marshal
    async def pw_self_pool(
        self,
        request: PWSelfPool,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> PWSelfPoolResponse:
        # Leaving a pool requires two state transitions.
        # First we transition to PoolSingletonState.LEAVING_POOL
        # Then we transition to FARMING_TO_POOL or SELF_POOLING
        wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=PoolWallet)

        total_fee = await wallet.self_pool(request.fee, action_scope)
        # tx_endpoint will take care of filling in these default values
        return PWSelfPoolResponse(
            [],
            [],
            total_fee=total_fee,
            transaction=REPLACEABLE_TRANSACTION_RECORD,
            fee_transaction=REPLACEABLE_TRANSACTION_RECORD,
        )

    @tx_endpoint(push=True)
    @marshal
    async def pw_absorb_rewards(
        self,
        request: PWAbsorbRewards,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> PWAbsorbRewardsResponse:
        """Perform a sweep of the p2_singleton rewards controlled by the pool wallet singleton"""
        wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=PoolWallet)

        assert isinstance(wallet, PoolWallet)
        async with self.service.wallet_state_manager.lock:
            await wallet.claim_pool_rewards(request.fee, request.max_spends_in_tx, action_scope)
            state: PoolWalletInfo = await wallet.get_current_state()
            return PWAbsorbRewardsResponse(
                [],
                [],
                state=state,
                transaction=REPLACEABLE_TRANSACTION_RECORD,
                fee_transaction=REPLACEABLE_TRANSACTION_RECORD,
            )

    @marshal
    async def pw_status(self, request: PWStatus) -> PWStatusResponse:
        """Return the complete state of the Pool wallet with id `request["wallet_id"]`"""
        wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=PoolWallet)

        assert isinstance(wallet, PoolWallet)
        state: PoolWalletInfo = await wallet.get_current_state()
        unconfirmed_transactions: list[TransactionRecord] = await wallet.get_unconfirmed_transactions()
        return PWStatusResponse(
            state=state,
            unconfirmed_transactions=unconfirmed_transactions,
        )

    ##########################################################################################
    # DataLayer Wallet
    ##########################################################################################
    @tx_endpoint(push=True)
    @marshal
    async def create_new_dl(
        self,
        request: CreateNewDL,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> CreateNewDLResponse:
        """Initialize the DataLayer Wallet (only one can exist)"""
        if self.service.wallet_state_manager is None:
            raise ValueError("The wallet service is not currently initialized")

        try:
            dl_wallet = self.service.wallet_state_manager.get_dl_wallet()
        except ValueError:
            async with self.service.wallet_state_manager.lock:
                dl_wallet = await DataLayerWallet.create_new_dl_wallet(self.service.wallet_state_manager)

        async with self.service.wallet_state_manager.lock:
            launcher_id = await dl_wallet.generate_new_reporter(
                request.root,
                action_scope,
                fee=request.fee,
                extra_conditions=extra_conditions,
            )

        # tx_endpoint will take care of these default values
        return CreateNewDLResponse([], [], launcher_id=launcher_id)

    @marshal
    async def dl_track_new(self, request: DLTrackNew) -> Empty:
        """Initialize the DataLayer Wallet (only one can exist)"""
        if self.service.wallet_state_manager is None:
            raise ValueError("The wallet service is not currently initialized")
        try:
            dl_wallet = self.service.wallet_state_manager.get_dl_wallet()
        except ValueError:
            async with self.service.wallet_state_manager.lock:
                dl_wallet = await DataLayerWallet.create_new_dl_wallet(
                    self.service.wallet_state_manager,
                )
        peer_list = self.service.get_full_node_peers_in_order()
        peer_length = len(peer_list)
        for i, peer in enumerate(peer_list):
            try:
                await dl_wallet.track_new_launcher_id(
                    request.launcher_id,
                    peer,
                )
            except LauncherCoinNotFoundError as e:
                if i == peer_length - 1:
                    raise e  # raise the error if we've tried all peers
                continue  # try some other peers, maybe someone has it
        return Empty()

    @marshal
    async def dl_stop_tracking(self, request: DLStopTracking) -> Empty:
        """Initialize the DataLayer Wallet (only one can exist)"""
        if self.service.wallet_state_manager is None:
            raise ValueError("The wallet service is not currently initialized")

        dl_wallet = self.service.wallet_state_manager.get_dl_wallet()
        await dl_wallet.stop_tracking_singleton(request.launcher_id)
        return Empty()

    @marshal
    async def dl_latest_singleton(self, request: DLLatestSingleton) -> DLLatestSingletonResponse:
        """Get the singleton record for the latest singleton of a launcher ID"""
        if self.service.wallet_state_manager is None:
            raise ValueError("The wallet service is not currently initialized")

        wallet = self.service.wallet_state_manager.get_dl_wallet()
        record = await wallet.get_latest_singleton(request.launcher_id, request.only_confirmed)
        return DLLatestSingletonResponse(record)

    @marshal
    async def dl_singletons_by_root(self, request: DLSingletonsByRoot) -> DLSingletonsByRootResponse:
        """Get the singleton records that contain the specified root"""
        if self.service.wallet_state_manager is None:
            raise ValueError("The wallet service is not currently initialized")

        wallet = self.service.wallet_state_manager.get_dl_wallet()
        records = await wallet.get_singletons_by_root(request.launcher_id, request.root)
        return DLSingletonsByRootResponse(records)

    @tx_endpoint(push=True)
    @marshal
    async def dl_update_root(
        self,
        request: DLUpdateRoot,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> DLUpdateRootResponse:
        """Get the singleton record for the latest singleton of a launcher ID"""
        if self.service.wallet_state_manager is None:
            raise ValueError("The wallet service is not currently initialized")

        wallet = self.service.wallet_state_manager.get_dl_wallet()
        async with self.service.wallet_state_manager.lock:
            await wallet.create_update_state_spend(
                request.launcher_id,
                request.new_root,
                action_scope,
                fee=request.fee,
                extra_conditions=extra_conditions,
            )

        # tx_endpoint will take care of default values here
        return DLUpdateRootResponse(
            [],
            [],
            REPLACEABLE_TRANSACTION_RECORD,
        )

    @tx_endpoint(push=True)
    @marshal
    async def dl_update_multiple(
        self,
        request: DLUpdateMultiple,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> DLUpdateMultipleResponse:
        """Update multiple singletons with new merkle roots"""
        if self.service.wallet_state_manager is None:
            raise RuntimeError("not initialized")

        wallet = self.service.wallet_state_manager.get_dl_wallet()
        async with self.service.wallet_state_manager.lock:
            # TODO: This method should optionally link the singletons with announcements.
            #       Otherwise spends are vulnerable to signature subtraction.
            # TODO: This method should natively support spending many and attaching one fee
            fee_per_launcher = uint64(request.fee // len(request.updates.launcher_root_pairs))
            for launcher_root_pair in request.updates.launcher_root_pairs:
                await wallet.create_update_state_spend(
                    launcher_root_pair.launcher_id,
                    launcher_root_pair.new_root,
                    action_scope,
                    fee=fee_per_launcher,
                    extra_conditions=extra_conditions,
                )

            # tx_endpoint will take care of default values here
            return DLUpdateMultipleResponse(
                [],
                [],
            )

    @marshal
    async def dl_history(self, request: DLHistory) -> DLHistoryResponse:
        """Get the singleton record for the latest singleton of a launcher ID"""
        if self.service.wallet_state_manager is None:
            raise ValueError("The wallet service is not currently initialized")

        wallet = self.service.wallet_state_manager.get_dl_wallet()
        additional_kwargs = {}

        if request.min_generation is not None:
            additional_kwargs["min_generation"] = uint32(request.min_generation)
        if request.max_generation is not None:
            additional_kwargs["max_generation"] = uint32(request.max_generation)
        if request.num_results is not None:
            additional_kwargs["num_results"] = uint32(request.num_results)

        history = await wallet.get_history(request.launcher_id, **additional_kwargs)
        return DLHistoryResponse(history, uint32(len(history)))

    @marshal
    async def dl_owned_singletons(self, request: Empty) -> DLOwnedSingletonsResponse:
        """Get all owned singleton records"""
        if self.service.wallet_state_manager is None:
            raise ValueError("The wallet service is not currently initialized")

        wallet = self.service.wallet_state_manager.get_dl_wallet()
        singletons = await wallet.get_owned_singletons()

        return DLOwnedSingletonsResponse(singletons, uint32(len(singletons)))

    @marshal
    async def dl_get_mirrors(self, request: DLGetMirrors) -> DLGetMirrorsResponse:
        """Get all of the mirrors for a specific singleton"""
        if self.service.wallet_state_manager is None:
            raise ValueError("The wallet service is not currently initialized")

        wallet = self.service.wallet_state_manager.get_dl_wallet()
        return DLGetMirrorsResponse(await wallet.get_mirrors_for_launcher(request.launcher_id))

    @tx_endpoint(push=True)
    @marshal
    async def dl_new_mirror(
        self,
        request: DLNewMirror,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> DLNewMirrorResponse:
        """Add a new on chain message for a specific singleton"""
        if self.service.wallet_state_manager is None:
            raise ValueError("The wallet service is not currently initialized")

        dl_wallet = self.service.wallet_state_manager.get_dl_wallet()
        async with self.service.wallet_state_manager.lock:
            await dl_wallet.create_new_mirror(
                request.launcher_id,
                request.amount,
                Mirror.encode_urls(request.urls),
                action_scope,
                fee=request.fee,
                extra_conditions=extra_conditions,
            )

        # tx_endpoint will take care of default values here
        return DLNewMirrorResponse(
            [],
            [],
        )

    @tx_endpoint(push=True)
    @marshal
    async def dl_delete_mirror(
        self,
        request: DLDeleteMirror,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> DLDeleteMirrorResponse:
        """Remove an existing mirror for a specific singleton"""
        if self.service.wallet_state_manager is None:
            raise ValueError("The wallet service is not currently initialized")

        dl_wallet = self.service.wallet_state_manager.get_dl_wallet()
        async with self.service.wallet_state_manager.lock:
            await dl_wallet.delete_mirror(
                request.coin_id,
                self.service.get_full_node_peer(),
                action_scope,
                fee=request.fee,
                extra_conditions=extra_conditions,
            )

        # tx_endpoint will take care of default values here
        return DLDeleteMirrorResponse(
            [],
            [],
        )

    @marshal
    async def dl_verify_proof(
        self,
        request: DLProof,
    ) -> VerifyProofResponse:
        """Verify a proof of inclusion for a DL singleton"""
        res = await dl_verify_proof(
            request,
            peer=self.service.get_full_node_peer(),
            wallet_node=self.service.wallet_state_manager.wallet_node,
        )

        return res

    ##########################################################################################
    # Verified Credential
    ##########################################################################################
    @tx_endpoint(push=True)
    @marshal
    async def vc_mint(
        self,
        request: VCMint,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> VCMintResponse:
        """
        Mint a verified credential using the assigned DID
        :param request: We require 'did_id' that will be minting the VC and options for a new 'target_address' as well
        as a 'fee' for the mint tx
        :return: a 'vc_record' containing all the information of the soon-to-be-confirmed vc as well as any relevant
        'transactions'
        """
        did_id = decode_puzzle_hash(request.did_id)
        puzhash: bytes32 | None = None
        if request.target_address is not None:
            puzhash = decode_puzzle_hash(request.target_address)

        vc_wallet: VCWallet = await self.service.wallet_state_manager.get_or_create_vc_wallet()
        vc_record = await vc_wallet.launch_new_vc(
            did_id, action_scope, puzhash, request.fee, extra_conditions=extra_conditions
        )
        return VCMintResponse([], [], vc_record)

    @marshal
    async def vc_get(self, request: VCGet) -> VCGetResponse:
        """
        Given a launcher ID get the verified credential
        :param request: the 'vc_id' launcher id of a verifiable credential
        :return: the 'vc_record' representing the specified verifiable credential
        """
        vc_record = await self.service.wallet_state_manager.vc_store.get_vc_record(request.vc_id)
        return VCGetResponse(vc_record)

    @marshal
    async def vc_get_list(self, request: VCGetList) -> VCGetListResponse:
        """
        Get a list of verified credentials
        :param request: optional parameters for pagination 'start' and 'count'
        :return: all 'vc_records' in the specified range and any 'proofs' associated with the roots contained within
        """

        vc_list = await self.service.wallet_state_manager.vc_store.get_vc_record_list(request.start, request.end)
        return VCGetListResponse(
            [VCRecordWithCoinID.from_vc_record(vc) for vc in vc_list],
            [
                VCProofWithHash(
                    rec.vc.proof_hash, None if fetched_proof is None else VCProofsRPC.from_vc_proofs(fetched_proof)
                )
                for rec in vc_list
                if rec.vc.proof_hash is not None
                for fetched_proof in (
                    await self.service.wallet_state_manager.vc_store.get_proofs_for_root(rec.vc.proof_hash),
                )
            ],
        )

    @tx_endpoint(push=True)
    @marshal
    async def vc_spend(
        self,
        request: VCSpend,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> VCSpendResponse:
        """
        Spend a verified credential
        :param request: Required 'vc_id' launcher id of the vc we wish to spend. Optional parameters for a 'new_puzhash'
        for the vc to end up at and 'new_proof_hash' & 'provider_inner_puzhash' which can be used to update the vc's
        proofs. Also standard 'fee' & 'reuse_puzhash' parameters for the transaction.
        :return: a list of all relevant 'transactions' (TransactionRecord) that this spend generates (VC TX + fee TX)
        """

        vc_wallet: VCWallet = await self.service.wallet_state_manager.get_or_create_vc_wallet()

        await vc_wallet.generate_signed_transaction(
            [uint64(1)],
            [
                request.new_puzhash
                if request.new_puzhash is not None
                else await action_scope.get_puzzle_hash(self.service.wallet_state_manager)
            ],
            action_scope,
            request.fee,
            vc_id=request.vc_id,
            new_proof_hash=request.new_proof_hash,
            provider_inner_puzhash=request.provider_inner_puzhash,
            extra_conditions=extra_conditions,
        )

        return VCSpendResponse([], [])  # tx_endpoint takes care of filling this out

    @marshal
    async def vc_add_proofs(self, request: VCAddProofs) -> Empty:
        """
        Add a set of proofs to the DB that can be used when spending a VC. VCs are near useless until their proofs have
        been added.
        :param request: 'proofs' is a dictionary of key/value pairs
        :return:
        """
        vc_wallet: VCWallet = await self.service.wallet_state_manager.get_or_create_vc_wallet()

        await vc_wallet.store.add_vc_proofs(request.to_vc_proofs())

        return Empty()

    @marshal
    async def vc_get_proofs_for_root(self, request: VCGetProofsForRoot) -> VCGetProofsForRootResponse:
        """
        Given a specified vc root, get any proofs associated with that root.
        :param request: must specify 'root' representing the tree hash of some set of proofs
        :return: a dictionary of root hashes mapped to dictionaries of key value pairs of 'proofs'
        """

        vc_wallet: VCWallet = await self.service.wallet_state_manager.get_or_create_vc_wallet()

        vc_proofs: VCProofs | None = await vc_wallet.store.get_proofs_for_root(request.root)
        if vc_proofs is None:
            raise ValueError("no proofs found for specified root")  # pragma: no cover
        return VCGetProofsForRootResponse.from_vc_proofs(vc_proofs)

    @tx_endpoint(push=True)
    @marshal
    async def vc_revoke(
        self,
        request: VCRevoke,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> VCRevokeResponse:
        """
        Revoke an on chain VC provided the correct DID is available
        :param request: required 'vc_parent_id' for the VC coin. Standard transaction params 'fee' & 'reuse_puzhash'.
        :return: a list of all relevant 'transactions' (TransactionRecord) that this spend generates (VC TX + fee TX)
        """

        vc_wallet: VCWallet = await self.service.wallet_state_manager.get_or_create_vc_wallet()

        await vc_wallet.revoke_vc(
            request.vc_parent_id,
            self.service.get_full_node_peer(),
            action_scope,
            request.fee,
            extra_conditions=extra_conditions,
        )

        return VCRevokeResponse([], [])  # tx_endpoint takes care of filling this out

    @tx_endpoint(push=True)
    @marshal
    async def crcat_approve_pending(
        self,
        request: CRCATApprovePending,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> CRCATApprovePendingResponse:
        """
        Moving any "pending approval" CR-CATs into the spendable balance of the wallet
        :param request: Required 'wallet_id'. Optional 'min_amount_to_claim' (default: full balance).
        Standard transaction params 'fee' & 'reuse_puzhash'.
        :return: a list of all relevant 'transactions' (TransactionRecord) that this spend generates:
        (CRCAT TX + fee TX)
        """

        cr_cat_wallet = self.service.wallet_state_manager.wallets[request.wallet_id]
        assert isinstance(cr_cat_wallet, CRCATWallet)

        await cr_cat_wallet.claim_pending_approval_balance(
            request.min_amount_to_claim,
            action_scope,
            fee=request.fee,
            extra_conditions=extra_conditions,
        )

        # tx_endpoint will take care of default values here
        return CRCATApprovePendingResponse([], [])

    @marshal
    async def gather_signing_info(
        self,
        request: GatherSigningInfo,
    ) -> GatherSigningInfoResponse:
        return GatherSigningInfoResponse(await self.service.wallet_state_manager.gather_signing_info(request.spends))

    @marshal
    async def apply_signatures(
        self,
        request: ApplySignatures,
    ) -> ApplySignaturesResponse:
        return ApplySignaturesResponse(
            [await self.service.wallet_state_manager.apply_signatures(request.spends, request.signing_responses)]
        )

    @marshal
    async def submit_transactions(
        self,
        request: SubmitTransactions,
    ) -> SubmitTransactionsResponse:
        return SubmitTransactionsResponse(
            await self.service.wallet_state_manager.submit_transactions(request.signed_transactions)
        )

    @marshal
    async def execute_signing_instructions(
        self,
        request: ExecuteSigningInstructions,
    ) -> ExecuteSigningInstructionsResponse:
        return ExecuteSigningInstructionsResponse(
            await self.service.wallet_state_manager.execute_signing_instructions(
                request.signing_instructions, request.partial_allowed
            )
        )
