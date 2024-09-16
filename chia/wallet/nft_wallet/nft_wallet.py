from __future__ import annotations

import dataclasses
import json
import logging
import math
import time
from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional, Set, Tuple, Type, TypeVar, cast

from chia_rs import AugSchemeMPL, G1Element, G2Element
from clvm.casts import int_from_bytes, int_to_bytes
from typing_extensions import Unpack

import chia.wallet.singleton
from chia.protocols.wallet_protocol import CoinState
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend, compute_additions, make_spend
from chia.types.signing_mode import CHIP_0002_SIGN_MESSAGE_PREFIX, SigningMode
from chia.util.hash import std_hash
from chia.util.ints import uint16, uint32, uint64, uint128
from chia.wallet.conditions import (
    AssertCoinAnnouncement,
    AssertPuzzleAnnouncement,
    Condition,
    CreateCoinAnnouncement,
    CreatePuzzleAnnouncement,
    UnknownCondition,
    parse_timelock_info,
)
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.did_wallet import did_wallet_puzzles
from chia.wallet.did_wallet.did_info import DIDInfo
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.nft_wallet import nft_puzzles
from chia.wallet.nft_wallet.nft_info import NFTCoinInfo, NFTWalletInfo
from chia.wallet.nft_wallet.nft_puzzles import NFT_METADATA_UPDATER, create_ownership_layer_puzzle, get_metadata_and_phs
from chia.wallet.nft_wallet.uncurry_nft import NFTCoinData, UncurriedNFT
from chia.wallet.outer_puzzles import AssetType, construct_puzzle, match_puzzle, solve_puzzle
from chia.wallet.payment import Payment
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
    puzzle_for_pk,
)
from chia.wallet.trading.offer import OFFER_MOD, OFFER_MOD_HASH, NotarizedPayment, Offer
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_action_scope import WalletActionScope
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_nft_store import WalletNftStore
from chia.wallet.wallet_protocol import GSTOptionalArgs, WalletProtocol
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

_T_NFTWallet = TypeVar("_T_NFTWallet", bound="NFTWallet")


class NFTWallet:
    if TYPE_CHECKING:
        _protocol_check: ClassVar[WalletProtocol[NFTCoinData]] = cast("NFTWallet", None)

    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    nft_wallet_info: NFTWalletInfo
    standard_wallet: Wallet
    wallet_id: int
    nft_store: WalletNftStore

    @property
    def did_id(self) -> Optional[bytes32]:
        return self.nft_wallet_info.did_id

    @classmethod
    async def create_new_nft_wallet(
        cls: Type[_T_NFTWallet],
        wallet_state_manager: Any,
        wallet: Wallet,
        did_id: Optional[bytes32] = None,
        name: Optional[str] = None,
    ) -> _T_NFTWallet:
        """
        This must be called under the wallet state manager lock
        """
        self = cls()
        self.standard_wallet = wallet
        if name is None:
            name = "NFT Wallet"
        self.log = logging.getLogger(name if name else __name__)
        self.wallet_state_manager = wallet_state_manager
        self.nft_wallet_info = NFTWalletInfo(did_id)
        info_as_string = json.dumps(self.nft_wallet_info.to_json_dict())
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            name, uint32(WalletType.NFT.value), info_as_string
        )
        self.wallet_id = self.wallet_info.id
        self.nft_store = wallet_state_manager.nft_store
        self.log.debug("NFT wallet id: %r and standard wallet id: %r", self.wallet_id, self.standard_wallet.wallet_id)

        await self.wallet_state_manager.add_new_wallet(self)
        self.log.debug("Generated a new NFT wallet: %s", self.__dict__)
        return self

    @classmethod
    async def create(
        cls: Type[_T_NFTWallet],
        wallet_state_manager: Any,
        wallet: Wallet,
        wallet_info: WalletInfo,
        name: Optional[str] = None,
    ) -> _T_NFTWallet:
        self = cls()
        self.log = logging.getLogger(name if name else __name__)
        self.wallet_state_manager = wallet_state_manager
        self.wallet_info = wallet_info
        self.wallet_id = wallet_info.id
        self.standard_wallet = wallet
        self.wallet_info = wallet_info
        self.nft_store = wallet_state_manager.nft_store
        self.nft_wallet_info = NFTWalletInfo.from_json_dict(json.loads(wallet_info.data))
        return self

    @classmethod
    def type(cls) -> WalletType:
        return WalletType.NFT

    def id(self) -> uint32:
        return self.wallet_info.id

    def get_did(self) -> Optional[bytes32]:
        return self.did_id

    async def get_confirmed_balance(self, record_list: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        """The NFT wallet doesn't really have a balance."""
        return uint128(0)

    async def get_unconfirmed_balance(self, record_list: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        """The NFT wallet doesn't really have a balance."""
        return uint128(0)

    async def get_spendable_balance(self, unspent_records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        """The NFT wallet doesn't really have a balance."""
        return uint128(0)

    async def get_pending_change_balance(self) -> uint64:
        return uint64(0)

    async def get_max_send_amount(self, records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        """This is the confirmed balance, which we set to 0 as the NFT wallet doesn't have one."""
        return uint128(0)

    async def get_nft_coin_by_id(self, nft_coin_id: bytes32) -> NFTCoinInfo:
        nft_coin = await self.nft_store.get_nft_by_coin_id(nft_coin_id)
        if nft_coin is None:
            raise KeyError(f"Couldn't find coin with id: {nft_coin_id}")
        return nft_coin

    async def coin_added(
        self, coin: Coin, height: uint32, peer: WSChiaConnection, parent_coin_data: Optional[NFTCoinData]
    ) -> None:
        """Notification from wallet state manager that wallet has been received."""
        self.log.info(f"NFT wallet %s has been notified that {coin} was added", self.get_name())
        if await self.nft_store.exists(coin.name()):
            # already added
            return
        assert isinstance(parent_coin_data, NFTCoinData), f"Invalid NFT coin data: {parent_coin_data}"
        await self.puzzle_solution_received(coin, parent_coin_data, peer)

    async def puzzle_solution_received(self, coin: Coin, data: NFTCoinData, peer: WSChiaConnection) -> None:
        self.log.debug("Puzzle solution received to wallet: %s", self.wallet_info)
        # At this point, the puzzle must be a NFT puzzle.
        # This method will be called only when the wallet state manager uncurried this coin as a NFT puzzle.

        uncurried_nft: UncurriedNFT = data.uncurried_nft
        self.log.debug(
            "found the info for NFT coin %s %s %s",
            coin.name().hex(),
            uncurried_nft.inner_puzzle,
            uncurried_nft.singleton_struct,
        )
        singleton_id = uncurried_nft.singleton_launcher_id
        parent_inner_puzhash = uncurried_nft.nft_state_layer.get_tree_hash()
        metadata, p2_puzzle_hash = get_metadata_and_phs(uncurried_nft, data.parent_coin_spend.solution)
        self.log.debug("Got back puzhash from solution: %s", p2_puzzle_hash)
        self.log.debug("Got back updated metadata: %s", metadata)
        derivation_record: Optional[DerivationRecord] = (
            await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(p2_puzzle_hash)
        )
        self.log.debug("Record for %s is: %s", p2_puzzle_hash, derivation_record)
        if derivation_record is None:
            self.log.debug("Not our NFT, pointing to %s, skipping", p2_puzzle_hash)
            return
        p2_puzzle = puzzle_for_pk(derivation_record.pubkey)
        launcher_coin_states: List[CoinState] = await self.wallet_state_manager.wallet_node.get_coin_state(
            [singleton_id], peer=peer
        )
        assert (
            launcher_coin_states is not None
            and len(launcher_coin_states) == 1
            and launcher_coin_states[0].spent_height is not None
        )
        mint_height: uint32 = uint32(launcher_coin_states[0].spent_height)
        minter_did = None
        if uncurried_nft.supports_did:
            inner_puzzle = nft_puzzles.recurry_nft_puzzle(
                uncurried_nft, data.parent_coin_spend.solution.to_program(), p2_puzzle
            )
            minter_did = await self.wallet_state_manager.get_minter_did(launcher_coin_states[0].coin, peer)
        else:
            inner_puzzle = p2_puzzle
        child_puzzle: Program = nft_puzzles.create_full_puzzle(
            singleton_id,
            Program.to(metadata),
            bytes32(uncurried_nft.metadata_updater_hash.as_atom()),
            inner_puzzle,
        )
        self.log.debug(
            "Created NFT full puzzle with inner: %s",
            nft_puzzles.create_full_puzzle_with_nft_puzzle(singleton_id, uncurried_nft.inner_puzzle),
        )
        child_puzzle_hash = child_puzzle.get_tree_hash()
        for new_coin in compute_additions(data.parent_coin_spend):
            self.log.debug(
                "Comparing addition: %s with %s, amount: %s ",
                new_coin.puzzle_hash,
                child_puzzle_hash,
                new_coin.amount,
            )
            if new_coin.puzzle_hash == child_puzzle_hash:
                child_coin = new_coin
                break
        else:
            raise ValueError("Couldn't generate child puzzle for NFT")

        self.log.info("Adding a new NFT to wallet: %s", child_coin)
        # all is well, lets add NFT to our local db
        parent_coin = data.parent_coin_state.coin
        confirmed_height = (
            None if data.parent_coin_state.spent_height is None else uint32(data.parent_coin_state.spent_height)
        )

        if confirmed_height is None:
            raise ValueError("Error finding parent")

        await self.add_coin(
            child_coin,
            singleton_id,
            child_puzzle,
            LineageProof(parent_coin.parent_coin_info, parent_inner_puzhash, uint64(parent_coin.amount)),
            mint_height,
            minter_did,
            confirmed_height,
        )

    async def add_coin(
        self,
        coin: Coin,
        nft_id: bytes32,
        puzzle: Program,
        lineage_proof: LineageProof,
        mint_height: uint32,
        minter_did: Optional[bytes32],
        confirmed_height: uint32,
    ) -> None:
        new_nft = NFTCoinInfo(nft_id, coin, lineage_proof, puzzle, mint_height, minter_did, confirmed_height)
        await self.wallet_state_manager.nft_store.save_nft(self.id(), self.get_did(), new_nft)
        await self.wallet_state_manager.add_interested_coin_ids([coin.name()])
        self.wallet_state_manager.state_changed("nft_coin_added", self.wallet_info.id)

    async def remove_coin(self, coin: Coin, height: uint32) -> None:
        nft_coin_info = await self.nft_store.get_nft_by_coin_id(coin.name())
        if nft_coin_info:
            await self.nft_store.delete_nft_by_coin_id(coin.name(), height)
            self.wallet_state_manager.state_changed("nft_coin_removed", self.wallet_info.id)
            num = await self.get_nft_count()
            if num == 0 and self.did_id is not None:
                # Check if the wallet owns the DID
                for did_wallet in await self.wallet_state_manager.get_all_wallet_info_entries(
                    wallet_type=WalletType.DECENTRALIZED_ID
                ):
                    did_wallet_info: DIDInfo = DIDInfo.from_json_dict(json.loads(did_wallet.data))
                    assert did_wallet_info.origin_coin is not None
                    if did_wallet_info.origin_coin.name() == self.did_id:
                        return
                self.log.info(f"No NFT, deleting wallet {self.wallet_info.name} ...")
                await self.wallet_state_manager.user_store.delete_wallet(self.wallet_info.id)
                self.wallet_state_manager.wallets.pop(self.wallet_info.id)
        else:
            self.log.info("Tried removing NFT coin that doesn't exist: %s", coin.name())

    async def get_did_approval_info(
        self,
        nft_ids: List[bytes32],
        action_scope: WalletActionScope,
        did_id: Optional[bytes32] = None,
    ) -> bytes32:
        """Get DID spend with announcement created we need to transfer NFT with did with current inner hash of DID

        We also store `did_id` and then iterate to find the did wallet as we'd otherwise have to subscribe to
        any changes to DID wallet and storing wallet_id is not guaranteed to be consistent on wallet crash/reset.
        """
        if did_id is None:
            did_id = self.did_id
        did_inner_hash: bytes32
        for _, wallet in self.wallet_state_manager.wallets.items():
            self.log.debug("Checking wallet type %s", wallet.type())
            if wallet.type() == WalletType.DECENTRALIZED_ID:
                self.log.debug("Found a DID wallet, checking did: %r == %r", wallet.get_my_DID(), did_id)
                if bytes32.fromhex(wallet.get_my_DID()) == did_id:
                    self.log.debug("Creating announcement from DID for nft_ids: %s", nft_ids)
                    await wallet.create_message_spend(
                        action_scope, extra_conditions=(CreatePuzzleAnnouncement(id) for id in nft_ids)
                    )
                    did_inner_hash = wallet.did_info.current_inner.get_tree_hash()
                    break
        else:
            raise ValueError(f"Missing DID Wallet for did_id: {did_id}")
        return did_inner_hash

    async def generate_new_nft(
        self,
        metadata: Program,
        action_scope: WalletActionScope,
        target_puzzle_hash: Optional[bytes32] = None,
        royalty_puzzle_hash: Optional[bytes32] = None,
        percentage: uint16 = uint16(0),
        did_id: Optional[bytes] = None,
        fee: uint64 = uint64(0),
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> bytes32:
        """
        This must be called under the wallet state manager lock
        """
        if self.did_id is not None and did_id is None:
            # For a DID enabled NFT wallet it cannot mint NFT0. Mint NFT1 instead.
            did_id = self.did_id
        amount = uint64(1)
        # ensure percentage is uint16
        try:
            percentage = uint16(percentage)
        except ValueError:
            raise ValueError("Percentage must be lower than 655%")
        coins = await self.standard_wallet.select_coins(uint64(amount + fee), action_scope)
        if coins is None:
            return None
        origin = coins.copy().pop()
        genesis_launcher_puz = nft_puzzles.LAUNCHER_PUZZLE
        # nft_id == singleton_id == launcher_id == launcher_coin.name()
        launcher_coin = Coin(origin.name(), nft_puzzles.LAUNCHER_PUZZLE_HASH, uint64(amount))
        self.log.debug("Generating NFT with launcher coin %s and metadata: %s", launcher_coin, metadata)

        p2_inner_puzzle = await self.standard_wallet.get_puzzle(new=not action_scope.config.tx_config.reuse_puzhash)
        if not target_puzzle_hash:
            target_puzzle_hash = p2_inner_puzzle.get_tree_hash()
        self.log.debug("Attempt to generate a new NFT to %s", target_puzzle_hash.hex())
        if did_id is not None:
            self.log.debug("Creating provenant NFT")
            # eve coin DID can be set to whatever so we keep it empty
            # WARNING: wallets should always ignore DID value for eve coins as they can be set
            #          to any DID without approval
            inner_puzzle = create_ownership_layer_puzzle(
                launcher_coin.name(), b"", p2_inner_puzzle, percentage, royalty_puzzle_hash=royalty_puzzle_hash
            )
            self.log.debug("Got back ownership inner puzzle: %s", inner_puzzle)
        else:
            self.log.debug("Creating standard NFT")
            inner_puzzle = p2_inner_puzzle

        # singleton eve puzzle
        eve_fullpuz = nft_puzzles.create_full_puzzle(
            launcher_coin.name(), metadata, NFT_METADATA_UPDATER.get_tree_hash(), inner_puzzle
        )
        eve_fullpuz_hash = eve_fullpuz.get_tree_hash()
        # launcher announcement
        announcement_message = Program.to([eve_fullpuz_hash, amount, []]).get_tree_hash()

        self.log.debug(
            "Creating transaction for launcher: %s and other coins: %s (%s)", origin, coins, announcement_message
        )
        # store the launcher transaction in the wallet state
        await self.standard_wallet.generate_signed_transaction(
            uint64(amount),
            nft_puzzles.LAUNCHER_PUZZLE_HASH,
            action_scope,
            fee,
            coins,
            None,
            origin_id=origin.name(),
            extra_conditions=(
                *extra_conditions,
                AssertCoinAnnouncement(asserted_id=launcher_coin.name(), asserted_msg=announcement_message),
            ),
        )
        genesis_launcher_solution = Program.to([eve_fullpuz_hash, amount, []])

        # launcher spend to generate the singleton
        launcher_cs = make_spend(launcher_coin, genesis_launcher_puz, genesis_launcher_solution)
        launcher_sb = WalletSpendBundle([launcher_cs], AugSchemeMPL.aggregate([]))

        eve_coin = Coin(launcher_coin.name(), eve_fullpuz_hash, uint64(amount))

        async with action_scope.use() as interface:
            interface.side_effects.extra_spends.append(launcher_sb)

        # Create inner solution for eve spend
        did_inner_hash = b""
        if did_id is not None:
            if did_id != b"":
                did_inner_hash = await self.get_did_approval_info([launcher_coin.name()], action_scope)
        nft_coin = NFTCoinInfo(
            nft_id=launcher_coin.name(),
            coin=eve_coin,
            lineage_proof=LineageProof(parent_name=launcher_coin.parent_coin_info, amount=uint64(launcher_coin.amount)),
            full_puzzle=eve_fullpuz,
            mint_height=uint32(0),
            minter_did=bytes32(did_id) if did_id is not None and did_id != b"" else None,
        )
        # Don't set fee, it is covered in the tx_record
        await self.generate_signed_transaction(
            [uint64(eve_coin.amount)],
            [target_puzzle_hash],
            action_scope,
            nft_coin=nft_coin,
            new_owner=did_id,
            new_did_inner_hash=did_inner_hash,
            memos=[[target_puzzle_hash]],
        )

        return launcher_coin.name()

    async def update_metadata(
        self,
        nft_coin_info: NFTCoinInfo,
        key: str,
        uri: str,
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> None:
        uncurried_nft = UncurriedNFT.uncurry(*nft_coin_info.full_puzzle.uncurry())
        assert uncurried_nft is not None
        puzzle_hash = uncurried_nft.p2_puzzle.get_tree_hash()

        self.log.info(
            "Attempting to add urls to NFT coin %s in the metadata: %s",
            nft_coin_info.coin.name(),
            uncurried_nft.metadata,
        )
        await self.generate_signed_transaction(
            [uint64(nft_coin_info.coin.amount)],
            [puzzle_hash],
            action_scope,
            fee,
            {nft_coin_info.coin},
            metadata_update=(key, uri),
            extra_conditions=extra_conditions,
        )
        await self.update_coin_status(nft_coin_info.coin.name(), True)
        self.wallet_state_manager.state_changed("nft_coin_updated", self.wallet_info.id)

    async def get_current_nfts(self, start_index: int = 0, count: int = 50) -> List[NFTCoinInfo]:
        return await self.nft_store.get_nft_list(wallet_id=self.id(), start_index=start_index, count=count)

    async def get_nft_count(self) -> int:
        return await self.nft_store.count(wallet_id=self.id())

    async def is_empty(self) -> bool:
        return await self.nft_store.is_empty(wallet_id=self.id())

    async def update_coin_status(self, coin_id: bytes32, pending_transaction: bool) -> None:
        await self.nft_store.update_pending_transaction(coin_id, pending_transaction)

    async def save_info(self, nft_info: NFTWalletInfo) -> None:
        self.nft_wallet_info = nft_info
        current_info = self.wallet_info
        data_str = json.dumps(nft_info.to_json_dict())
        wallet_info = WalletInfo(current_info.id, current_info.name, current_info.type, data_str)
        self.wallet_info = wallet_info
        await self.wallet_state_manager.user_store.update_wallet(wallet_info)

    async def convert_puzzle_hash(self, puzhash: bytes32) -> bytes32:
        return puzhash

    async def get_nft(self, launcher_id: bytes32) -> Optional[NFTCoinInfo]:
        return await self.nft_store.get_nft_by_id(launcher_id)

    async def get_puzzle_info(self, nft_id: bytes32) -> PuzzleInfo:
        nft_coin: Optional[NFTCoinInfo] = await self.get_nft(nft_id)
        if nft_coin is None:
            raise ValueError("An asset ID was specified that this wallet doesn't track")
        puzzle_info: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(nft_coin.full_puzzle))
        if puzzle_info is None:
            raise ValueError("Internal Error: NFT wallet is tracking a non NFT coin")
        else:
            return puzzle_info

    async def sign_message(self, message: str, nft: NFTCoinInfo, mode: SigningMode) -> Tuple[G1Element, G2Element]:
        uncurried_nft = UncurriedNFT.uncurry(*nft.full_puzzle.uncurry())
        if uncurried_nft is not None:
            p2_puzzle = uncurried_nft.p2_puzzle
            puzzle_hash = p2_puzzle.get_tree_hash()
            private = await self.wallet_state_manager.get_private_key(puzzle_hash)
            synthetic_secret_key = calculate_synthetic_secret_key(private, DEFAULT_HIDDEN_PUZZLE_HASH)
            synthetic_pk = synthetic_secret_key.get_g1()
            if mode == SigningMode.CHIP_0002_HEX_INPUT:
                hex_message: bytes = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, bytes.fromhex(message))).get_tree_hash()
            elif mode == SigningMode.BLS_MESSAGE_AUGMENTATION_UTF8_INPUT:
                hex_message = bytes(message, "utf-8")
            elif mode == SigningMode.BLS_MESSAGE_AUGMENTATION_HEX_INPUT:
                hex_message = bytes.fromhex(message)
            else:
                hex_message = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, message)).get_tree_hash()
            return synthetic_pk, AugSchemeMPL.sign(synthetic_secret_key, hex_message)
        else:
            raise ValueError("Invalid NFT puzzle.")

    async def get_coins_to_offer(
        self,
        nft_id: bytes32,
        *args: Any,
        **kwargs: Any,
    ) -> Set[Coin]:
        nft_coin: Optional[NFTCoinInfo] = await self.get_nft(nft_id)
        if nft_coin is None:
            raise ValueError("An asset ID was specified that this wallet doesn't track")
        return {nft_coin.coin}

    async def match_puzzle_info(self, puzzle_driver: PuzzleInfo) -> bool:
        return (
            AssetType(puzzle_driver.type()) == AssetType.SINGLETON
            and puzzle_driver.also() is not None
            and AssetType(puzzle_driver.also().type()) == AssetType.METADATA  # type: ignore
            and puzzle_driver.also().also() is None  # type: ignore
            and await self.get_nft(puzzle_driver["launcher_id"]) is not None
        )

    @classmethod
    async def create_from_puzzle_info(
        cls: Any,
        wallet_state_manager: Any,
        wallet: Wallet,
        puzzle_driver: PuzzleInfo,
        name: Optional[str] = None,
    ) -> Any:
        # Off the bat we don't support multiple profile but when we do this will have to change
        for wallet in wallet_state_manager.wallets.values():
            if wallet.type() == WalletType.NFT.value:
                return wallet

        # TODO: These are not the arguments to this function yet but they will be
        return await cls.create_new_nft_wallet(
            wallet_state_manager,
            wallet,
            None,
            name,
        )

    async def generate_signed_transaction(
        self,
        amounts: List[uint64],
        puzzle_hashes: List[bytes32],
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        coins: Optional[Set[Coin]] = None,
        memos: Optional[List[List[bytes]]] = None,
        extra_conditions: Tuple[Condition, ...] = tuple(),
        **kwargs: Unpack[GSTOptionalArgs],
    ) -> None:
        nft_coin: Optional[NFTCoinInfo] = kwargs.get("nft_coin", None)
        new_owner: Optional[bytes] = kwargs.get("new_owner", None)
        new_did_inner_hash: Optional[bytes] = kwargs.get("new_did_inner_hash", None)
        trade_prices_list: Optional[Program] = kwargs.get("trade_prices_list", None)
        additional_bundles: List[WalletSpendBundle] = kwargs.get("additional_bundles", [])
        metadata_update: Optional[Tuple[str, str]] = kwargs.get("metadata_update", None)
        if memos is None:
            memos = [[] for _ in range(len(puzzle_hashes))]

        if not (len(memos) == len(puzzle_hashes) == len(amounts)):
            raise ValueError("Memos, puzzle_hashes, and amounts must have the same length")

        payments = []
        for amount, puzhash, memo_list in zip(amounts, puzzle_hashes, memos):
            memos_with_hint: List[bytes] = [puzhash]
            memos_with_hint.extend(memo_list)
            payments.append(Payment(puzhash, amount, memos_with_hint))

        payment_sum = sum(p.amount for p in payments)
        unsigned_spend_bundle = await self.generate_unsigned_spendbundle(
            payments,
            action_scope,
            fee,
            coins=coins,
            nft_coin=nft_coin,
            new_owner=new_owner,
            new_did_inner_hash=new_did_inner_hash,
            trade_prices_list=trade_prices_list,
            metadata_update=metadata_update,
            extra_conditions=extra_conditions,
        )
        spend_bundle = WalletSpendBundle.aggregate([unsigned_spend_bundle] + additional_bundles)

        async with action_scope.use() as interface:
            other_tx_removals: Set[Coin] = {
                removal for tx in interface.side_effects.transactions for removal in tx.removals
            }
            other_tx_additions: Set[Coin] = {
                addition for tx in interface.side_effects.transactions for addition in tx.additions
            }
            tx = TransactionRecord(
                confirmed_at_height=uint32(0),
                created_at_time=uint64(int(time.time())),
                to_puzzle_hash=puzzle_hashes[0],
                amount=uint64(payment_sum),
                fee_amount=fee,
                confirmed=False,
                sent=uint32(0),
                spend_bundle=spend_bundle,
                additions=list(set(spend_bundle.additions()) - other_tx_additions),
                removals=list(set(spend_bundle.removals()) - other_tx_removals),
                wallet_id=self.id(),
                sent_to=[],
                trade_id=None,
                type=uint32(TransactionType.OUTGOING_TX.value),
                name=spend_bundle.name(),
                memos=list(compute_memos(spend_bundle).items()),
                valid_times=parse_timelock_info(extra_conditions),
            )

            interface.side_effects.transactions.append(tx)

    async def generate_unsigned_spendbundle(
        self,
        payments: List[Payment],
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        coins: Optional[Set[Coin]] = None,
        new_owner: Optional[bytes] = None,
        new_did_inner_hash: Optional[bytes] = None,
        trade_prices_list: Optional[Program] = None,
        metadata_update: Optional[Tuple[str, str]] = None,
        nft_coin: Optional[NFTCoinInfo] = None,
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> WalletSpendBundle:
        if nft_coin is None:
            if coins is None or not len(coins) == 1:
                # Make sure the user is specifying which specific NFT coin to use
                raise ValueError("NFT spends require a single selected coin")
            elif len(payments) > 1:
                raise ValueError("NFTs can only be sent to one party")
            nft_coin = await self.nft_store.get_nft_by_coin_id(coins.pop().name())
            assert nft_coin

        coin_name = nft_coin.coin.name()
        if fee > 0:
            await self.standard_wallet.create_tandem_xch_tx(
                fee,
                action_scope,
                extra_conditions=(AssertCoinAnnouncement(asserted_id=coin_name, asserted_msg=coin_name),),
            )

        unft = UncurriedNFT.uncurry(*nft_coin.full_puzzle.uncurry())
        assert unft is not None
        if unft.supports_did:
            if new_owner is None:
                # If no new owner was specified and we're sending this to ourselves, let's not reset the DID
                derivation_record: Optional[DerivationRecord] = (
                    await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(
                        payments[0].puzzle_hash
                    )
                )
                if derivation_record is not None:
                    new_owner = unft.owner_did
            extra_conditions = (
                *extra_conditions,
                UnknownCondition(
                    opcode=Program.to(-10),
                    args=[
                        Program.to(new_owner),
                        Program.to(trade_prices_list),
                        Program.to(new_did_inner_hash),
                    ],
                ),
            )
        if metadata_update is not None:
            extra_conditions = (
                *extra_conditions,
                UnknownCondition(
                    opcode=Program.to(-24),
                    args=[
                        NFT_METADATA_UPDATER,
                        Program.to(metadata_update),
                    ],
                ),
            )

        innersol: Program = self.standard_wallet.make_solution(
            primaries=payments,
            conditions=(*extra_conditions, CreateCoinAnnouncement(coin_name)) if fee > 0 else extra_conditions,
        )

        if unft.supports_did:
            innersol = Program.to([innersol])

        nft_layer_solution = Program.to([innersol])
        assert isinstance(nft_coin.lineage_proof, LineageProof)
        singleton_solution = Program.to([nft_coin.lineage_proof.to_program(), nft_coin.coin.amount, nft_layer_solution])
        coin_spend = make_spend(nft_coin.coin, nft_coin.full_puzzle, singleton_solution)

        nft_spend_bundle = WalletSpendBundle([coin_spend], G2Element())

        return nft_spend_bundle

    @staticmethod
    def royalty_calculation(
        royalty_assets_dict: Dict[Any, Tuple[Any, uint16]],
        fungible_asset_dict: Dict[Any, uint64],
    ) -> Dict[Any, List[Dict[str, Any]]]:
        summary_dict: Dict[Any, List[Dict[str, Any]]] = {}
        for id, royalty_info in royalty_assets_dict.items():
            address, percentage = royalty_info
            summary_dict[id] = []
            for name, amount in fungible_asset_dict.items():
                summary_dict[id].append(
                    {
                        "asset": name,
                        "address": address,
                        "amount": math.floor(math.floor(abs(amount) / len(royalty_assets_dict)) * (percentage / 10000)),
                    }
                )

        return summary_dict

    @staticmethod
    async def make_nft1_offer(
        wallet_state_manager: Any,
        offer_dict: Dict[Optional[bytes32], int],
        driver_dict: Dict[bytes32, PuzzleInfo],
        action_scope: WalletActionScope,
        fee: uint64,
        extra_conditions: Tuple[Condition, ...],
    ) -> Offer:
        # First, let's take note of all the royalty enabled NFTs
        royalty_nft_asset_dict: Dict[bytes32, int] = {}
        for asset, amount in offer_dict.items():
            if asset is not None and driver_dict[asset].check_type(  # check if asset is an Royalty Enabled NFT
                [
                    AssetType.SINGLETON.value,
                    AssetType.METADATA.value,
                    AssetType.OWNERSHIP.value,
                ]
            ):
                driver_dict[asset].info["also"]["also"]["owner"] = "()"
                royalty_nft_asset_dict[asset] = amount

        # Then, all of the things that trigger royalties
        fungible_asset_dict: Dict[Optional[bytes32], int] = {}
        for asset, amount in offer_dict.items():
            if asset is None or driver_dict[asset].type() != AssetType.SINGLETON.value:
                fungible_asset_dict[asset] = amount

        # Let's gather some information about the royalties
        offer_side_royalty_split: int = 0
        request_side_royalty_split: int = 0
        for asset, amount in royalty_nft_asset_dict.items():  # requested non fungible items
            if amount > 0:
                request_side_royalty_split += 1
            elif amount < 0:
                offer_side_royalty_split += 1

        trade_prices: List[Tuple[uint64, bytes32]] = []
        for asset, amount in fungible_asset_dict.items():  # requested fungible items
            if amount > 0 and offer_side_royalty_split > 0:
                settlement_ph: bytes32 = (
                    OFFER_MOD_HASH if asset is None else construct_puzzle(driver_dict[asset], OFFER_MOD).get_tree_hash()
                )
                trade_prices.append((uint64(math.floor(amount / offer_side_royalty_split)), settlement_ph))

        required_royalty_info: List[Tuple[bytes32, bytes32, uint16]] = []  # [(launcher_id, address, percentage)]
        offered_royalty_percentages: Dict[bytes32, uint16] = {}
        for asset, amount in royalty_nft_asset_dict.items():  # royalty enabled NFTs
            transfer_info = driver_dict[asset].also().also()  # type: ignore
            assert isinstance(transfer_info, PuzzleInfo)
            royalty_percentage_raw = transfer_info["transfer_program"]["royalty_percentage"]
            assert royalty_percentage_raw is not None
            # clvm encodes large ints as bytes
            if isinstance(royalty_percentage_raw, bytes):
                royalty_percentage = int_from_bytes(royalty_percentage_raw)
            else:
                royalty_percentage = int(royalty_percentage_raw)
            if amount > 0:
                required_royalty_info.append(
                    (
                        asset,
                        bytes32(transfer_info["transfer_program"]["royalty_address"]),
                        uint16(royalty_percentage),
                    )
                )
            else:
                offered_royalty_percentages[asset] = uint16(royalty_percentage)

        royalty_payments: Dict[Optional[bytes32], List[Tuple[bytes32, Payment]]] = {}
        for asset, amount in fungible_asset_dict.items():  # offered fungible items
            if amount < 0 and request_side_royalty_split > 0:
                payment_list: List[Tuple[bytes32, Payment]] = []
                for launcher_id, address, percentage in required_royalty_info:
                    extra_royalty_amount = uint64(
                        math.floor(math.floor(abs(amount) / request_side_royalty_split) * (percentage / 10000))
                    )
                    if extra_royalty_amount == abs(amount):
                        raise ValueError("Amount offered and amount paid in royalties are equal")
                    payment_list.append((launcher_id, Payment(address, extra_royalty_amount, [address])))
                royalty_payments[asset] = payment_list

        # Generate the requested_payments to be notarized
        p2_ph = await wallet_state_manager.main_wallet.get_puzzle_hash(
            new=not action_scope.config.tx_config.reuse_puzhash
        )
        requested_payments: Dict[Optional[bytes32], List[Payment]] = {}
        for asset, amount in offer_dict.items():
            if amount > 0:
                requested_payments[asset] = [Payment(p2_ph, uint64(amount), [p2_ph] if asset is not None else [])]

        # Find all the coins we're offering
        offered_coins_by_asset: Dict[Optional[bytes32], Set[Coin]] = {}
        all_offered_coins: Set[Coin] = set()
        for asset, amount in offer_dict.items():
            if amount < 0:
                if asset is None:
                    wallet = wallet_state_manager.main_wallet
                else:
                    wallet = await wallet_state_manager.get_wallet_for_asset_id(asset.hex())
                if asset in royalty_payments:
                    royalty_amount: int = sum(p.amount for _, p in royalty_payments[asset])
                else:
                    royalty_amount = 0
                if asset is None:
                    coin_amount_needed: int = abs(amount) + royalty_amount + fee
                else:
                    coin_amount_needed = abs(amount) + royalty_amount
                offered_coins: Set[Coin] = await wallet.get_coins_to_offer(asset, coin_amount_needed, action_scope)
                if len(offered_coins) == 0:
                    raise ValueError(f"Did not have asset ID {asset.hex() if asset is not None else 'XCH'} to offer")
                offered_coins_by_asset[asset] = offered_coins
                all_offered_coins.update(offered_coins)

        # Notarize the payments and get the announcements for the bundle
        notarized_payments: Dict[Optional[bytes32], List[NotarizedPayment]] = Offer.notarize_payments(
            requested_payments, list(all_offered_coins)
        )
        announcements_to_assert: List[AssertPuzzleAnnouncement] = Offer.calculate_announcements(
            notarized_payments, driver_dict
        )
        for asset, payments in royalty_payments.items():
            if asset is None:  # xch offer
                offer_puzzle = OFFER_MOD
                royalty_ph = OFFER_MOD_HASH
            else:
                offer_puzzle = construct_puzzle(driver_dict[asset], OFFER_MOD)
                royalty_ph = offer_puzzle.get_tree_hash()
            announcements_to_assert.extend(
                [
                    AssertPuzzleAnnouncement(
                        asserted_ph=royalty_ph,
                        asserted_msg=Program.to((launcher_id, [p.as_condition_args()])).get_tree_hash(),
                    )
                    for launcher_id, p in payments
                    if p.amount > 0
                ]
            )

        # Create all of the transactions
        all_transactions: List[TransactionRecord] = []
        additional_bundles: List[WalletSpendBundle] = []
        # standard pays the fee if possible
        fee_left_to_pay: uint64 = uint64(0) if None in offer_dict and offer_dict[None] < 0 else fee

        for asset, amount in offer_dict.items():
            if amount < 0:
                if asset is None:
                    wallet = wallet_state_manager.main_wallet
                else:
                    wallet = await wallet_state_manager.get_wallet_for_asset_id(asset.hex())

                # First, sending all the coins to the OFFER_MOD
                async with wallet_state_manager.new_action_scope(
                    action_scope.config.tx_config, push=False
                ) as inner_action_scope:
                    if wallet.type() == WalletType.STANDARD_WALLET:
                        payments = royalty_payments[asset] if asset in royalty_payments else []
                        payment_sum = sum(p.amount for _, p in payments)
                        await wallet.generate_signed_transaction(
                            abs(amount),
                            OFFER_MOD_HASH,
                            inner_action_scope,
                            primaries=[Payment(OFFER_MOD_HASH, uint64(payment_sum))] if payment_sum > 0 else [],
                            fee=fee,
                            coins=offered_coins_by_asset[asset],
                            extra_conditions=(*extra_conditions, *announcements_to_assert),
                        )
                    elif asset not in fungible_asset_dict:
                        assert asset is not None
                        await wallet.generate_signed_transaction(
                            [abs(amount)],
                            [OFFER_MOD_HASH],
                            inner_action_scope,
                            fee=fee_left_to_pay,
                            coins=offered_coins_by_asset[asset],
                            trade_prices_list=[
                                list(price)
                                for price in trade_prices
                                if math.floor(price[0] * (offered_royalty_percentages[asset] / 10000)) != 0
                            ],
                            extra_conditions=(*extra_conditions, *announcements_to_assert),
                        )
                    else:
                        payments = royalty_payments[asset] if asset in royalty_payments else []
                        await wallet.generate_signed_transaction(
                            [abs(amount), sum(p.amount for _, p in payments)],
                            [OFFER_MOD_HASH, OFFER_MOD_HASH],
                            inner_action_scope,
                            fee=fee_left_to_pay,
                            coins=offered_coins_by_asset[asset],
                            extra_conditions=(*extra_conditions, *announcements_to_assert),
                        )
                all_transactions.extend(inner_action_scope.side_effects.transactions)
                fee_left_to_pay = uint64(0)
                extra_conditions = tuple()

                # Then, adding in the spends for the royalty offer mod
                if asset in fungible_asset_dict:
                    # Create a coin_spend for the royalty payout from OFFER MOD

                    # Skip it if we're paying 0 royalties
                    payments = royalty_payments[asset] if asset in royalty_payments else []
                    if sum(p.amount for _, p in payments) == 0:
                        continue

                    # We cannot create coins with the same puzzle hash and amount
                    # So if there's multiple NFTs with the same royalty puzhash/percentage, we must create multiple
                    # generations of offer coins
                    royalty_coin: Optional[Coin] = None
                    parent_spend: Optional[CoinSpend] = None
                    while True:
                        duplicate_payments: List[Tuple[bytes32, Payment]] = []
                        deduped_payment_list: List[Tuple[bytes32, Payment]] = []
                        for launcher_id, payment in payments:
                            if payment in [p for _, p in deduped_payment_list]:
                                duplicate_payments.append((launcher_id, payment))
                            else:
                                deduped_payment_list.append((launcher_id, payment))

                        # ((nft_launcher_id . ((ROYALTY_ADDRESS, royalty_amount, memos) ...)))
                        inner_royalty_sol = Program.to(
                            [
                                (launcher_id, [payment.as_condition_args()])
                                for launcher_id, payment in deduped_payment_list
                            ]
                        )
                        if duplicate_payments != []:
                            inner_royalty_sol = Program.to(
                                (
                                    None,
                                    [
                                        Payment(
                                            OFFER_MOD_HASH,
                                            uint64(sum(p.amount for _, p in duplicate_payments)),
                                        ).as_condition_args()
                                    ],
                                )
                            ).cons(inner_royalty_sol)

                        if asset is None:  # xch offer
                            offer_puzzle = OFFER_MOD
                            royalty_ph = OFFER_MOD_HASH
                        else:
                            offer_puzzle = construct_puzzle(driver_dict[asset], OFFER_MOD)
                            royalty_ph = offer_puzzle.get_tree_hash()
                        if royalty_coin is None:
                            for tx in inner_action_scope.side_effects.transactions:
                                if tx.spend_bundle is not None:
                                    for coin in tx.spend_bundle.additions():
                                        royalty_payment_amount: int = sum(p.amount for _, p in payments)
                                        if coin.amount == royalty_payment_amount and coin.puzzle_hash == royalty_ph:
                                            royalty_coin = coin
                                            parent_spend = next(
                                                cs
                                                for cs in tx.spend_bundle.coin_spends
                                                if cs.coin.name() == royalty_coin.parent_coin_info
                                            )
                                            break
                                    else:
                                        continue
                                    break
                        assert royalty_coin is not None
                        assert parent_spend is not None
                        if asset is None:  # If XCH
                            royalty_sol = inner_royalty_sol
                        else:
                            # call our drivers to solve the puzzle
                            royalty_coin_hex = (
                                "0x"
                                + royalty_coin.parent_coin_info.hex()
                                + royalty_coin.puzzle_hash.hex()
                                + uint64(royalty_coin.amount).stream_to_bytes().hex()
                            )
                            parent_spend_hex: str = "0x" + bytes(parent_spend).hex()
                            solver = Solver(
                                {
                                    "coin": royalty_coin_hex,
                                    "parent_spend": parent_spend_hex,
                                    "siblings": "()",
                                    "sibling_spends": "()",
                                    "sibling_puzzles": "()",
                                    "sibling_solutions": "()",
                                }
                            )
                            royalty_sol = solve_puzzle(driver_dict[asset], solver, OFFER_MOD, inner_royalty_sol)

                        new_coin_spend = make_spend(royalty_coin, offer_puzzle, royalty_sol)
                        additional_bundles.append(WalletSpendBundle([new_coin_spend], G2Element()))

                        if duplicate_payments != []:
                            payments = duplicate_payments
                            royalty_coin = next(
                                c for c in compute_additions(new_coin_spend) if c.puzzle_hash == royalty_ph
                            )
                            parent_spend = new_coin_spend
                            continue
                        else:
                            break

        # Finally, assemble the tx records properly
        txs_bundle = WalletSpendBundle.aggregate(
            [tx.spend_bundle for tx in all_transactions if tx.spend_bundle is not None]
        )
        aggregate_bundle = WalletSpendBundle.aggregate([txs_bundle, *additional_bundles])
        offer = Offer(notarized_payments, aggregate_bundle, driver_dict)
        async with action_scope.use() as interface:
            interface.side_effects.transactions.extend(all_transactions)

        return offer

    async def set_bulk_nft_did(
        self,
        nft_list: List[NFTCoinInfo],
        did_id: bytes,
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        announcement_ids: List[bytes32] = [],
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> None:
        self.log.debug("Setting NFT DID with parameters: nft=%s did=%s", nft_list, did_id)
        nft_ids = []
        first = True
        for nft_coin_info in nft_list:
            nft_ids.append(nft_coin_info.nft_id)
        if did_id != b"" and len(announcement_ids) > 0:
            await self.get_did_approval_info(announcement_ids, action_scope, bytes32(did_id))

        for _, wallet in self.wallet_state_manager.wallets.items():
            if wallet.type() == WalletType.DECENTRALIZED_ID:
                if bytes32.fromhex(wallet.get_my_DID()) == did_id:
                    did_inner_hash = wallet.did_info.current_inner.get_tree_hash()
                    break
        else:
            raise ValueError(f"No DID wallet with id: {did_id.hex()}")

        for nft_coin_info in nft_list:
            unft = UncurriedNFT.uncurry(*nft_coin_info.full_puzzle.uncurry())
            assert unft is not None
            puzzle_hashes_to_sign = [unft.p2_puzzle.get_tree_hash()]
            if not first:
                fee = uint64(0)
                extra_conditions = tuple()
            await self.generate_signed_transaction(
                [uint64(nft_coin_info.coin.amount)],
                puzzle_hashes_to_sign,
                action_scope,
                fee,
                {nft_coin_info.coin},
                new_owner=did_id,
                new_did_inner_hash=did_inner_hash,
                extra_conditions=extra_conditions,
            )
            first = False

    async def bulk_transfer_nft(
        self,
        nft_list: List[NFTCoinInfo],
        puzzle_hash: bytes32,
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> None:
        self.log.debug("Transfer NFTs %s to %s", nft_list, puzzle_hash.hex())
        first = True

        for nft_coin_info in nft_list:
            if not first:
                fee = uint64(0)
                extra_conditions = tuple()
            await self.generate_signed_transaction(
                [uint64(nft_coin_info.coin.amount)],
                [puzzle_hash],
                action_scope,
                coins={nft_coin_info.coin},
                fee=fee,
                new_owner=b"",
                new_did_inner_hash=b"",
                extra_conditions=extra_conditions,
            )
            first = False

    async def set_nft_did(
        self,
        nft_coin_info: NFTCoinInfo,
        did_id: bytes,
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> None:
        self.log.debug("Setting NFT DID with parameters: nft=%s did=%s", nft_coin_info, did_id)
        unft = UncurriedNFT.uncurry(*nft_coin_info.full_puzzle.uncurry())
        assert unft is not None
        nft_id = unft.singleton_launcher_id
        puzzle_hashes_to_sign = [unft.p2_puzzle.get_tree_hash()]
        did_inner_hash = b""
        if did_id != b"":
            did_inner_hash = await self.get_did_approval_info([nft_id], action_scope, bytes32(did_id))

        await self.generate_signed_transaction(
            [uint64(nft_coin_info.coin.amount)],
            puzzle_hashes_to_sign,
            action_scope,
            fee,
            {nft_coin_info.coin},
            new_owner=did_id,
            new_did_inner_hash=did_inner_hash,
            extra_conditions=extra_conditions,
        )

        await self.update_coin_status(nft_coin_info.coin.name(), True)
        self.wallet_state_manager.state_changed("nft_coin_did_set", self.wallet_info.id)

    async def mint_from_did(
        self,
        metadata_list: List[Dict[str, Any]],
        action_scope: WalletActionScope,
        target_list: Optional[List[bytes32]] = [],
        mint_number_start: Optional[int] = 1,
        mint_total: Optional[int] = None,
        xch_coins: Optional[Set[Coin]] = None,
        xch_change_ph: Optional[bytes32] = None,
        new_innerpuzhash: Optional[bytes32] = None,
        new_p2_puzhash: Optional[bytes32] = None,
        did_coin: Optional[Coin] = None,
        did_lineage_parent: Optional[bytes32] = None,
        fee: Optional[uint64] = uint64(0),
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> None:
        """
        Minting NFTs from the DID linked wallet, also used for bulk minting NFTs.
        - The DID is spent along with an intermediate launcher puzzle which
          generates a set of ephemeral coins with unique IDs by currying in the
          mint_number and mint_total for each NFT being minted. These
          intermediate coins then create the launcher coins for the list of NFTs
        - The launcher coins are then spent along with the created eve spend
          and an xch spend that funds the transactions and pays fees.
        - There is also an option to pass in a list of target puzzlehashes. If
          provided this method will create an additional transaction transfering
          the minted NFTs to the row-matched target.
        :param metadata_list: A list of dicts containing the metadata for each NFT to be minted
        :param target_list: [Optional] a list of targets for transfering minted NFTs (aka airdrop)
        :param mint_number_start: [Optional] The starting point for mint number used in intermediate launcher
        puzzle. Default: 1
        :param mint_total: [Optional] The total number of NFTs being minted
        :param xch_coins: [Optional] For use with bulk minting to provide the coin used for funding the minting spend.
        This coin can be one that will be created in the future
        :param xch_change_ph: [Optional] For use with bulk minting, so we can specify the puzzle hash that the change
        from the funding transaction goes to.
        :param new_innerpuzhash: [Optional] The new inner puzzle hash for the DID once it is spent. For bulk minting we
        generally don't provide this as the default behaviour is to re-use the existing inner puzzle hash
        :param new_p2_puzhash: [Optional] The new p2 puzzle hash for the DID once it is spent. For bulk minting we
        generally don't provide this as the default behaviour is to re-use the existing inner puzzle hash
        :param did_coin: [Optional] The did coin to use for minting. Required for bulk minting when the DID coin will
        be created in the future
        :param did_lineage_parent: [Optional]  The  parent coin to use for the lineage proof in the DID spend. Needed
        for bulk minting when the coin will be created in the future
        :param fee: A fee amount, taken out of the xch spend.
        """
        # get DID Wallet
        for wallet in self.wallet_state_manager.wallets.values():
            if wallet.type() == WalletType.DECENTRALIZED_ID:
                if self.get_did() == bytes32.from_hexstr(wallet.get_my_DID()):
                    did_wallet = wallet
                    break
        else:
            raise ValueError("There is no DID associated with this NFT wallet")

        assert did_wallet.did_info.current_inner is not None
        assert did_wallet.did_info.origin_coin is not None

        # Ensure we have an mint_total value
        if mint_total is None:
            mint_total = len(metadata_list)
        assert isinstance(mint_number_start, int)
        assert len(metadata_list) <= mint_total + 1 - mint_number_start

        # Ensure we have a did coin and its next inner puzzle hash
        if did_coin is None:
            did_coin = await did_wallet.get_coin()
        innerpuz: Program = did_wallet.did_info.current_inner
        if new_innerpuzhash is None:
            new_innerpuzhash = innerpuz.get_tree_hash()
            uncurried_did = did_wallet_puzzles.uncurry_innerpuz(innerpuz)
            assert uncurried_did is not None
            p2_puzzle = uncurried_did[0]
            new_p2_puzhash = p2_puzzle.get_tree_hash()
        assert new_p2_puzhash is not None
        # make the primaries for the DID spend
        primaries = [Payment(new_innerpuzhash, uint64(did_coin.amount), [bytes(new_p2_puzhash)])]

        # Ensure we have an xch coin of high enough amount
        assert isinstance(fee, uint64)
        total_amount = len(metadata_list) + fee
        if xch_coins is None:
            xch_coins = await self.standard_wallet.select_coins(uint64(total_amount), action_scope)
        assert len(xch_coins) > 0

        # set the chunk size for the spend bundle we're going to create
        chunk_size = len(metadata_list)

        # Because bulk minting may not mint all the NFTs in one bundle, we
        # calculate the edition numbers that will be used in the intermediate
        # puzzle based on the starting edition number given, and the size of the
        # chunk going into this spend bundle
        mint_number_end = mint_number_start + chunk_size

        # Empty set to load with the announcements we will assert from DID to
        # match the announcements from the intermediate launcher puzzle
        did_announcements: Set[Any] = set()
        puzzle_assertions: Set[Any] = set()
        amount = uint64(1)
        intermediate_coin_spends = []
        launcher_spends = []
        launcher_ids = []
        p2_inner_puzzle = await self.standard_wallet.get_new_puzzle()
        p2_inner_ph = p2_inner_puzzle.get_tree_hash()

        # Loop to create each intermediate coin, launcher, eve and (optional) transfer spends
        for mint_number in range(mint_number_start, mint_number_end):
            # Create  the puzzle, solution and coin spend for the intermediate launcher
            intermediate_launcher_puz = did_wallet_puzzles.INTERMEDIATE_LAUNCHER_MOD.curry(
                chia.wallet.singleton.SINGLETON_LAUNCHER_PUZZLE_HASH, mint_number, mint_total
            )
            intermediate_launcher_ph = intermediate_launcher_puz.get_tree_hash()
            primaries.append(Payment(intermediate_launcher_ph, uint64(0), [intermediate_launcher_ph]))
            intermediate_launcher_sol = Program.to([])
            intermediate_launcher_coin = Coin(did_coin.name(), intermediate_launcher_ph, uint64(0))
            intermediate_launcher_coin_spend = make_spend(
                intermediate_launcher_coin, intermediate_launcher_puz, intermediate_launcher_sol
            )
            intermediate_coin_spends.append(intermediate_launcher_coin_spend)

            # create an ASSERT_COIN_ANNOUNCEMENT for the DID spend. The
            # intermediate launcher coin issues a CREATE_COIN_ANNOUNCEMENT of
            # the mint_number and mint_total for the launcher coin it creates
            intermediate_announcement_message = std_hash(int_to_bytes(mint_number) + int_to_bytes(mint_total))
            did_announcements.add(std_hash(intermediate_launcher_coin.name() + intermediate_announcement_message))

            # Create the launcher coin, and add its id to a list to be asserted in the DID spend
            launcher_coin = Coin(
                intermediate_launcher_coin.name(), chia.wallet.singleton.SINGLETON_LAUNCHER_PUZZLE_HASH, amount
            )
            launcher_ids.append(launcher_coin.name())

            # Grab the metadata from metadata_list. The index for metadata_list
            # needs to be offset by mint_number_start
            metadata = metadata_list[mint_number - mint_number_start]

            # Create the inner and full puzzles for the eve spend
            inner_puzzle = create_ownership_layer_puzzle(
                launcher_coin.name(),
                b"",
                p2_inner_puzzle,
                metadata["royalty_pc"],
                royalty_puzzle_hash=metadata["royalty_ph"],
            )
            eve_fullpuz = nft_puzzles.create_full_puzzle(
                launcher_coin.name(), metadata["program"], NFT_METADATA_UPDATER.get_tree_hash(), inner_puzzle
            )

            # Annnouncements for eve spend. These are asserted by the DID spend
            announcement_message = Program.to([eve_fullpuz.get_tree_hash(), amount, []]).get_tree_hash()
            did_announcements.add(std_hash(launcher_coin.name() + announcement_message))

            genesis_launcher_solution = Program.to([eve_fullpuz.get_tree_hash(), amount, []])

            launcher_cs = make_spend(
                launcher_coin, chia.wallet.singleton.SINGLETON_LAUNCHER_PUZZLE, genesis_launcher_solution
            )
            launcher_spends.append(launcher_cs)

            eve_coin = Coin(launcher_coin.name(), eve_fullpuz.get_tree_hash(), uint64(amount))

            # To make the eve transaction we need to construct the NFTCoinInfo
            # for the NFT (which doesn't exist yet)
            nft_coin = NFTCoinInfo(
                nft_id=launcher_coin.name(),
                coin=eve_coin,
                lineage_proof=LineageProof(
                    parent_name=launcher_coin.parent_coin_info, amount=uint64(launcher_coin.amount)
                ),
                full_puzzle=eve_fullpuz,
                mint_height=uint32(0),
            )

            # Create the eve transaction setting the DID owner, and applying
            # the announcements from announcement_set to match the launcher
            # coin annnouncement
            if target_list:
                target_ph = target_list[mint_number - mint_number_start]
            else:
                target_ph = p2_inner_ph
            async with self.wallet_state_manager.new_action_scope(
                action_scope.config.tx_config, push=False
            ) as inner_action_scope:
                await self.generate_signed_transaction(
                    [uint64(eve_coin.amount)],
                    [target_ph],
                    inner_action_scope,
                    nft_coin=nft_coin,
                    new_owner=b"",
                    new_did_inner_hash=b"",
                    additional_bundles=[],
                    memos=[[target_ph]],
                )

            async with action_scope.use() as interface:
                interface.side_effects.transactions.extend(inner_action_scope.side_effects.transactions)

            eve_sb = next(
                tx.spend_bundle for tx in inner_action_scope.side_effects.transactions if tx.spend_bundle is not None
            )
            # Extract Puzzle Announcement from eve spend
            eve_sol = eve_sb.coin_spends[0].solution.to_program()
            conds = eve_fullpuz.run(eve_sol)
            eve_puzzle_announcement = [x for x in conds.as_python() if int_from_bytes(x[0]) == 62][0][1]
            assertion = std_hash(eve_fullpuz.get_tree_hash() + eve_puzzle_announcement)
            puzzle_assertions.add(assertion)

        # We've now created all the intermediate, launcher, eve and transfer spends.
        # Create the xch spend to fund the minting.
        spend_value = sum(coin.amount for coin in xch_coins)
        change: uint64 = uint64(spend_value - total_amount)
        if xch_change_ph is None:
            xch_change_ph = await self.standard_wallet.get_new_puzzlehash()
        xch_payment = Payment(xch_change_ph, change, [xch_change_ph])

        xch_coins_iter = iter(xch_coins)
        xch_coin = next(xch_coins_iter)

        message_list: List[bytes32] = [c.name() for c in xch_coins]
        message_list.append(Coin(xch_coin.name(), xch_payment.puzzle_hash, xch_payment.amount).name())
        message: bytes32 = std_hash(b"".join(message_list))

        xch_extra_conditions: Tuple[Condition, ...] = (
            AssertCoinAnnouncement(asserted_id=did_coin.name(), asserted_msg=message),
        )
        if len(xch_coins) > 1:
            xch_extra_conditions += (CreateCoinAnnouncement(message),)

        solution: Program = self.standard_wallet.make_solution(
            primaries=[xch_payment],
            fee=fee,
            conditions=xch_extra_conditions,
        )
        primary_announcement_hash = AssertCoinAnnouncement(asserted_id=xch_coin.name(), asserted_msg=message).msg_calc
        # connect this coin assertion to the DID announcement
        did_coin_announcement = CreateCoinAnnouncement(message)
        puzzle = await self.standard_wallet.puzzle_for_puzzle_hash(xch_coin.puzzle_hash)
        xch_spends = [make_spend(xch_coin, puzzle, solution)]

        for xch_coin in xch_coins_iter:
            puzzle = await self.standard_wallet.puzzle_for_puzzle_hash(xch_coin.puzzle_hash)
            solution = self.standard_wallet.make_solution(
                primaries=[], conditions=(AssertCoinAnnouncement(primary_announcement_hash),)
            )
            xch_spends.append(make_spend(xch_coin, puzzle, solution))
        xch_spend = WalletSpendBundle(xch_spends, G2Element())

        # Create the DID spend using the announcements collected when making the intermediate launcher coins
        did_p2_solution = self.standard_wallet.make_solution(
            primaries=primaries,
            conditions=(
                *extra_conditions,
                did_coin_announcement,
                *(AssertCoinAnnouncement(ann) for ann in did_announcements),
                *(AssertPuzzleAnnouncement(ann) for ann in puzzle_assertions),
            ),
        )
        did_inner_sol: Program = Program.to([1, did_p2_solution])
        did_full_puzzle: Program = chia.wallet.singleton.create_singleton_puzzle(
            innerpuz,
            did_wallet.did_info.origin_coin.name(),
        )
        # The DID lineage parent won't not exist if we're bulk minting from a future DID coin
        if did_lineage_parent:
            did_parent_info: Optional[LineageProof] = LineageProof(
                parent_name=did_lineage_parent,
                inner_puzzle_hash=innerpuz.get_tree_hash(),
                amount=uint64(did_coin.amount),
            )
        else:
            did_parent_info = did_wallet.get_parent_for_coin(did_coin)
        assert did_parent_info is not None

        did_full_sol = Program.to(
            [
                [
                    did_parent_info.parent_name,
                    did_parent_info.inner_puzzle_hash,
                    did_parent_info.amount,
                ],
                did_coin.amount,
                did_inner_sol,
            ]
        )
        did_spend = make_spend(did_coin, did_full_puzzle, did_full_sol)

        # Collect up all the coin spends and sign them
        list_of_coinspends = [did_spend] + intermediate_coin_spends + launcher_spends + xch_spend.coin_spends
        unsigned_spend_bundle = WalletSpendBundle(list_of_coinspends, G2Element())

        # Aggregate everything into a single spend bundle
        async with action_scope.use() as interface:
            # This should not be looked to for best practice. I think many of the spends generated above could call
            # wallet methods that generate transactions and prevent most of the need for this. Refactoring this function
            # is out of scope so for now we're using this hack.
            if interface.side_effects.transactions[0].spend_bundle is None:
                new_spend = unsigned_spend_bundle
            else:
                new_spend = WalletSpendBundle.aggregate(
                    [interface.side_effects.transactions[0].spend_bundle, unsigned_spend_bundle]
                )
            interface.side_effects.transactions[0] = dataclasses.replace(
                interface.side_effects.transactions[0], spend_bundle=new_spend, name=new_spend.name()
            )

    async def mint_from_xch(
        self,
        metadata_list: List[Dict[str, Any]],
        action_scope: WalletActionScope,
        target_list: Optional[List[bytes32]] = [],
        mint_number_start: Optional[int] = 1,
        mint_total: Optional[int] = None,
        xch_coins: Optional[Set[Coin]] = None,
        xch_change_ph: Optional[bytes32] = None,
        fee: Optional[uint64] = uint64(0),
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> None:
        """
        Minting NFTs from a single XCH spend using intermediate launcher puzzle
        :param metadata_list: A list of dicts containing the metadata for each NFT to be minted
        :param target_list: [Optional] a list of targets for transfering minted NFTs (aka airdrop)
        :param mint_number_start: [Optional] The starting point for mint number used in intermediate launcher
        puzzle. Default: 1
        :param mint_total: [Optional] The total number of NFTs being minted
        :param xch_coins: [Optional] For use with bulk minting to provide the coin used for funding the minting spend.
        This coin can be one that will be created in the future
        :param xch_change_ph: [Optional] For use with bulk minting, so we can specify the puzzle hash that the change
        from the funding transaction goes to.
        :param fee: A fee amount, taken out of the xch spend.
        """

        # Ensure we have an mint_total value
        if mint_total is None:
            mint_total = len(metadata_list)
        assert isinstance(mint_number_start, int)
        assert len(metadata_list) <= mint_total + 1 - mint_number_start

        # Ensure we have an xch coin of high enough amount
        assert isinstance(fee, uint64)
        total_amount = len(metadata_list) + fee
        if xch_coins is None:
            xch_coins = await self.standard_wallet.select_coins(uint64(total_amount), action_scope)
        assert len(xch_coins) > 0

        funding_coin = xch_coins.copy().pop()

        # set the chunk size for the spend bundle we're going to create
        chunk_size = len(metadata_list)

        # Because bulk minting may not mint all the NFTs in one bundle, we
        # calculate the edition numbers that will be used in the intermediate
        # puzzle based on the starting edition number given, and the size of the
        # chunk going into this spend bundle
        mint_number_end = mint_number_start + chunk_size

        # Empty set to load with the announcements we will assert from XCH to
        # match the announcements from the intermediate launcher puzzle
        coin_announcements: Set[bytes32] = set()
        puzzle_assertions: Set[bytes32] = set()
        primaries = []
        amount = uint64(1)
        intermediate_coin_spends = []
        launcher_spends = []
        launcher_ids = []
        p2_inner_puzzle = await self.standard_wallet.get_new_puzzle()
        p2_inner_ph = p2_inner_puzzle.get_tree_hash()

        # Loop to create each intermediate coin, launcher, eve and (optional) transfer spends
        for mint_number in range(mint_number_start, mint_number_end):
            # Create  the puzzle, solution and coin spend for the intermediate launcher
            intermediate_launcher_puz = nft_puzzles.INTERMEDIATE_LAUNCHER_MOD.curry(
                nft_puzzles.LAUNCHER_PUZZLE_HASH, mint_number, mint_total
            )
            intermediate_launcher_ph = intermediate_launcher_puz.get_tree_hash()
            primaries.append(Payment(intermediate_launcher_ph, uint64(1), [intermediate_launcher_ph]))
            intermediate_launcher_sol = Program.to([])
            intermediate_launcher_coin = Coin(funding_coin.name(), intermediate_launcher_ph, uint64(1))
            intermediate_launcher_coin_spend = make_spend(
                intermediate_launcher_coin, intermediate_launcher_puz, intermediate_launcher_sol
            )
            intermediate_coin_spends.append(intermediate_launcher_coin_spend)

            # create an ASSERT_COIN_ANNOUNCEMENT for the XCH spend. The
            # intermediate launcher coin issues a CREATE_COIN_ANNOUNCEMENT of
            # the mint_number and mint_total for the launcher coin it creates
            intermediate_announcement_message = std_hash(int_to_bytes(mint_number) + int_to_bytes(mint_total))
            coin_announcements.add(std_hash(intermediate_launcher_coin.name() + intermediate_announcement_message))

            # Create the launcher coin, and add its id to a list to be asserted in the XCH spend
            launcher_coin = Coin(intermediate_launcher_coin.name(), nft_puzzles.LAUNCHER_PUZZLE_HASH, amount)
            launcher_ids.append(launcher_coin.name())

            # Grab the metadata from metadata_list. The index for metadata_list
            # needs to be offset by mint_number_start, and since
            # mint_number starts at 1 not 0, we also subtract 1.
            metadata = metadata_list[mint_number - mint_number_start]

            # Create the inner and full puzzles for the eve spend
            inner_puzzle = create_ownership_layer_puzzle(
                launcher_coin.name(),
                b"",
                p2_inner_puzzle,
                metadata["royalty_pc"],
                royalty_puzzle_hash=metadata["royalty_ph"],
            )
            eve_fullpuz = nft_puzzles.create_full_puzzle(
                launcher_coin.name(), metadata["program"], NFT_METADATA_UPDATER.get_tree_hash(), inner_puzzle
            )

            # Annnouncements for eve spend. These are asserted by the xch spend
            announcement_message = Program.to([eve_fullpuz.get_tree_hash(), amount, []]).get_tree_hash()
            coin_announcements.add(std_hash(launcher_coin.name() + announcement_message))

            genesis_launcher_solution = Program.to([eve_fullpuz.get_tree_hash(), amount, []])

            launcher_cs = make_spend(launcher_coin, nft_puzzles.LAUNCHER_PUZZLE, genesis_launcher_solution)
            launcher_spends.append(launcher_cs)

            eve_coin = Coin(launcher_coin.name(), eve_fullpuz.get_tree_hash(), uint64(amount))

            # To make the eve transaction we need to construct the NFTCoinInfo
            # for the NFT (which doesn't exist yet)
            nft_coin = NFTCoinInfo(
                nft_id=launcher_coin.name(),
                coin=eve_coin,
                lineage_proof=LineageProof(
                    parent_name=launcher_coin.parent_coin_info, amount=uint64(launcher_coin.amount)
                ),
                full_puzzle=eve_fullpuz,
                mint_height=uint32(0),
            )

            # Create the eve transaction with targets if present
            if target_list:
                target_ph = target_list[mint_number - mint_number_start]
            else:
                target_ph = p2_inner_ph
            async with self.wallet_state_manager.new_action_scope(
                action_scope.config.tx_config, push=False
            ) as inner_action_scope:
                await self.generate_signed_transaction(
                    [uint64(eve_coin.amount)],
                    [target_ph],
                    inner_action_scope,
                    nft_coin=nft_coin,
                    new_owner=b"",
                    new_did_inner_hash=b"",
                    additional_bundles=[],
                    memos=[[target_ph]],
                )

            async with action_scope.use() as interface:
                interface.side_effects.transactions.extend(inner_action_scope.side_effects.transactions)

            eve_sb = next(
                tx.spend_bundle for tx in inner_action_scope.side_effects.transactions if tx.spend_bundle is not None
            )
            # Extract Puzzle Announcement from eve spend
            eve_sol = eve_sb.coin_spends[0].solution.to_program()
            conds = eve_fullpuz.run(eve_sol)
            eve_puzzle_announcement = [x for x in conds.as_python() if int_from_bytes(x[0]) == 62][0][1]
            assertion = std_hash(eve_fullpuz.get_tree_hash() + eve_puzzle_announcement)
            puzzle_assertions.add(assertion)

        # We've now created all the intermediate, launcher, eve and transfer spends.
        # Create the xch spend to fund the minting.
        spend_value = sum(coin.amount for coin in xch_coins)
        change: uint64 = uint64(spend_value - total_amount)
        xch_spends = []
        if xch_change_ph is None:
            xch_change_ph = await self.standard_wallet.get_new_puzzlehash()
        xch_payment = Payment(xch_change_ph, change, [xch_change_ph])

        first = True
        for xch_coin in xch_coins:
            puzzle: Program = await self.standard_wallet.puzzle_for_puzzle_hash(xch_coin.puzzle_hash)
            if first:
                message_list: List[bytes32] = [c.name() for c in xch_coins]
                message_list.append(Coin(xch_coin.name(), xch_payment.puzzle_hash, xch_payment.amount).name())
                message: bytes32 = std_hash(b"".join(message_list))

                if len(xch_coins) > 1:
                    extra_conditions += (CreateCoinAnnouncement(message),)
                extra_conditions += tuple(AssertCoinAnnouncement(ann) for ann in coin_announcements)
                extra_conditions += tuple(AssertPuzzleAnnouncement(ann) for ann in puzzle_assertions)

                solution: Program = self.standard_wallet.make_solution(
                    primaries=[xch_payment] + primaries,
                    fee=fee,
                    conditions=extra_conditions,
                )
                primary_announcement = AssertCoinAnnouncement(asserted_id=xch_coin.name(), asserted_msg=message)
                first = False
            else:
                solution = self.standard_wallet.make_solution(primaries=[], conditions=(primary_announcement,))
            xch_spends.append(make_spend(xch_coin, puzzle, solution))

        # Collect up all the coin spends and sign them
        list_of_coinspends = intermediate_coin_spends + launcher_spends + xch_spends
        unsigned_spend_bundle = WalletSpendBundle(list_of_coinspends, G2Element())

        # Aggregate everything into a single spend bundle
        async with action_scope.use() as interface:
            # This should not be looked to for best practice. I think many of the spends generated above could call
            # wallet methods that generate transactions and prevent most of the need for this. Refactoring this function
            # is out of scope so for now we're using this hack.
            if interface.side_effects.transactions[0].spend_bundle is None:
                new_spend = unsigned_spend_bundle
            else:
                new_spend = WalletSpendBundle.aggregate(
                    [interface.side_effects.transactions[0].spend_bundle, unsigned_spend_bundle]
                )
            interface.side_effects.transactions[0] = dataclasses.replace(
                interface.side_effects.transactions[0], spend_bundle=new_spend, name=new_spend.name()
            )

    async def select_coins(
        self,
        amount: uint64,
        action_scope: WalletActionScope,
    ) -> Set[Coin]:
        raise RuntimeError("NFTWallet does not support select_coins()")

    def require_derivation_paths(self) -> bool:
        return False

    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:
        raise RuntimeError("NFTWallet does not support puzzle_hash_for_pk")

    def get_name(self) -> str:
        return self.wallet_info.name

    async def match_hinted_coin(self, coin: Coin, hint: bytes32) -> bool:
        return False
