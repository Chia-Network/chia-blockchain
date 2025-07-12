from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Optional, Union, cast

from chia_rs import AugSchemeMPL, Coin, CoinSpend, CoinState, G1Element, G2Element, PrivateKey
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint16, uint32, uint64
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
from chia.types.blockchain_format.coin import coin_as_list
from chia.types.blockchain_format.program import INFINITE_COST, Program, run_with_cost
from chia.types.coin_record import CoinRecord
from chia.types.signing_mode import CHIP_0002_SIGN_MESSAGE_PREFIX, SigningMode
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import load_config, str2bool
from chia.util.errors import KeychainIsLocked
from chia.util.hash import std_hash
from chia.util.keychain import bytes_to_mnemonic, generate_mnemonic
from chia.util.path import path_from_root
from chia.util.streamable import Streamable, UInt32Range, streamable
from chia.util.ws_message import WsRpcMessage, create_payload_dict
from chia.wallet.cat_wallet.cat_constants import DEFAULT_CATS
from chia.wallet.cat_wallet.cat_info import CRCATInfo
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.conditions import (
    AssertCoinAnnouncement,
    AssertPuzzleAnnouncement,
    Condition,
    ConditionValidTimes,
    CreateCoin,
    CreateCoinAnnouncement,
    CreatePuzzleAnnouncement,
    conditions_from_json_dicts,
    parse_conditions_non_consensus,
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
from chia.wallet.notification_store import Notification
from chia.wallet.outer_puzzles import AssetType
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.puzzles import p2_delegated_conditions
from chia.wallet.puzzles.clawback.metadata import AutoClaimSettings, ClawbackMetadata
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_hash_for_synthetic_public_key
from chia.wallet.signer_protocol import SigningResponse
from chia.wallet.singleton import (
    SINGLETON_LAUNCHER_PUZZLE_HASH,
    create_singleton_puzzle,
    get_inner_puzzle_from_singleton,
)
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.offer import Offer
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.util.address_type import AddressType, is_valid_address
from chia.wallet.util.clvm_streamable import json_serialize_with_clvm_streamable
from chia.wallet.util.compute_hints import compute_spend_hints_and_additions
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.curry_and_treehash import NIL_TREEHASH
from chia.wallet.util.query_filter import FilterMode, HashFilter, TransactionTypeFilter
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
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_coin_store import CoinRecordOrder, GetCoinRecords, unspent_range
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_node import WalletNode
from chia.wallet.wallet_protocol import WalletProtocol
from chia.wallet.wallet_request_types import (
    AddKey,
    AddKeyResponse,
    ApplySignatures,
    ApplySignaturesResponse,
    CheckDeleteKey,
    CheckDeleteKeyResponse,
    CombineCoins,
    CombineCoinsResponse,
    CreateNewDL,
    CreateNewDLResponse,
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
    Empty,
    ExecuteSigningInstructions,
    ExecuteSigningInstructionsResponse,
    GatherSigningInfo,
    GatherSigningInfoResponse,
    GenerateMnemonicResponse,
    GetHeightInfoResponse,
    GetLoggedInFingerprintResponse,
    GetNotifications,
    GetNotificationsResponse,
    GetPrivateKey,
    GetPrivateKeyFormat,
    GetPrivateKeyResponse,
    GetPublicKeysResponse,
    GetSyncStatusResponse,
    GetTimestampForHeight,
    GetTimestampForHeightResponse,
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
    SetWalletResyncOnStartup,
    SplitCoins,
    SplitCoinsResponse,
    SubmitTransactions,
    SubmitTransactionsResponse,
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
                excluded_coins: Optional[list[dict[str, Any]]] = request.get(
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

            async with self.service.wallet_state_manager.new_action_scope(
                tx_config,
                push=request.get("push", push),
                merge_spends=request.get("merge_spends", merge_spends),
                sign=request.get("sign", self.service.config.get("auto_sign_txs", True)),
            ) as action_scope:
                response: EndpointResult = await func(
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

            response["transactions"] = [
                TransactionRecord.to_json_dict_convenience(tx, self.service.config)
                for tx in action_scope.side_effects.transactions
            ]

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
    memos=[],
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
            "/did_update_recovery_ids": self.did_update_recovery_ids,
            "/did_update_metadata": self.did_update_metadata,
            "/did_get_pubkey": self.did_get_pubkey,
            "/did_get_did": self.did_get_did,
            "/did_recovery_spend": self.did_recovery_spend,
            "/did_get_recovery_list": self.did_get_recovery_list,
            "/did_get_metadata": self.did_get_metadata,
            "/did_create_attest": self.did_create_attest,
            "/did_get_information_needed_for_recovery": self.did_get_information_needed_for_recovery,
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

    def get_connections(self, request_node_type: Optional[NodeType]) -> list[dict[str, Any]]:
        return default_get_connections(server=self.service.server, request_node_type=request_node_type)

    async def _state_changed(self, change: str, change_data: Optional[dict[str, Any]]) -> list[WsRpcMessage]:
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
            fingerprints = [
                uint32(sk.get_g1().get_fingerprint())
                for (sk, seed) in await self.service.keychain_proxy.get_all_private_keys()
            ]
        except KeychainIsLocked:
            return GetPublicKeysResponse(keyring_is_locked=True)
        except Exception as e:
            raise Exception(
                "Error while getting keys.  If the issue persists, restart all services."
                f"  Original error: {type(e).__name__}: {e}"
            ) from e
        else:
            return GetPublicKeysResponse(keyring_is_locked=False, public_key_fingerprints=fingerprints)

    async def _get_private_key(self, fingerprint: int) -> tuple[Optional[PrivateKey], Optional[bytes]]:
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
            sk = await self.service.keychain_proxy.add_key(" ".join(request.mnemonic))
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
        path = path_from_root(
            self.service.root_path,
            f"{self.service.config['database_path']}-{request.fingerprint}",
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
        try:
            await self.service.keychain_proxy.delete_all_keys()
        except Exception as e:
            log.error(f"Failed to delete all keys: {e}")
            raise e
        path = path_from_root(self.service.root_path, self.service.config["database_path"])
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
        async with action_scope.use() as interface:
            interface.side_effects.transactions.extend(request.transactions)
            if request.fee != 0:
                all_conditions_and_origins = [
                    (condition, cs.coin.name())
                    for tx in interface.side_effects.transactions
                    if tx.spend_bundle is not None
                    for cs in tx.spend_bundle.coin_spends
                    for condition in run_with_cost(cs.puzzle_reveal, INFINITE_COST, cs.solution)[1].as_iter()
                ]
                create_coin_announcement = next(
                    condition
                    for condition in parse_conditions_non_consensus(
                        [con for con, coin in all_conditions_and_origins], abstractions=False
                    )
                    if isinstance(condition, CreateCoinAnnouncement)
                )
                announcement_origin = next(
                    coin
                    for condition, coin in all_conditions_and_origins
                    if condition == create_coin_announcement.to_program()
                )
                async with self.service.wallet_state_manager.new_action_scope(
                    dataclasses.replace(
                        action_scope.config.tx_config,
                        excluded_coin_ids=[
                            *action_scope.config.tx_config.excluded_coin_ids,
                            *(c.name() for tx in interface.side_effects.transactions for c in tx.removals),
                        ],
                    ),
                    push=False,
                ) as inner_action_scope:
                    await self.service.wallet_state_manager.main_wallet.create_tandem_xch_tx(
                        request.fee,
                        inner_action_scope,
                        extra_conditions=(
                            *extra_conditions,
                            CreateCoinAnnouncement(
                                create_coin_announcement.msg, announcement_origin
                            ).corresponding_assertion(),
                        ),
                    )

                interface.side_effects.transactions.extend(inner_action_scope.side_effects.transactions)

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

    async def get_wallets(self, request: dict[str, Any]) -> EndpointResult:
        include_data: bool = request.get("include_data", True)
        wallet_type: Optional[WalletType] = None
        if "type" in request:
            wallet_type = WalletType(request["type"])

        wallets: list[WalletInfo] = await self.service.wallet_state_manager.get_all_wallet_info_entries(wallet_type)
        if not include_data:
            result: list[WalletInfo] = []
            for wallet in wallets:
                result.append(WalletInfo(wallet.id, wallet.name, wallet.type, ""))
            wallets = result
        response: EndpointResult = {"wallets": wallets}
        if include_data:
            response = {
                "wallets": [
                    (
                        wallet
                        if wallet.type != WalletType.CRCAT
                        else {
                            **wallet.to_json_dict(),
                            "authorized_providers": [
                                p.hex() for p in CRCATInfo.from_bytes(bytes.fromhex(wallet.data)).authorized_providers
                            ],
                            "flags_needed": CRCATInfo.from_bytes(bytes.fromhex(wallet.data)).proofs_checker.flags,
                        }
                    )
                    for wallet in response["wallets"]
                ]
            }
        if self.service.logged_in_fingerprint is not None:
            response["fingerprint"] = self.service.logged_in_fingerprint
        return response

    @tx_endpoint(push=True)
    async def create_new_wallet(
        self,
        request: dict[str, Any],
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> EndpointResult:
        wallet_state_manager = self.service.wallet_state_manager

        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced.")
        main_wallet = wallet_state_manager.main_wallet
        fee = uint64(request.get("fee", 0))

        if request["wallet_type"] == "cat_wallet":
            # If not provided, the name will be autogenerated based on the tail hash.
            name = request.get("name", None)
            if request["mode"] == "new":
                if request.get("test", False):
                    if not action_scope.config.push:
                        raise ValueError("Test CAT minting must be pushed automatically")  # pragma: no cover
                    async with self.service.wallet_state_manager.lock:
                        cat_wallet = await CATWallet.create_new_cat_wallet(
                            wallet_state_manager,
                            main_wallet,
                            {"identifier": "genesis_by_id"},
                            uint64(request["amount"]),
                            action_scope,
                            fee,
                            name,
                        )
                        asset_id = cat_wallet.get_asset_id()
                    self.service.wallet_state_manager.state_changed("wallet_created")
                    return {
                        "type": cat_wallet.type(),
                        "asset_id": asset_id,
                        "wallet_id": cat_wallet.id(),
                        "transactions": None,  # tx_endpoint wrapper will take care of this
                    }
                else:
                    raise ValueError(
                        "Support for this RPC mode has been dropped."
                        " Please use the CAT Admin Tool @ https://github.com/Chia-Network/CAT-admin-tool instead."
                    )

            elif request["mode"] == "existing":
                async with self.service.wallet_state_manager.lock:
                    cat_wallet = await CATWallet.get_or_create_wallet_for_cat(
                        wallet_state_manager, main_wallet, request["asset_id"], name
                    )
                return {"type": cat_wallet.type(), "asset_id": request["asset_id"], "wallet_id": cat_wallet.id()}

            else:  # undefined mode
                pass

        elif request["wallet_type"] == "did_wallet":
            if request["did_type"] == "new":
                backup_dids = []
                num_needed = 0
                for d in request["backup_dids"]:
                    backup_dids.append(decode_puzzle_hash(d))
                if len(backup_dids) > 0:
                    num_needed = uint64(request["num_of_backup_ids_needed"])
                metadata: dict[str, str] = {}
                if "metadata" in request:
                    if type(request["metadata"]) is dict:
                        metadata = request["metadata"]

                async with self.service.wallet_state_manager.lock:
                    did_wallet_name: str = request.get("wallet_name", None)
                    if did_wallet_name is not None:
                        did_wallet_name = did_wallet_name.strip()
                    did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
                        wallet_state_manager,
                        main_wallet,
                        uint64(request["amount"]),
                        action_scope,
                        backup_dids,
                        uint64(num_needed),
                        metadata,
                        did_wallet_name,
                        uint64(request.get("fee", 0)),
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
                return {
                    "success": True,
                    "type": did_wallet.type(),
                    "my_did": my_did_id,
                    "wallet_id": did_wallet.id(),
                    "transactions": None,  # tx_endpoint wrapper will take care of this
                }

            elif request["did_type"] == "recovery":
                async with self.service.wallet_state_manager.lock:
                    did_wallet = await DIDWallet.create_new_did_wallet_from_recovery(
                        wallet_state_manager, main_wallet, request["backup_data"]
                    )
                assert did_wallet.did_info.temp_coin is not None
                assert did_wallet.did_info.temp_puzhash is not None
                assert did_wallet.did_info.temp_pubkey is not None
                my_did = did_wallet.get_my_DID()
                coin_name = did_wallet.did_info.temp_coin.name().hex()
                coin_list = coin_as_list(did_wallet.did_info.temp_coin)
                newpuzhash = did_wallet.did_info.temp_puzhash
                pubkey = did_wallet.did_info.temp_pubkey
                return {
                    "success": True,
                    "type": did_wallet.type(),
                    "my_did": my_did,
                    "wallet_id": did_wallet.id(),
                    "coin_name": coin_name,
                    "coin_list": coin_list,
                    "newpuzhash": newpuzhash.hex(),
                    "pubkey": pubkey.hex(),
                    "backup_dids": did_wallet.did_info.backup_ids,
                    "num_verifications_required": did_wallet.did_info.num_of_backup_ids_needed,
                }
            else:  # undefined did_type
                pass
        elif request["wallet_type"] == "nft_wallet":
            for wallet in self.service.wallet_state_manager.wallets.values():
                did_id: Optional[bytes32] = None
                if "did_id" in request and request["did_id"] is not None:
                    did_id = decode_puzzle_hash(request["did_id"])
                if wallet.type() == WalletType.NFT:
                    assert isinstance(wallet, NFTWallet)
                    if wallet.get_did() == did_id:
                        log.info("NFT wallet already existed, skipping.")
                        return {
                            "success": True,
                            "type": wallet.type(),
                            "wallet_id": wallet.id(),
                        }

            async with self.service.wallet_state_manager.lock:
                nft_wallet: NFTWallet = await NFTWallet.create_new_nft_wallet(
                    wallet_state_manager, main_wallet, did_id, request.get("name", None)
                )
            return {
                "success": True,
                "type": nft_wallet.type(),
                "wallet_id": nft_wallet.id(),
            }
        elif request["wallet_type"] == "pool_wallet":
            if request["mode"] == "new":
                if "initial_target_state" not in request:
                    raise AttributeError("Daemon didn't send `initial_target_state`. Try updating the daemon.")

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

                    initial_target_state = initial_pool_state_from_dict(
                        request["initial_target_state"], owner_pk, owner_puzzle_hash
                    )
                    assert initial_target_state is not None

                    try:
                        delayed_address = None
                        if "p2_singleton_delayed_ph" in request:
                            delayed_address = bytes32.from_hexstr(request["p2_singleton_delayed_ph"])

                        p2_singleton_puzzle_hash, launcher_id = await PoolWallet.create_new_pool_wallet_transaction(
                            wallet_state_manager,
                            main_wallet,
                            initial_target_state,
                            action_scope,
                            fee,
                            request.get("p2_singleton_delay_time", None),
                            delayed_address,
                            extra_conditions=extra_conditions,
                        )

                    except Exception as e:
                        raise ValueError(str(e))
                    return {
                        "total_fee": fee * 2,
                        "transaction": None,  # tx_endpoint wrapper will take care of this
                        "transactions": None,  # tx_endpoint wrapper will take care of this
                        "launcher_id": launcher_id.hex(),
                        "p2_singleton_puzzle_hash": p2_singleton_puzzle_hash.hex(),
                    }
            elif request["mode"] == "recovery":
                raise ValueError("Need upgraded singleton for on-chain recovery")

        else:  # undefined wallet_type
            pass

        # TODO: rework this function to report detailed errors for each error case
        return {"success": False, "error": "invalid request"}

    ##########################################################################################
    # Wallet
    ##########################################################################################

    async def _get_wallet_balance(self, wallet_id: uint32) -> dict[str, Any]:
        wallet = self.service.wallet_state_manager.wallets[wallet_id]
        balance = await self.service.get_balance(wallet_id)
        wallet_balance = balance.to_json_dict()
        wallet_balance["wallet_id"] = wallet_id
        wallet_balance["wallet_type"] = wallet.type()
        if self.service.logged_in_fingerprint is not None:
            wallet_balance["fingerprint"] = self.service.logged_in_fingerprint
        if wallet.type() in {WalletType.CAT, WalletType.CRCAT, WalletType.RCAT}:
            assert isinstance(wallet, CATWallet)
            wallet_balance["asset_id"] = wallet.get_asset_id()
            if wallet.type() == WalletType.CRCAT:
                assert isinstance(wallet, CRCATWallet)
                wallet_balance["pending_approval_balance"] = await wallet.get_pending_approval_balance()

        return wallet_balance

    async def get_wallet_balance(self, request: dict[str, Any]) -> EndpointResult:
        wallet_id = uint32(int(request["wallet_id"]))
        wallet_balance = await self._get_wallet_balance(wallet_id)
        return {"wallet_balance": wallet_balance}

    async def get_wallet_balances(self, request: dict[str, Any]) -> EndpointResult:
        try:
            wallet_ids: list[uint32] = [uint32(int(wallet_id)) for wallet_id in request["wallet_ids"]]
        except (TypeError, KeyError):
            wallet_ids = list(self.service.wallet_state_manager.wallets.keys())
        wallet_balances: dict[uint32, dict[str, Any]] = {}
        for wallet_id in wallet_ids:
            wallet_balances[wallet_id] = await self._get_wallet_balance(wallet_id)
        return {"wallet_balances": wallet_balances}

    async def get_transaction(self, request: dict[str, Any]) -> EndpointResult:
        transaction_id: bytes32 = bytes32.from_hexstr(request["transaction_id"])
        tr: Optional[TransactionRecord] = await self.service.wallet_state_manager.get_transaction(transaction_id)
        if tr is None:
            raise ValueError(f"Transaction 0x{transaction_id.hex()} not found")

        return {
            "transaction": (await self._convert_tx_puzzle_hash(tr)).to_json_dict_convenience(self.service.config),
            "transaction_id": tr.name,
        }

    async def get_transaction_memo(self, request: dict[str, Any]) -> EndpointResult:
        transaction_id: bytes32 = bytes32.from_hexstr(request["transaction_id"])
        tr: Optional[TransactionRecord] = await self.service.wallet_state_manager.get_transaction(transaction_id)
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
        memos: dict[bytes32, list[bytes]] = compute_memos(tr.spend_bundle)
        response = {}
        # Convert to hex string
        for coin_id, memo_list in memos.items():
            response[coin_id.hex()] = [memo.hex() for memo in memo_list]
        return {transaction_id.hex(): response}

    @tx_endpoint(push=False)
    @marshal
    async def split_coins(
        self, request: SplitCoins, action_scope: WalletActionScope, extra_conditions: tuple[Condition, ...] = tuple()
    ) -> SplitCoinsResponse:
        if request.number_of_coins > 500:
            raise ValueError(f"{request.number_of_coins} coins is greater then the maximum limit of 500 coins.")

        optional_coin = await self.service.wallet_state_manager.coin_store.get_coin_record(request.target_coin_id)
        if optional_coin is None:
            raise ValueError(f"Could not find coin with ID {request.target_coin_id}")
        else:
            coin = optional_coin.coin

        total_amount = request.amount_per_coin * request.number_of_coins

        if coin.amount < total_amount:
            raise ValueError(
                f"Coin amount: {coin.amount} is less than the total amount of the split: {total_amount}, exiting."
            )

        if request.wallet_id not in self.service.wallet_state_manager.wallets:
            raise ValueError(f"Wallet with ID {request.wallet_id} does not exist")
        wallet = self.service.wallet_state_manager.wallets[request.wallet_id]
        if not isinstance(wallet, (Wallet, CATWallet)):
            raise ValueError("Cannot split coins from non-fungible wallet types")

        outputs = [
            CreateCoin(
                await action_scope.get_puzzle_hash(
                    self.service.wallet_state_manager, override_reuse_puzhash_with=False
                ),
                request.amount_per_coin,
            )
            for _ in range(request.number_of_coins)
        ]
        if len(outputs) == 0:
            return SplitCoinsResponse([], [])

        if wallet.type() == WalletType.STANDARD_WALLET and coin.amount < total_amount + request.fee:
            async with action_scope.use() as interface:
                interface.side_effects.selected_coins.append(coin)
            coins = await wallet.select_coins(
                uint64(total_amount + request.fee - coin.amount),
                action_scope,
            )
            coins.add(coin)
        else:
            coins = {coin}

        await wallet.generate_signed_transaction(
            [output.amount for output in outputs],
            [output.puzzle_hash for output in outputs],
            action_scope,
            request.fee,
            coins=coins,
            extra_conditions=extra_conditions,
        )

        return SplitCoinsResponse([], [])  # tx_endpoint will take care to fill this out

    @tx_endpoint(push=False)
    @marshal
    async def combine_coins(
        self, request: CombineCoins, action_scope: WalletActionScope, extra_conditions: tuple[Condition, ...] = tuple()
    ) -> CombineCoinsResponse:
        # Some "number of coins" validation
        if request.number_of_coins > request.coin_num_limit:
            raise ValueError(
                f"{request.number_of_coins} coins is greater then the maximum limit of {request.coin_num_limit} coins."
            )
        if request.number_of_coins < 1:
            raise ValueError("You need at least two coins to combine")
        if len(request.target_coin_ids) > request.number_of_coins:
            raise ValueError("More coin IDs specified than desired number of coins to combine")

        if request.wallet_id not in self.service.wallet_state_manager.wallets:
            raise ValueError(f"Wallet with ID {request.wallet_id} does not exist")
        wallet = self.service.wallet_state_manager.wallets[request.wallet_id]
        if not isinstance(wallet, (Wallet, CATWallet)):
            raise ValueError("Cannot combine coins from non-fungible wallet types")

        coins: list[Coin] = []

        # First get the coin IDs specified
        if request.target_coin_ids != []:
            coins.extend(
                cr.coin
                for cr in (
                    await self.service.wallet_state_manager.coin_store.get_coin_records(
                        wallet_id=request.wallet_id,
                        coin_id_filter=HashFilter(request.target_coin_ids, mode=uint8(FilterMode.include.value)),
                    )
                ).records
            )

        async with action_scope.use() as interface:
            interface.side_effects.selected_coins.extend(coins)

        # Next let's select enough coins to meet the target + fee if there is one
        fungible_amount_needed = uint64(0) if request.target_coin_amount is None else request.target_coin_amount
        if isinstance(wallet, Wallet):
            fungible_amount_needed = uint64(fungible_amount_needed + request.fee)
        amount_selected = sum(c.amount for c in coins)
        if amount_selected < fungible_amount_needed:  # implicit fungible_amount_needed > 0 here
            coins.extend(
                await wallet.select_coins(
                    amount=uint64(fungible_amount_needed - amount_selected), action_scope=action_scope
                )
            )

        if len(coins) > request.number_of_coins:
            raise ValueError(
                f"Options specified cannot be met without selecting more coins than specified: {len(coins)}"
            )

        # Now let's select enough coins to get to the target number to combine
        if len(coins) < request.number_of_coins:
            async with action_scope.use() as interface:
                coins.extend(
                    cr.coin
                    for cr in (
                        await self.service.wallet_state_manager.coin_store.get_coin_records(
                            wallet_id=request.wallet_id,
                            limit=uint32(request.number_of_coins - len(coins)),
                            order=CoinRecordOrder.amount,
                            coin_id_filter=HashFilter(
                                [c.name() for c in interface.side_effects.selected_coins],
                                mode=uint8(FilterMode.exclude.value),
                            ),
                            reverse=request.largest_first,
                        )
                    ).records
                )

        async with action_scope.use() as interface:
            interface.side_effects.selected_coins.extend(coins)

        primary_output_amount = (
            uint64(sum(c.amount for c in coins)) if request.target_coin_amount is None else request.target_coin_amount
        )
        if isinstance(wallet, Wallet):
            primary_output_amount = uint64(primary_output_amount - request.fee)

        await wallet.generate_signed_transaction(
            [primary_output_amount],
            [await action_scope.get_puzzle_hash(self.service.wallet_state_manager)],
            action_scope,
            request.fee,
            coins=set(coins),
            extra_conditions=extra_conditions,
        )

        return CombineCoinsResponse([], [])  # tx_endpoint will take care to fill this out

    async def get_transactions(self, request: dict[str, Any]) -> EndpointResult:
        wallet_id = int(request["wallet_id"])

        start = request.get("start", 0)
        end = request.get("end", 50)
        sort_key = request.get("sort_key", None)
        reverse = request.get("reverse", False)

        to_address = request.get("to_address", None)
        to_puzzle_hash: Optional[bytes32] = None
        if to_address is not None:
            to_puzzle_hash = decode_puzzle_hash(to_address)
        type_filter = None
        if "type_filter" in request:
            type_filter = TransactionTypeFilter.from_json_dict(request["type_filter"])

        transactions = await self.service.wallet_state_manager.tx_store.get_transactions_between(
            wallet_id,
            start,
            end,
            sort_key=sort_key,
            reverse=reverse,
            to_puzzle_hash=to_puzzle_hash,
            type_filter=type_filter,
            confirmed=request.get("confirmed", None),
        )
        tx_list = []
        # Format for clawback transactions
        for tr in transactions:
            tx = (await self._convert_tx_puzzle_hash(tr)).to_json_dict_convenience(self.service.config)
            tx_list.append(tx)
            if tx["type"] not in CLAWBACK_INCOMING_TRANSACTION_TYPES:
                continue
            coin: Coin = tr.additions[0]
            record: Optional[WalletCoinRecord] = await self.service.wallet_state_manager.coin_store.get_coin_record(
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
        return {
            "transactions": tx_list,
            "wallet_id": wallet_id,
        }

    async def get_transaction_count(self, request: dict[str, Any]) -> EndpointResult:
        wallet_id = int(request["wallet_id"])
        type_filter = None
        if "type_filter" in request:
            type_filter = TransactionTypeFilter.from_json_dict(request["type_filter"])
        count = await self.service.wallet_state_manager.tx_store.get_transaction_count_for_wallet(
            wallet_id, confirmed=request.get("confirmed", None), type_filter=type_filter
        )
        return {
            "count": count,
            "wallet_id": wallet_id,
        }

    async def get_next_address(self, request: dict[str, Any]) -> EndpointResult:
        """
        Returns a new address
        """
        if request["new_address"] is True:
            create_new = True
        else:
            create_new = False
        wallet_id = uint32(int(request["wallet_id"]))
        wallet = self.service.wallet_state_manager.wallets[wallet_id]
        selected = self.service.config["selected_network"]
        prefix = self.service.config["network_overrides"]["config"][selected]["address_prefix"]
        if wallet.type() in {WalletType.STANDARD_WALLET, WalletType.CAT, WalletType.CRCAT, WalletType.RCAT}:
            async with self.service.wallet_state_manager.new_action_scope(
                DEFAULT_TX_CONFIG, push=request.get("save_derivations", True)
            ) as action_scope:
                raw_puzzle_hash = await action_scope.get_puzzle_hash(
                    self.service.wallet_state_manager, override_reuse_puzhash_with=not create_new
                )
            address = encode_puzzle_hash(raw_puzzle_hash, prefix)
        else:
            raise ValueError(f"Wallet type {wallet.type()} cannot create puzzle hashes")

        return {
            "wallet_id": wallet_id,
            "address": address,
        }

    @tx_endpoint(push=True)
    async def send_transaction(
        self,
        request: dict[str, Any],
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> EndpointResult:
        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced before sending transactions")

        wallet_id = uint32(request["wallet_id"])
        wallet = self.service.wallet_state_manager.get_wallet(id=wallet_id, required_type=Wallet)

        # TODO: Add support for multiple puzhash/amount/memo sets
        if not isinstance(request["amount"], int) or not isinstance(request["fee"], int):
            raise ValueError("An integer amount or fee is required (too many decimals)")
        amount: uint64 = uint64(request["amount"])
        address = request["address"]
        selected_network = self.service.config["selected_network"]
        expected_prefix = self.service.config["network_overrides"]["config"][selected_network]["address_prefix"]
        if address[0 : len(expected_prefix)] != expected_prefix:
            raise ValueError("Unexpected Address Prefix")
        puzzle_hash: bytes32 = decode_puzzle_hash(address)

        memos: list[bytes] = []
        if "memos" in request:
            memos = [mem.encode("utf-8") for mem in request["memos"]]

        fee: uint64 = uint64(request.get("fee", 0))

        await wallet.generate_signed_transaction(
            [amount],
            [puzzle_hash],
            action_scope,
            fee,
            memos=[memos],
            puzzle_decorator_override=request.get("puzzle_decorator", None),
            extra_conditions=extra_conditions,
        )

        # Transaction may not have been included in the mempool yet. Use get_transaction to check.
        return {
            "transaction": None,  # tx_endpoint wrapper will take care of this
            "transactions": None,  # tx_endpoint wrapper will take care of this
            "transaction_id": None,  # tx_endpoint wrapper will take care of this
        }

    async def send_transaction_multi(self, request: dict[str, Any]) -> EndpointResult:
        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced before sending transactions")

        # This is required because this is a "@tx_endpoint" that calls other @tx_endpoints
        request.setdefault("push", True)
        request.setdefault("merge_spends", True)

        wallet_id = uint32(request["wallet_id"])
        wallet = self.service.wallet_state_manager.wallets[wallet_id]

        async with self.service.wallet_state_manager.lock:
            if wallet.type() in {WalletType.CAT, WalletType.CRCAT, WalletType.RCAT}:
                assert isinstance(wallet, CATWallet)
                response = await self.cat_spend(request, hold_lock=False)
                transaction = response["transaction"]
                transactions = response["transactions"]
            else:
                response = await self.create_signed_transaction(request, hold_lock=False)
                transaction = response["signed_tx"]
                transactions = response["transactions"]

        # Transaction may not have been included in the mempool yet. Use get_transaction to check.
        return {
            "transaction": transaction,
            "transaction_id": TransactionRecord.from_json_dict_convenience(transaction).name,
            "transactions": transactions,
            "unsigned_transactions": response["unsigned_transactions"],
        }

    @tx_endpoint(push=True, merge_spends=False)
    async def spend_clawback_coins(
        self,
        request: dict[str, Any],
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> EndpointResult:
        """Spend clawback coins that were sent (to claw them back) or received (to claim them).

        :param coin_ids: list of coin ids to be spent
        :param batch_size: number of coins to spend per bundle
        :param fee: transaction fee in mojos
        :return:
        """
        if "coin_ids" not in request:
            raise ValueError("Coin IDs are required.")
        coin_ids: list[bytes32] = [bytes32.from_hexstr(coin) for coin in request["coin_ids"]]
        tx_fee: uint64 = uint64(request.get("fee", 0))
        # Get inner puzzle
        coin_records = await self.service.wallet_state_manager.coin_store.get_coin_records(
            coin_id_filter=HashFilter.include(coin_ids),
            coin_type=CoinType.CLAWBACK,
            wallet_type=WalletType.STANDARD_WALLET,
            spent_range=UInt32Range(stop=uint32(0)),
        )

        coins: dict[Coin, ClawbackMetadata] = {}
        batch_size = request.get(
            "batch_size", self.service.wallet_state_manager.config.get("auto_claim", {}).get("batch_size", 50)
        )
        for coin_id, coin_record in coin_records.coin_id_to_record.items():
            try:
                metadata = coin_record.parsed_metadata()
                assert isinstance(metadata, ClawbackMetadata)
                coins[coin_record.coin] = metadata
                if len(coins) >= batch_size:
                    await self.service.wallet_state_manager.spend_clawback_coins(
                        coins,
                        tx_fee,
                        action_scope,
                        request.get("force", False),
                        extra_conditions=extra_conditions,
                    )
                    coins = {}
            except Exception as e:
                log.error(f"Failed to spend clawback coin {coin_id.hex()}: %s", e)
        if len(coins) > 0:
            await self.service.wallet_state_manager.spend_clawback_coins(
                coins,
                tx_fee,
                action_scope,
                request.get("force", False),
                extra_conditions=extra_conditions,
            )

        return {
            "success": True,
            "transaction_ids": None,  # tx_endpoint wrapper will take care of this
            "transactions": None,  # tx_endpoint wrapper will take care of this
        }

    async def delete_unconfirmed_transactions(self, request: dict[str, Any]) -> EndpointResult:
        wallet_id = uint32(request["wallet_id"])
        if wallet_id not in self.service.wallet_state_manager.wallets:
            raise ValueError(f"Wallet id {wallet_id} does not exist")
        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced.")

        async with self.service.wallet_state_manager.db_wrapper.writer():
            await self.service.wallet_state_manager.tx_store.delete_unconfirmed_transactions(wallet_id)
            wallet = self.service.wallet_state_manager.wallets[wallet_id]
            if wallet.type() == WalletType.POOLING_WALLET.value:
                assert isinstance(wallet, PoolWallet)
                wallet.target_state = None
            return {}

    async def select_coins(
        self,
        request: dict[str, Any],
    ) -> EndpointResult:
        assert self.service.logged_in_fingerprint is not None
        tx_config_loader: TXConfigLoader = TXConfigLoader.from_json_dict(request)

        # Some backwards compat fill-ins
        if tx_config_loader.excluded_coin_ids is None:
            excluded_coins: Optional[list[dict[str, Any]]] = request.get("excluded_coins", request.get("exclude_coins"))
            if excluded_coins is not None:
                tx_config_loader = tx_config_loader.override(
                    excluded_coin_ids=[Coin.from_json_dict(c).name() for c in excluded_coins],
                )

        tx_config: TXConfig = tx_config_loader.autofill(
            constants=self.service.wallet_state_manager.constants,
        )

        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced before selecting coins")

        amount = uint64(request["amount"])
        wallet_id = uint32(request["wallet_id"])

        wallet = self.service.wallet_state_manager.wallets[wallet_id]
        async with self.service.wallet_state_manager.new_action_scope(tx_config, push=False) as action_scope:
            selected_coins = await wallet.select_coins(amount, action_scope)

        return {"coins": [coin.to_json_dict() for coin in selected_coins]}

    async def get_spendable_coins(self, request: dict[str, Any]) -> EndpointResult:
        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced before getting all coins")

        wallet_id = uint32(request["wallet_id"])
        min_coin_amount = uint64(request.get("min_coin_amount", 0))
        max_coin_amount: uint64 = uint64(request.get("max_coin_amount", 0))
        if max_coin_amount == 0:
            max_coin_amount = uint64(self.service.wallet_state_manager.constants.MAX_COIN_AMOUNT)
        excluded_coin_amounts: Optional[list[uint64]] = request.get("excluded_coin_amounts")
        if excluded_coin_amounts is not None:
            excluded_coin_amounts = [uint64(a) for a in excluded_coin_amounts]
        else:
            excluded_coin_amounts = []
        excluded_coins_input: Optional[dict[str, dict[str, Any]]] = request.get("excluded_coins")
        if excluded_coins_input is not None:
            excluded_coins = [Coin.from_json_dict(json_coin) for json_coin in excluded_coins_input.values()]
        else:
            excluded_coins = []
        excluded_coin_ids_input: Optional[list[str]] = request.get("excluded_coin_ids")
        if excluded_coin_ids_input is not None:
            excluded_coin_ids = [bytes32.from_hexstr(hex_id) for hex_id in excluded_coin_ids_input]
        else:
            excluded_coin_ids = []
        state_mgr = self.service.wallet_state_manager
        wallet = state_mgr.wallets[wallet_id]
        async with state_mgr.lock:
            all_coin_records = await state_mgr.coin_store.get_unspent_coins_for_wallet(wallet_id)
            if wallet.type() in {WalletType.CAT, WalletType.CRCAT, WalletType.RCAT}:
                assert isinstance(wallet, CATWallet)
                spendable_coins: list[WalletCoinRecord] = await wallet.get_cat_spendable_coins(all_coin_records)
            else:
                spendable_coins = list(await state_mgr.get_spendable_coins_for_wallet(wallet_id, all_coin_records))

            # Now we get the unconfirmed transactions and manually derive the additions and removals.
            unconfirmed_transactions: list[TransactionRecord] = await state_mgr.tx_store.get_unconfirmed_for_wallet(
                wallet_id
            )
            unconfirmed_removal_ids: dict[bytes32, uint64] = {
                coin.name(): transaction.created_at_time
                for transaction in unconfirmed_transactions
                for coin in transaction.removals
            }
            unconfirmed_additions: list[Coin] = [
                coin
                for transaction in unconfirmed_transactions
                for coin in transaction.additions
                if await state_mgr.does_coin_belong_to_wallet(coin, wallet_id)
            ]
            valid_spendable_cr: list[CoinRecord] = []
            unconfirmed_removals: list[CoinRecord] = []
            for coin_record in all_coin_records:
                if coin_record.name() in unconfirmed_removal_ids:
                    unconfirmed_removals.append(coin_record.to_coin_record(unconfirmed_removal_ids[coin_record.name()]))
            for coin_record in spendable_coins:  # remove all the unconfirmed coins, exclude coins and dust.
                if coin_record.name() in unconfirmed_removal_ids:
                    continue
                if coin_record.coin in excluded_coins:
                    continue
                if coin_record.name() in excluded_coin_ids:
                    continue
                if coin_record.coin.amount < min_coin_amount or coin_record.coin.amount > max_coin_amount:
                    continue
                if coin_record.coin.amount in excluded_coin_amounts:
                    continue
                c_r = await state_mgr.get_coin_record_by_wallet_record(coin_record)
                assert c_r is not None and c_r.coin == coin_record.coin  # this should never happen
                valid_spendable_cr.append(c_r)

        return {
            "confirmed_records": [cr.to_json_dict() for cr in valid_spendable_cr],
            "unconfirmed_removals": [cr.to_json_dict() for cr in unconfirmed_removals],
            "unconfirmed_additions": [coin.to_json_dict() for coin in unconfirmed_additions],
        }

    async def get_coin_records_by_names(self, request: dict[str, Any]) -> EndpointResult:
        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced before finding coin information")

        if "names" not in request:
            raise ValueError("Names not in request")
        coin_ids = [bytes32.from_hexstr(name) for name in request["names"]]
        kwargs: dict[str, Any] = {
            "coin_id_filter": HashFilter.include(coin_ids),
        }

        confirmed_range = UInt32Range()
        if "start_height" in request:
            confirmed_range = dataclasses.replace(confirmed_range, start=uint32(request["start_height"]))
        if "end_height" in request:
            confirmed_range = dataclasses.replace(confirmed_range, stop=uint32(request["end_height"]))
        if confirmed_range != UInt32Range():
            kwargs["confirmed_range"] = confirmed_range

        if "include_spent_coins" in request and not str2bool(request["include_spent_coins"]):
            kwargs["spent_range"] = unspent_range

        async with self.service.wallet_state_manager.lock:
            coin_records: list[CoinRecord] = await self.service.wallet_state_manager.get_coin_records_by_coin_ids(
                **kwargs
            )
            missed_coins: list[str] = [
                "0x" + c_id.hex() for c_id in coin_ids if c_id not in [cr.name for cr in coin_records]
            ]
            if missed_coins:
                raise ValueError(f"Coin ID's: {missed_coins} not found.")

        return {"coin_records": [cr.to_json_dict() for cr in coin_records]}

    async def get_current_derivation_index(self, request: dict[str, Any]) -> dict[str, Any]:
        assert self.service.wallet_state_manager is not None

        index: Optional[uint32] = await self.service.wallet_state_manager.puzzle_store.get_last_derivation_path()

        return {"success": True, "index": index}

    async def extend_derivation_index(self, request: dict[str, Any]) -> dict[str, Any]:
        assert self.service.wallet_state_manager is not None

        # Require a new max derivation index
        if "index" not in request:
            raise ValueError("Derivation index is required")

        # Require that the wallet is fully synced
        synced = await self.service.wallet_state_manager.synced()
        if synced is False:
            raise ValueError("Wallet needs to be fully synced before extending derivation index")

        index = uint32(request["index"])
        current: Optional[uint32] = await self.service.wallet_state_manager.puzzle_store.get_last_derivation_path()

        # Additional sanity check that the wallet is synced
        if current is None:
            raise ValueError("No current derivation record found, unable to extend index")

        # Require that the new index is greater than the current index
        if index <= current:
            raise ValueError(f"New derivation index must be greater than current index: {current}")

        if index - current > MAX_DERIVATION_INDEX_DELTA:
            raise ValueError(
                "Too many derivations requested. "
                f"Use a derivation index less than {current + MAX_DERIVATION_INDEX_DELTA + 1}"
            )

        # Since we've bumping the derivation index without having found any new puzzles, we want
        # to preserve the current last used index, so we call create_more_puzzle_hashes with
        # mark_existing_as_used=False
        result = await self.service.wallet_state_manager.create_more_puzzle_hashes(
            from_zero=False, mark_existing_as_used=False, up_to_index=index, num_additional_phs=0
        )
        await result.commit(self.service.wallet_state_manager)

        updated: Optional[uint32] = await self.service.wallet_state_manager.puzzle_store.get_last_derivation_path()
        updated_index = updated if updated is not None else None

        return {"success": True, "index": updated_index}

    @marshal
    async def get_notifications(self, request: GetNotifications) -> GetNotificationsResponse:
        if request.ids is None:
            notifications: list[
                Notification
            ] = await self.service.wallet_state_manager.notification_manager.notification_store.get_all_notifications(
                pagination=(request.start, request.end)
            )
        else:
            notifications = (
                await self.service.wallet_state_manager.notification_manager.notification_store.get_notifications(
                    request.ids
                )
            )

        return GetNotificationsResponse(notifications)

    async def delete_notifications(self, request: dict[str, Any]) -> EndpointResult:
        ids: Optional[list[str]] = request.get("ids", None)
        if ids is None:
            await self.service.wallet_state_manager.notification_manager.notification_store.delete_all_notifications()
        else:
            await self.service.wallet_state_manager.notification_manager.notification_store.delete_notifications(
                [bytes32.from_hexstr(id) for id in ids]
            )

        return {}

    @tx_endpoint(push=True)
    async def send_notification(
        self,
        request: dict[str, Any],
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> EndpointResult:
        await self.service.wallet_state_manager.notification_manager.send_new_notification(
            bytes32.from_hexstr(request["target"]),
            bytes.fromhex(request["message"]),
            uint64(request["amount"]),
            action_scope,
            request.get("fee", uint64(0)),
            extra_conditions=extra_conditions,
        )

        return {"tx": None, "transactions": None}  # tx_endpoint wrapper will take care of this

    async def verify_signature(self, request: dict[str, Any]) -> EndpointResult:
        """
        Given a public key, message and signature, verify if it is valid.
        :param request:
        :return:
        """
        input_message: str = request["message"]
        signing_mode_str: Optional[str] = request.get("signing_mode")
        # Default to BLS_MESSAGE_AUGMENTATION_HEX_INPUT as this RPC was originally designed to verify
        # signatures made by `chia keys sign`, which uses BLS_MESSAGE_AUGMENTATION_HEX_INPUT
        if signing_mode_str is None:
            signing_mode = SigningMode.BLS_MESSAGE_AUGMENTATION_HEX_INPUT
        else:
            try:
                signing_mode = SigningMode(signing_mode_str)
            except ValueError:
                raise ValueError(f"Invalid signing mode: {signing_mode_str!r}")

        if signing_mode in {SigningMode.CHIP_0002, SigningMode.CHIP_0002_P2_DELEGATED_CONDITIONS}:
            # CHIP-0002 message signatures are made over the tree hash of:
            #   ("Chia Signed Message", message)
            message_to_verify: bytes = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, input_message)).get_tree_hash()
        elif signing_mode == SigningMode.BLS_MESSAGE_AUGMENTATION_HEX_INPUT:
            # Message is expected to be a hex string
            message_to_verify = hexstr_to_bytes(input_message)
        elif signing_mode == SigningMode.BLS_MESSAGE_AUGMENTATION_UTF8_INPUT:
            # Message is expected to be a UTF-8 string
            message_to_verify = bytes(input_message, "utf-8")
        else:
            raise ValueError(f"Unsupported signing mode: {signing_mode_str!r}")

        # Verify using the BLS message augmentation scheme
        is_valid = AugSchemeMPL.verify(
            G1Element.from_bytes(hexstr_to_bytes(request["pubkey"])),
            message_to_verify,
            G2Element.from_bytes(hexstr_to_bytes(request["signature"])),
        )
        address = request.get("address")
        if address is not None:
            # For signatures made by the sign_message_by_address/sign_message_by_id
            # endpoints, the "address" field should contain the p2_address of the NFT/DID
            # that was used to sign the message.
            puzzle_hash: bytes32 = decode_puzzle_hash(address)
            expected_puzzle_hash: Optional[bytes32] = None
            if signing_mode == SigningMode.CHIP_0002_P2_DELEGATED_CONDITIONS:
                puzzle = p2_delegated_conditions.puzzle_for_pk(Program.to(hexstr_to_bytes(request["pubkey"])))
                expected_puzzle_hash = bytes32(puzzle.get_tree_hash())
            else:
                expected_puzzle_hash = puzzle_hash_for_synthetic_public_key(
                    G1Element.from_bytes(hexstr_to_bytes(request["pubkey"]))
                )
            if puzzle_hash != expected_puzzle_hash:
                return {"isValid": False, "error": "Public key doesn't match the address"}
        if is_valid:
            return {"isValid": is_valid}
        else:
            return {"isValid": False, "error": "Signature is invalid."}

    async def sign_message_by_address(self, request: dict[str, Any]) -> EndpointResult:
        """
        Given a derived P2 address, sign the message by its private key.
        :param request:
        :return:
        """
        puzzle_hash: bytes32 = decode_puzzle_hash(request["address"])
        is_hex: bool = request.get("is_hex", False)
        if isinstance(is_hex, str):
            is_hex = True if is_hex.lower() == "true" else False
        safe_mode: bool = request.get("safe_mode", True)
        if isinstance(safe_mode, str):
            safe_mode = True if safe_mode.lower() == "true" else False
        mode: SigningMode = SigningMode.CHIP_0002
        if is_hex and safe_mode:
            mode = SigningMode.CHIP_0002_HEX_INPUT
        elif not is_hex and not safe_mode:
            mode = SigningMode.BLS_MESSAGE_AUGMENTATION_UTF8_INPUT
        elif is_hex and not safe_mode:
            mode = SigningMode.BLS_MESSAGE_AUGMENTATION_HEX_INPUT
        pubkey, signature = await self.service.wallet_state_manager.main_wallet.sign_message(
            request["message"], puzzle_hash, mode
        )
        return {
            "success": True,
            "pubkey": str(pubkey),
            "signature": str(signature),
            "signing_mode": mode.value,
        }

    async def sign_message_by_id(self, request: dict[str, Any]) -> EndpointResult:
        """
        Given a NFT/DID ID, sign the message by the P2 private key.
        :param request:
        :return:
        """
        entity_id: bytes32 = decode_puzzle_hash(request["id"])
        selected_wallet: Optional[WalletProtocol[Any]] = None
        is_hex: bool = request.get("is_hex", False)
        if isinstance(is_hex, str):
            is_hex = True if is_hex.lower() == "true" else False
        safe_mode: bool = request.get("safe_mode", True)
        if isinstance(safe_mode, str):
            safe_mode = True if safe_mode.lower() == "true" else False
        mode: SigningMode = SigningMode.CHIP_0002
        if is_hex and safe_mode:
            mode = SigningMode.CHIP_0002_HEX_INPUT
        elif not is_hex and not safe_mode:
            mode = SigningMode.BLS_MESSAGE_AUGMENTATION_UTF8_INPUT
        elif is_hex and not safe_mode:
            mode = SigningMode.BLS_MESSAGE_AUGMENTATION_HEX_INPUT
        if is_valid_address(request["id"], {AddressType.DID}, self.service.config):
            for wallet in self.service.wallet_state_manager.wallets.values():
                if wallet.type() == WalletType.DECENTRALIZED_ID.value:
                    assert isinstance(wallet, DIDWallet)
                    assert wallet.did_info.origin_coin is not None
                    if wallet.did_info.origin_coin.name() == entity_id:
                        selected_wallet = wallet
                        break
            if selected_wallet is None:
                return {"success": False, "error": f"DID for {entity_id.hex()} doesn't exist."}
            assert isinstance(selected_wallet, DIDWallet)
            pubkey, signature = await selected_wallet.sign_message(request["message"], mode)
            latest_coin_id = (await selected_wallet.get_coin()).name()
        elif is_valid_address(request["id"], {AddressType.NFT}, self.service.config):
            target_nft: Optional[NFTCoinInfo] = None
            for wallet in self.service.wallet_state_manager.wallets.values():
                if wallet.type() == WalletType.NFT.value:
                    assert isinstance(wallet, NFTWallet)
                    nft: Optional[NFTCoinInfo] = await wallet.get_nft(entity_id)
                    if nft is not None:
                        selected_wallet = wallet
                        target_nft = nft
                        break
            if selected_wallet is None or target_nft is None:
                return {"success": False, "error": f"NFT for {entity_id.hex()} doesn't exist."}

            assert isinstance(selected_wallet, NFTWallet)
            pubkey, signature = await selected_wallet.sign_message(request["message"], target_nft, mode)
            latest_coin_id = target_nft.coin.name()
        else:
            return {"success": False, "error": f"Unknown ID type, {request['id']}"}

        return {
            "success": True,
            "pubkey": str(pubkey),
            "signature": str(signature),
            "latest_coin_id": latest_coin_id.hex() if latest_coin_id is not None else None,
            "signing_mode": mode.value,
        }

    ##########################################################################################
    # CATs and Trading
    ##########################################################################################

    async def get_cat_list(self, request: dict[str, Any]) -> EndpointResult:
        return {"cat_list": list(DEFAULT_CATS.values())}

    async def cat_set_name(self, request: dict[str, Any]) -> EndpointResult:
        wallet_id = uint32(request["wallet_id"])
        wallet = self.service.wallet_state_manager.get_wallet(id=wallet_id, required_type=CATWallet)
        await wallet.set_name(str(request["name"]))
        return {"wallet_id": wallet_id}

    async def cat_get_name(self, request: dict[str, Any]) -> EndpointResult:
        wallet_id = uint32(request["wallet_id"])
        wallet = self.service.wallet_state_manager.get_wallet(id=wallet_id, required_type=CATWallet)
        name: str = wallet.get_name()
        return {"wallet_id": wallet_id, "name": name}

    async def get_stray_cats(self, request: dict[str, Any]) -> EndpointResult:
        """
        Get a list of all unacknowledged CATs
        :param request: RPC request
        :return: A list of unacknowledged CATs
        """
        cats = await self.service.wallet_state_manager.interested_store.get_unacknowledged_tokens()
        return {"stray_cats": cats}

    @tx_endpoint(push=True)
    async def cat_spend(
        self,
        request: dict[str, Any],
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
        hold_lock: bool = True,
    ) -> EndpointResult:
        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced.")
        wallet_id = uint32(request["wallet_id"])
        wallet = self.service.wallet_state_manager.get_wallet(id=wallet_id, required_type=CATWallet)

        amounts: list[uint64] = []
        puzzle_hashes: list[bytes32] = []
        memos: list[list[bytes]] = []
        additions: Optional[list[dict[str, Any]]] = request.get("additions")
        if not isinstance(request["fee"], int) or (additions is None and not isinstance(request["amount"], int)):
            raise ValueError("An integer amount or fee is required (too many decimals)")
        if additions is not None:
            for addition in additions:
                receiver_ph = bytes32.from_hexstr(addition["puzzle_hash"])
                if len(receiver_ph) != 32:
                    raise ValueError(f"Address must be 32 bytes. {receiver_ph.hex()}")
                amount = uint64(addition["amount"])
                if amount > self.service.constants.MAX_COIN_AMOUNT:
                    raise ValueError(f"Coin amount cannot exceed {self.service.constants.MAX_COIN_AMOUNT}")
                amounts.append(amount)
                puzzle_hashes.append(receiver_ph)
                if "memos" in addition:
                    memos.append([mem.encode("utf-8") for mem in addition["memos"]])
        else:
            amounts.append(uint64(request["amount"]))
            puzzle_hashes.append(decode_puzzle_hash(request["inner_address"]))
            if "memos" in request:
                memos.append([mem.encode("utf-8") for mem in request["memos"]])
        coins: Optional[set[Coin]] = None
        if "coins" in request and len(request["coins"]) > 0:
            coins = {Coin.from_json_dict(coin_json) for coin_json in request["coins"]}
        fee: uint64 = uint64(request.get("fee", 0))

        cat_discrepancy_params: tuple[Optional[int], Optional[str], Optional[str]] = (
            request.get("extra_delta", None),
            request.get("tail_reveal", None),
            request.get("tail_solution", None),
        )
        cat_discrepancy: Optional[tuple[int, Program, Program]] = None
        if cat_discrepancy_params != (None, None, None):
            if None in cat_discrepancy_params:
                raise ValueError("Specifying extra_delta, tail_reveal, or tail_solution requires specifying the others")
            else:
                assert cat_discrepancy_params[0] is not None
                assert cat_discrepancy_params[1] is not None
                assert cat_discrepancy_params[2] is not None
                cat_discrepancy = (
                    cat_discrepancy_params[0],  # mypy sanitization
                    Program.fromhex(cat_discrepancy_params[1]),
                    Program.fromhex(cat_discrepancy_params[2]),
                )
        if hold_lock:
            async with self.service.wallet_state_manager.lock:
                await wallet.generate_signed_transaction(
                    amounts,
                    puzzle_hashes,
                    action_scope,
                    fee,
                    cat_discrepancy=cat_discrepancy,
                    coins=coins,
                    memos=memos if memos else None,
                    extra_conditions=extra_conditions,
                )
        else:
            await wallet.generate_signed_transaction(
                amounts,
                puzzle_hashes,
                action_scope,
                fee,
                cat_discrepancy=cat_discrepancy,
                coins=coins,
                memos=memos if memos else None,
                extra_conditions=extra_conditions,
            )

        return {
            "transaction": None,  # tx_endpoint wrapper will take care of this
            "transactions": None,  # tx_endpoint wrapper will take care of this
            "transaction_id": None,  # tx_endpoint wrapper will take care of this
        }

    async def cat_get_asset_id(self, request: dict[str, Any]) -> EndpointResult:
        wallet_id = uint32(request["wallet_id"])
        wallet = self.service.wallet_state_manager.get_wallet(id=wallet_id, required_type=CATWallet)
        asset_id: str = wallet.get_asset_id()
        return {"asset_id": asset_id, "wallet_id": wallet_id}

    async def cat_asset_id_to_name(self, request: dict[str, Any]) -> EndpointResult:
        wallet = await self.service.wallet_state_manager.get_wallet_for_asset_id(request["asset_id"])
        if wallet is None:
            if request["asset_id"] in DEFAULT_CATS:
                return {"wallet_id": None, "name": DEFAULT_CATS[request["asset_id"]]["name"]}
            else:
                raise ValueError("The asset ID specified does not belong to a wallet")
        else:
            return {"wallet_id": wallet.id(), "name": (wallet.get_name())}

    @tx_endpoint(push=False)
    async def create_offer_for_ids(
        self,
        request: dict[str, Any],
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> EndpointResult:
        if action_scope.config.push:
            raise ValueError("Cannot push an incomplete spend")  # pragma: no cover

        offer: dict[str, int] = request["offer"]
        fee: uint64 = uint64(request.get("fee", 0))
        validate_only: bool = request.get("validate_only", False)
        driver_dict_str: Optional[dict[str, Any]] = request.get("driver_dict", None)
        marshalled_solver = request.get("solver")
        solver: Optional[Solver]
        if marshalled_solver is None:
            solver = None
        else:
            solver = Solver(info=marshalled_solver)

        # This driver_dict construction is to maintain backward compatibility where everything is assumed to be a CAT
        driver_dict: dict[bytes32, PuzzleInfo] = {}
        if driver_dict_str is None:
            for key, amount in offer.items():
                if amount > 0:
                    try:
                        driver_dict[bytes32.from_hexstr(key)] = PuzzleInfo(
                            {"type": AssetType.CAT.value, "tail": "0x" + key}
                        )
                    except ValueError:
                        pass
        else:
            for key, value in driver_dict_str.items():
                driver_dict[bytes32.from_hexstr(key)] = PuzzleInfo(value)

        modified_offer: dict[Union[int, bytes32], int] = {}
        for wallet_identifier, change in offer.items():
            try:
                modified_offer[bytes32.from_hexstr(wallet_identifier)] = change
            except ValueError:
                modified_offer[int(wallet_identifier)] = change

        async with self.service.wallet_state_manager.lock:
            result = await self.service.wallet_state_manager.trade_manager.create_offer_for_ids(
                modified_offer,
                action_scope,
                driver_dict,
                solver=solver,
                fee=fee,
                validate_only=validate_only,
                extra_conditions=extra_conditions,
            )
        if result[0]:
            _success, trade_record, _error = result
            return {
                "offer": Offer.from_bytes(trade_record.offer).to_bech32(),
                "trade_record": trade_record.to_json_dict_convenience(),
                "transactions": None,  # tx_endpoint wrapper will take care of this
            }
        raise ValueError(result[2])

    async def get_offer_summary(self, request: dict[str, Any]) -> EndpointResult:
        offer_hex: str = request["offer"]

        offer = Offer.from_bech32(offer_hex)
        offered, requested, infos, valid_times = offer.summary()

        if request.get("advanced", False):
            response = {
                "summary": {
                    "offered": offered,
                    "requested": requested,
                    "fees": offer.fees(),
                    "infos": infos,
                    "additions": [c.name().hex() for c in offer.additions()],
                    "removals": [c.name().hex() for c in offer.removals()],
                    "valid_times": {
                        k: v
                        for k, v in valid_times.to_json_dict().items()
                        if k
                        not in {
                            "max_secs_after_created",
                            "min_secs_since_created",
                            "max_blocks_after_created",
                            "min_blocks_since_created",
                        }
                    },
                },
                "id": offer.name(),
            }
        else:
            response = {
                "summary": await self.service.wallet_state_manager.trade_manager.get_offer_summary(offer),
                "id": offer.name(),
            }

        # This is a bit of a hack in favor of returning some more manageable information about CR-CATs
        # A more general solution surely exists, but I'm not sure what it is right now
        return {
            **response,
            "summary": {
                **response["summary"],  # type: ignore[dict-item]
                "infos": {
                    key: (
                        {
                            **info,
                            "also": {
                                **info["also"],
                                "flags": ProofsChecker.from_program(
                                    uncurry_puzzle(Program(assemble(info["also"]["proofs_checker"])))
                                ).flags,
                            },
                        }
                        if "also" in info and "proofs_checker" in info["also"]
                        else info
                    )
                    for key, info in response["summary"]["infos"].items()  # type: ignore[index]
                },
            },
        }

    async def check_offer_validity(self, request: dict[str, Any]) -> EndpointResult:
        offer_hex: str = request["offer"]

        offer = Offer.from_bech32(offer_hex)
        peer = self.service.get_full_node_peer()
        return {
            "valid": (await self.service.wallet_state_manager.trade_manager.check_offer_validity(offer, peer)),
            "id": offer.name(),
        }

    @tx_endpoint(push=True)
    async def take_offer(
        self,
        request: dict[str, Any],
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> EndpointResult:
        offer_hex: str = request["offer"]

        offer = Offer.from_bech32(offer_hex)
        fee: uint64 = uint64(request.get("fee", 0))
        maybe_marshalled_solver: Optional[dict[str, Any]] = request.get("solver")
        solver: Optional[Solver]
        if maybe_marshalled_solver is None:
            solver = None
        else:
            solver = Solver(info=maybe_marshalled_solver)

        peer = self.service.get_full_node_peer()
        trade_record = await self.service.wallet_state_manager.trade_manager.respond_to_offer(
            offer,
            peer,
            action_scope,
            fee=fee,
            solver=solver,
            extra_conditions=extra_conditions,
        )

        async with action_scope.use() as interface:
            interface.side_effects.signing_responses.append(
                SigningResponse(bytes(offer._bundle.aggregated_signature), trade_record.trade_id)
            )

        return {
            "trade_record": trade_record.to_json_dict_convenience(),
            "offer": Offer.from_bytes(trade_record.offer).to_bech32(),
            "transactions": None,  # tx_endpoint wrapper will take care of this
            "signing_responses": None,  # tx_endpoint wrapper will take care of this
        }

    async def get_offer(self, request: dict[str, Any]) -> EndpointResult:
        trade_mgr = self.service.wallet_state_manager.trade_manager

        trade_id = bytes32.from_hexstr(request["trade_id"])
        file_contents: bool = request.get("file_contents", False)
        trade_record: Optional[TradeRecord] = await trade_mgr.get_trade_by_id(bytes32(trade_id))
        if trade_record is None:
            raise ValueError(f"No trade with trade id: {trade_id.hex()}")

        offer_to_return: bytes = trade_record.offer if trade_record.taken_offer is None else trade_record.taken_offer
        offer_value: Optional[str] = Offer.from_bytes(offer_to_return).to_bech32() if file_contents else None
        return {"trade_record": trade_record.to_json_dict_convenience(), "offer": offer_value}

    async def get_all_offers(self, request: dict[str, Any]) -> EndpointResult:
        trade_mgr = self.service.wallet_state_manager.trade_manager

        start: int = request.get("start", 0)
        end: int = request.get("end", 10)
        exclude_my_offers: bool = request.get("exclude_my_offers", False)
        exclude_taken_offers: bool = request.get("exclude_taken_offers", False)
        include_completed: bool = request.get("include_completed", False)
        sort_key: Optional[str] = request.get("sort_key", None)
        reverse: bool = request.get("reverse", False)
        file_contents: bool = request.get("file_contents", False)

        all_trades = await trade_mgr.trade_store.get_trades_between(
            start,
            end,
            sort_key=sort_key,
            reverse=reverse,
            exclude_my_offers=exclude_my_offers,
            exclude_taken_offers=exclude_taken_offers,
            include_completed=include_completed,
        )
        result = []
        offer_values: Optional[list[str]] = [] if file_contents else None
        for trade in all_trades:
            result.append(trade.to_json_dict_convenience())
            if file_contents and offer_values is not None:
                offer_to_return: bytes = trade.offer if trade.taken_offer is None else trade.taken_offer
                offer_values.append(Offer.from_bytes(offer_to_return).to_bech32())

        return {"trade_records": result, "offers": offer_values}

    async def get_offers_count(self, request: dict[str, Any]) -> EndpointResult:
        trade_mgr = self.service.wallet_state_manager.trade_manager

        (total, my_offers_count, taken_offers_count) = await trade_mgr.trade_store.get_trades_count()

        return {"total": total, "my_offers_count": my_offers_count, "taken_offers_count": taken_offers_count}

    @tx_endpoint(push=True)
    async def cancel_offer(
        self,
        request: dict[str, Any],
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> EndpointResult:
        wsm = self.service.wallet_state_manager
        secure = request["secure"]
        trade_id = bytes32.from_hexstr(request["trade_id"])
        fee: uint64 = uint64(request.get("fee", 0))
        async with self.service.wallet_state_manager.lock:
            await wsm.trade_manager.cancel_pending_offers(
                [trade_id], action_scope, fee=fee, secure=secure, extra_conditions=extra_conditions
            )

        return {"transactions": None}  # tx_endpoint wrapper will take care of this

    @tx_endpoint(push=True, merge_spends=False)
    async def cancel_offers(
        self,
        request: dict[str, Any],
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> EndpointResult:
        secure = request["secure"]
        batch_fee: uint64 = uint64(request.get("batch_fee", 0))
        batch_size = request.get("batch_size", 5)
        cancel_all = request.get("cancel_all", False)
        if cancel_all:
            asset_id = None
        else:
            asset_id = request.get("asset_id", "xch")

        start: int = 0
        end: int = start + batch_size
        trade_mgr = self.service.wallet_state_manager.trade_manager
        log.info(f"Start cancelling offers for  {'asset_id: ' + asset_id if asset_id is not None else 'all'} ...")
        # Traverse offers page by page
        key = None
        if asset_id is not None and asset_id != "xch":
            key = bytes32.from_hexstr(asset_id)
        while True:
            records: dict[bytes32, TradeRecord] = {}
            trades = await trade_mgr.trade_store.get_trades_between(
                start,
                end,
                reverse=True,
                exclude_my_offers=False,
                exclude_taken_offers=True,
                include_completed=False,
            )
            for trade in trades:
                if cancel_all:
                    records[trade.trade_id] = trade
                    continue
                if trade.offer and trade.offer != b"":
                    offer = Offer.from_bytes(trade.offer)
                    if key in offer.arbitrage():
                        records[trade.trade_id] = trade
                        continue

            if len(records) == 0:
                break

            async with self.service.wallet_state_manager.lock:
                await trade_mgr.cancel_pending_offers(
                    list(records.keys()),
                    action_scope,
                    batch_fee,
                    secure,
                    records,
                    extra_conditions=extra_conditions,
                )

            log.info(f"Cancelled offers {start} to {end} ...")
            # If fewer records were returned than requested, we're done
            if len(trades) < batch_size:
                break
            start = end
            end += batch_size

        return {"transactions": None}  # tx_endpoint wrapper will take care of this

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

    @tx_endpoint(push=True)
    @marshal
    async def did_update_recovery_ids(
        self,
        request: DIDUpdateRecoveryIDs,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> DIDUpdateRecoveryIDsResponse:
        wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=DIDWallet)
        recovery_list = [decode_puzzle_hash(puzzle_hash) for puzzle_hash in request.new_list]
        new_amount_verifications_required = (
            request.num_verifications_required
            if request.num_verifications_required is not None
            else uint64(len(recovery_list))
        )
        async with self.service.wallet_state_manager.lock:
            update_success = await wallet.update_recovery_list(recovery_list, new_amount_verifications_required)
            # Update coin with new ID info
            if update_success:
                await wallet.create_update_spend(action_scope, fee=request.fee, extra_conditions=extra_conditions)
                # tx_endpoint will take care of default values here
                return DIDUpdateRecoveryIDsResponse([], [])
            else:
                raise RuntimeError("updating recovery list failed")

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
        num_verification_int: Optional[uint16] = uint16(num_verification.as_int())
        assert num_verification_int is not None
        did_data: DIDCoinData = DIDCoinData(
            p2_puzzle,
            bytes32(recovery_list_hash.as_atom()) if recovery_list_hash != Program.to(None) else None,
            num_verification_int,
            singleton_struct,
            metadata,
            get_inner_puzzle_from_singleton(coin_spend.puzzle_reveal),
            coin_state,
        )
        hinted_coins, _ = compute_spend_hints_and_additions(coin_spend)
        # Hint is required, if it doesn't have any hint then it should be invalid
        hint: Optional[bytes32] = None
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
            did_wallet: Optional[DIDWallet] = None
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
    async def did_get_recovery_list(self, request: DIDGetRecoveryList) -> DIDGetRecoveryListResponse:
        wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=DIDWallet)
        recovery_list = wallet.did_info.backup_ids
        recovery_dids = []
        for backup_id in recovery_list:
            recovery_dids.append(encode_puzzle_hash(backup_id, AddressType.DID.hrp(self.service.config)))
        return DIDGetRecoveryListResponse(
            wallet_id=request.wallet_id,
            recovery_list=recovery_dids,
            num_required=uint16(wallet.did_info.num_of_backup_ids_needed),
        )

    @marshal
    async def did_get_metadata(self, request: DIDGetMetadata) -> DIDGetMetadataResponse:
        wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=DIDWallet)
        metadata = json.loads(wallet.did_info.metadata)
        return DIDGetMetadataResponse(wallet_id=request.wallet_id, metadata=metadata)

    # TODO: this needs a test
    # Don't need full @tx_endpoint decorator here, but "push" is still a valid option
    async def did_recovery_spend(self, request: dict[str, Any]) -> EndpointResult:  # pragma: no cover
        wallet_id = uint32(request["wallet_id"])
        wallet = self.service.wallet_state_manager.get_wallet(id=wallet_id, required_type=DIDWallet)
        if len(request["attest_data"]) < wallet.did_info.num_of_backup_ids_needed:
            return {"success": False, "reason": "insufficient messages"}
        async with self.service.wallet_state_manager.lock:
            (
                info_list,
                message_spend_bundle,
            ) = await wallet.load_attest_files_for_recovery_spend(request["attest_data"])

            if "pubkey" in request:
                pubkey = G1Element.from_bytes(hexstr_to_bytes(request["pubkey"]))
            else:
                assert wallet.did_info.temp_pubkey is not None
                pubkey = G1Element.from_bytes(wallet.did_info.temp_pubkey)

            if "puzhash" in request:
                puzhash = bytes32.from_hexstr(request["puzhash"])
            else:
                assert wallet.did_info.temp_puzhash is not None
                puzhash = wallet.did_info.temp_puzhash

            assert wallet.did_info.temp_coin is not None
            async with self.service.wallet_state_manager.new_action_scope(
                DEFAULT_TX_CONFIG, push=request.get("push", True)
            ) as action_scope:
                await wallet.recovery_spend(
                    wallet.did_info.temp_coin,
                    puzhash,
                    info_list,
                    pubkey,
                    message_spend_bundle,
                    action_scope,
                )
            [tx] = action_scope.side_effects.transactions
        return {
            "success": True,
            "spend_bundle": tx.spend_bundle,
            "transactions": [tx.to_json_dict_convenience(self.service.config)],
        }

    @marshal
    async def did_get_pubkey(self, request: DIDGetPubkey) -> DIDGetPubkeyResponse:
        wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=DIDWallet)
        return DIDGetPubkeyResponse(
            (await wallet.wallet_state_manager.get_unused_derivation_record(request.wallet_id)).pubkey
        )

    # TODO: this needs a test
    @tx_endpoint(push=True)
    async def did_create_attest(
        self,
        request: dict[str, Any],
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> EndpointResult:  # pragma: no cover
        wallet_id = uint32(request["wallet_id"])
        wallet = self.service.wallet_state_manager.get_wallet(id=wallet_id, required_type=DIDWallet)
        async with self.service.wallet_state_manager.lock:
            info = await wallet.get_info_for_recovery()
            coin = bytes32.from_hexstr(request["coin_name"])
            pubkey = G1Element.from_bytes(hexstr_to_bytes(request["pubkey"]))
            message_spend_bundle, attest_data = await wallet.create_attestment(
                coin,
                bytes32.from_hexstr(request["puzhash"]),
                pubkey,
                action_scope,
                extra_conditions=extra_conditions,
            )
        if info is not None:
            return {
                "success": True,
                "message_spend_bundle": bytes(message_spend_bundle).hex(),
                "info": [info[0].hex(), info[1].hex(), info[2]],
                "attest_data": attest_data,
                "transactions": None,  # tx_endpoint wrapper will take care of this
            }
        else:
            return {"success": False}

    @marshal
    async def did_get_information_needed_for_recovery(self, request: DIDGetRecoveryInfo) -> DIDGetRecoveryInfoResponse:
        did_wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=DIDWallet)
        my_did = encode_puzzle_hash(
            bytes32.from_hexstr(did_wallet.get_my_DID()), AddressType.DID.hrp(self.service.config)
        )
        assert did_wallet.did_info.temp_coin is not None
        coin_name = did_wallet.did_info.temp_coin.name()
        return DIDGetRecoveryInfoResponse(
            wallet_id=request.wallet_id,
            my_did=my_did,
            coin_name=coin_name,
            newpuzhash=did_wallet.did_info.temp_puzhash,
            pubkey=G1Element.from_bytes(did_wallet.did_info.temp_pubkey)
            if did_wallet.did_info.temp_pubkey is not None
            else None,
            backup_dids=did_wallet.did_info.backup_ids,
        )

    @marshal
    async def did_get_current_coin_info(self, request: DIDGetCurrentCoinInfo) -> DIDGetCurrentCoinInfoResponse:
        did_wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=DIDWallet)
        my_did = encode_puzzle_hash(
            bytes32.from_hexstr(did_wallet.get_my_DID()), AddressType.DID.hrp(self.service.config)
        )

        did_coin_threeple = await did_wallet.get_info_for_recovery()
        assert my_did is not None
        assert did_coin_threeple is not None
        return DIDGetCurrentCoinInfoResponse(
            wallet_id=request.wallet_id,
            my_did=my_did,
            did_parent=did_coin_threeple[0],
            did_innerpuz=did_coin_threeple[1],
            did_amount=did_coin_threeple[2],
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
        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced.")
        did_wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=DIDWallet)
        puzzle_hash: bytes32 = decode_puzzle_hash(request.inner_address)
        async with self.service.wallet_state_manager.lock:
            await did_wallet.transfer_did(
                puzzle_hash,
                request.fee,
                request.with_recovery_info,
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
                did_id: Optional[bytes] = b""
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
            try:
                nft_wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=NFTWallet)
            except KeyError:
                # wallet not found
                raise ValueError(f"Wallet {request.wallet_id} not found.")
            count = await nft_wallet.get_nft_count()
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
        did_id: Optional[bytes32] = None
        if request.did_id is not None:
            did_id = decode_puzzle_hash(request.did_id)
        for wallet in self.service.wallet_state_manager.wallets.values():
            if isinstance(wallet, NFTWallet) and wallet.get_did() == did_id:
                return NFTGetByDIDResponse(uint32(wallet.wallet_id))
        raise ValueError(f"Cannot find a NFT wallet DID = {did_id}")

    @marshal
    async def nft_get_wallet_did(self, request: NFTGetWalletDID) -> NFTGetWalletDIDResponse:
        nft_wallet = self.service.wallet_state_manager.get_wallet(id=request.wallet_id, required_type=NFTWallet)
        did_bytes: Optional[bytes32] = nft_wallet.get_did()
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
                nft_wallet_did: Optional[bytes32] = wallet.get_did()
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

        uncurried_nft: Optional[UncurriedNFT] = UncurriedNFT.uncurry(*full_puzzle.uncurry())
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
        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced.")
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
            if request.xch_change_target.startswith("xch"):
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
        for record in tx_records:
            if record.wallet_id not in self.service.wallet_state_manager.wallets:
                continue
            if record.type == TransactionType.COINBASE_REWARD.value:
                if self.service.wallet_state_manager.wallets[record.wallet_id].type() == WalletType.POOLING_WALLET:
                    # Don't add pool rewards for pool wallets.
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
    async def create_signed_transaction(
        self,
        request: dict[str, Any],
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
        hold_lock: bool = True,
    ) -> EndpointResult:
        if "wallet_id" in request:
            wallet_id = uint32(request["wallet_id"])
            wallet = self.service.wallet_state_manager.wallets[wallet_id]
        else:
            wallet = self.service.wallet_state_manager.main_wallet

        assert isinstance(wallet, (Wallet, CATWallet, CRCATWallet)), (
            "create_signed_transaction only works for standard and CAT wallets"
        )

        if "additions" not in request or len(request["additions"]) < 1:
            raise ValueError("Specify additions list")

        additions: list[dict[str, Any]] = request["additions"]
        amount_0: uint64 = uint64(additions[0]["amount"])
        assert amount_0 <= self.service.constants.MAX_COIN_AMOUNT
        puzzle_hash_0 = bytes32.from_hexstr(additions[0]["puzzle_hash"])
        if len(puzzle_hash_0) != 32:
            raise ValueError(f"Address must be 32 bytes. {puzzle_hash_0.hex()}")

        memos_0 = [] if "memos" not in additions[0] else [mem.encode("utf-8") for mem in additions[0]["memos"]]

        additional_outputs: list[CreateCoin] = []
        for addition in additions[1:]:
            receiver_ph = bytes32.from_hexstr(addition["puzzle_hash"])
            if len(receiver_ph) != 32:
                raise ValueError(f"Address must be 32 bytes. {receiver_ph.hex()}")
            amount = uint64(addition["amount"])
            if amount > self.service.constants.MAX_COIN_AMOUNT:
                raise ValueError(f"Coin amount cannot exceed {self.service.constants.MAX_COIN_AMOUNT}")
            memos = [] if "memos" not in addition else [mem.encode("utf-8") for mem in addition["memos"]]
            additional_outputs.append(CreateCoin(receiver_ph, amount, memos))

        fee: uint64 = uint64(request.get("fee", 0))

        coins = None
        if "coins" in request and len(request["coins"]) > 0:
            coins = {Coin.from_json_dict(coin_json) for coin_json in request["coins"]}

        async def _generate_signed_transaction() -> EndpointResult:
            await wallet.generate_signed_transaction(
                [amount_0] + [output.amount for output in additional_outputs],
                [bytes32(puzzle_hash_0)] + [output.puzzle_hash for output in additional_outputs],
                action_scope,
                fee,
                coins=coins,
                memos=[memos_0] + [output.memos if output.memos is not None else [] for output in additional_outputs],
                extra_conditions=(
                    *extra_conditions,
                    *(
                        AssertCoinAnnouncement(
                            asserted_id=bytes32.from_hexstr(ca["coin_id"]),
                            asserted_msg=(
                                hexstr_to_bytes(ca["message"])
                                if request.get("morph_bytes") is None
                                else std_hash(hexstr_to_bytes(ca["morph_bytes"]) + hexstr_to_bytes(ca["message"]))
                            ),
                        )
                        for ca in request.get("coin_announcements", [])
                    ),
                    *(
                        AssertPuzzleAnnouncement(
                            asserted_ph=bytes32.from_hexstr(pa["puzzle_hash"]),
                            asserted_msg=(
                                hexstr_to_bytes(pa["message"])
                                if request.get("morph_bytes") is None
                                else std_hash(hexstr_to_bytes(pa["morph_bytes"]) + hexstr_to_bytes(pa["message"]))
                            ),
                        )
                        for pa in request.get("puzzle_announcements", [])
                    ),
                ),
            )
            # tx_endpoint wrapper will take care of this
            return {"signed_txs": None, "signed_tx": None, "transactions": None}

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

        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced.")

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

        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced.")

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
        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced before collecting rewards")
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
        puzhash: Optional[bytes32] = None
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

        vc_proofs: Optional[VCProofs] = await vc_wallet.store.get_proofs_for_root(request.root)
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
    async def crcat_approve_pending(
        self,
        request: dict[str, Any],
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> EndpointResult:
        """
        Moving any "pending approval" CR-CATs into the spendable balance of the wallet
        :param request: Required 'wallet_id'. Optional 'min_amount_to_claim' (default: full balance).
        Standard transaction params 'fee' & 'reuse_puzhash'.
        :return: a list of all relevant 'transactions' (TransactionRecord) that this spend generates:
        (CRCAT TX + fee TX)
        """

        @streamable
        @dataclasses.dataclass(frozen=True)
        class CRCATApprovePending(Streamable):
            wallet_id: uint32
            min_amount_to_claim: uint64
            fee: uint64 = uint64(0)

        parsed_request = CRCATApprovePending.from_json_dict(request)
        cr_cat_wallet = self.service.wallet_state_manager.wallets[parsed_request.wallet_id]
        assert isinstance(cr_cat_wallet, CRCATWallet)

        await cr_cat_wallet.claim_pending_approval_balance(
            parsed_request.min_amount_to_claim,
            action_scope,
            fee=parsed_request.fee,
            extra_conditions=extra_conditions,
        )

        return {
            "transactions": None,  # tx_endpoint wrapper will take care of this
        }

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
