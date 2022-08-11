import dataclasses
import json
import logging
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Type, TypeVar

from blspy import AugSchemeMPL, G2Element

from chia.protocols.wallet_protocol import CoinState
from chia.server.ws_connection import WSChiaConnection
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
from chia.util.ints import uint8, uint16, uint32, uint64, uint128
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.nft_wallet import nft_puzzles
from chia.wallet.nft_wallet.nft_info import NFTCoinInfo, NFTWalletInfo
from chia.wallet.nft_wallet.nft_puzzles import NFT_METADATA_UPDATER, create_ownership_layer_puzzle, get_metadata_and_phs
from chia.wallet.nft_wallet.uncurry_nft import UncurriedNFT
from chia.wallet.outer_puzzles import AssetType, construct_puzzle, match_puzzle, solve_puzzle
from chia.wallet.payment import Payment
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
    puzzle_for_pk,
)
from chia.wallet.trading.offer import OFFER_MOD, NotarizedPayment, Offer
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.debug_spend_bundle import disassemble
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import AmountWithPuzzlehash, WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_info import WalletInfo

_T_NFTWallet = TypeVar("_T_NFTWallet", bound="NFTWallet")


class NFTWallet:
    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    nft_wallet_info: NFTWalletInfo
    my_nft_coins: List[NFTCoinInfo]
    standard_wallet: Wallet
    wallet_id: int

    @property
    def did_id(self):
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
        self.my_nft_coins = []
        info_as_string = json.dumps(self.nft_wallet_info.to_json_dict())
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            name, uint32(WalletType.NFT.value), info_as_string
        )
        self.wallet_id = self.wallet_info.id
        self.log.debug("NFT wallet id: %r and standard wallet id: %r", self.wallet_id, self.standard_wallet.wallet_id)

        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id)
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
        self.my_nft_coins = await self.wallet_state_manager.nft_store.get_nft_list(wallet_id=self.wallet_id)
        self.nft_wallet_info = NFTWalletInfo.from_json_dict(json.loads(wallet_info.data))
        return self

    @classmethod
    def type(cls) -> uint8:
        return uint8(WalletType.NFT)

    def id(self) -> uint32:
        return self.wallet_info.id

    def get_did(self) -> Optional[bytes32]:
        return self.did_id

    async def get_confirmed_balance(self, record_list=None) -> uint128:
        """The NFT wallet doesn't really have a balance."""
        return uint128(0)

    async def get_unconfirmed_balance(self, record_list=None) -> uint128:
        """The NFT wallet doesn't really have a balance."""
        return uint128(0)

    async def get_spendable_balance(self, unspent_records=None) -> uint128:
        """The NFT wallet doesn't really have a balance."""
        return uint128(0)

    async def get_pending_change_balance(self) -> uint64:
        return uint64(0)

    async def get_max_send_amount(self, records=None):
        """This is the confirmed balance, which we set to 0 as the NFT wallet doesn't have one."""
        return uint128(0)

    def get_nft_coin_by_id(self, nft_coin_id: bytes32) -> NFTCoinInfo:
        for nft_coin in self.my_nft_coins:
            if nft_coin.coin.name() == nft_coin_id:
                return nft_coin
        raise KeyError(f"Couldn't find coin with id: {nft_coin_id}")

    async def coin_added(self, coin: Coin, height: uint32, peer: WSChiaConnection) -> None:
        """Notification from wallet state manager that wallet has been received."""
        self.log.info(f"NFT wallet %s has been notified that {coin} was added", self.wallet_info.name)
        for coin_info in self.my_nft_coins:
            if coin_info.coin == coin:
                return
        wallet_node = self.wallet_state_manager.wallet_node
        cs: Optional[CoinSpend] = None
        coin_states: Optional[List[CoinState]] = await wallet_node.get_coin_state([coin.parent_coin_info], peer=peer)
        if not coin_states:
            # farm coin
            return
        assert coin_states
        parent_coin = coin_states[0].coin
        cs = await wallet_node.fetch_puzzle_solution(height, parent_coin, peer)
        assert cs is not None
        await self.puzzle_solution_received(cs, peer)

    async def puzzle_solution_received(self, coin_spend: CoinSpend, peer: WSChiaConnection) -> None:
        self.log.debug("Puzzle solution received to wallet: %s", self.wallet_info)
        coin_name = coin_spend.coin.name()
        puzzle: Program = Program.from_bytes(bytes(coin_spend.puzzle_reveal))
        # At this point, the puzzle must be a NFT puzzle.
        # This method will be called only when the wallet state manager uncurried this coin as a NFT puzzle.

        uncurried_nft = UncurriedNFT.uncurry(*puzzle.uncurry())
        assert uncurried_nft is not None
        self.log.info(
            f"found the info for NFT coin {coin_name} {uncurried_nft.inner_puzzle} {uncurried_nft.singleton_struct}"
        )
        singleton_id = uncurried_nft.singleton_launcher_id
        parent_inner_puzhash = uncurried_nft.nft_state_layer.get_tree_hash()
        metadata, p2_puzzle_hash = get_metadata_and_phs(uncurried_nft, coin_spend.solution)
        self.log.debug("Got back puzhash from solution: %s", p2_puzzle_hash)
        self.log.debug("Got back updated metadata: %s", metadata)
        derivation_record: Optional[
            DerivationRecord
        ] = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(p2_puzzle_hash)
        self.log.debug("Record for %s is: %s", p2_puzzle_hash, derivation_record)
        if derivation_record is None:
            self.log.debug(f"Not our NFT, pointing to {p2_puzzle_hash}, skipping")
            return
        p2_puzzle = puzzle_for_pk(derivation_record.pubkey)
        if uncurried_nft.supports_did:
            inner_puzzle = nft_puzzles.recurry_nft_puzzle(uncurried_nft, coin_spend.solution.to_program(), p2_puzzle)

        else:
            inner_puzzle = p2_puzzle
        child_puzzle: Program = nft_puzzles.create_full_puzzle(
            singleton_id,
            Program.to(metadata),
            bytes32(uncurried_nft.metadata_updater_hash.atom),
            inner_puzzle,
        )
        self.log.debug(
            "Created NFT full puzzle with inner: %s",
            nft_puzzles.create_full_puzzle_with_nft_puzzle(singleton_id, uncurried_nft.inner_puzzle),
        )
        for new_coin in coin_spend.additions():
            self.log.debug(
                "Comparing addition: %s with %s, amount: %s ",
                new_coin.puzzle_hash,
                child_puzzle.get_tree_hash(),
                new_coin.amount,
            )
            if new_coin.puzzle_hash == child_puzzle.get_tree_hash():
                child_coin = new_coin
                break
        else:
            raise ValueError("Couldn't generate child puzzle for NFT")
        launcher_coin_states: List[CoinState] = await self.wallet_state_manager.wallet_node.get_coin_state(
            [singleton_id], peer=peer
        )
        assert (
            launcher_coin_states is not None
            and len(launcher_coin_states) == 1
            and launcher_coin_states[0].spent_height is not None
        )
        mint_height: uint32 = launcher_coin_states[0].spent_height
        self.log.info("Adding a new NFT to wallet: %s", child_coin)

        # all is well, lets add NFT to our local db
        parent_coin = None
        confirmed_height = None
        coin_states: Optional[List[CoinState]] = await self.wallet_state_manager.wallet_node.get_coin_state(
            [coin_name], peer=peer
        )
        if coin_states is not None:
            parent_coin = coin_states[0].coin
            confirmed_height = coin_states[0].spent_height

        if parent_coin is None or confirmed_height is None:
            raise ValueError("Error finding parent")

        await self.add_coin(
            child_coin,
            singleton_id,
            child_puzzle,
            LineageProof(parent_coin.parent_coin_info, parent_inner_puzhash, uint64(parent_coin.amount)),
            mint_height,
            confirmed_height,
        )

    async def add_coin(
        self,
        coin: Coin,
        nft_id: bytes32,
        puzzle: Program,
        lineage_proof: LineageProof,
        mint_height: uint32,
        confirmed_height: uint32,
    ) -> None:
        my_nft_coins = self.my_nft_coins
        for coin_info in my_nft_coins:
            if coin_info.coin == coin:
                my_nft_coins.remove(coin_info)
        new_nft = NFTCoinInfo(nft_id, coin, lineage_proof, puzzle, mint_height, confirmed_height)
        my_nft_coins.append(new_nft)
        await self.wallet_state_manager.nft_store.save_nft(self.id(), self.get_did(), new_nft)
        await self.wallet_state_manager.add_interested_coin_ids([coin.name()])
        self.wallet_state_manager.state_changed("nft_coin_added", self.wallet_info.id)
        return

    async def remove_coin(self, coin: Coin, height: uint32) -> None:
        my_nft_coins = self.my_nft_coins
        for coin_info in my_nft_coins:
            if coin_info.coin == coin:
                my_nft_coins.remove(coin_info)
                await self.wallet_state_manager.nft_store.delete_nft(coin_info.nft_id, height)
        self.wallet_state_manager.state_changed("nft_coin_removed", self.wallet_info.id)
        return

    async def get_did_approval_info(
        self,
        nft_id: bytes32,
        did_id: bytes32 = None,
    ) -> Tuple[bytes32, SpendBundle]:
        """Get DID spend with announcement created we need to transfer NFT with did with current inner hash of DID

        We also store `did_id` and then iterate to find the did wallet as we'd otherwise have to subscribe to
        any changes to DID wallet and storing wallet_id is not guaranteed to be consistent on wallet crash/reset.
        """
        if did_id is None:
            did_id = self.did_id
        for _, wallet in self.wallet_state_manager.wallets.items():
            self.log.debug("Checking wallet type %s", wallet.type())
            if wallet.type() == WalletType.DECENTRALIZED_ID:
                self.log.debug("Found a DID wallet, checking did: %r == %r", wallet.get_my_DID(), did_id)
                if bytes32.fromhex(wallet.get_my_DID()) == did_id:
                    self.log.debug("Creating announcement from DID for nft_id: %s", nft_id)
                    did_bundle = await wallet.create_message_spend(puzzle_announcements=[nft_id])
                    self.log.debug("Sending DID announcement from puzzle: %s", did_bundle.removals())
                    did_inner_hash = wallet.did_info.current_inner.get_tree_hash()
                    break
        else:
            raise ValueError(f"Missing DID Wallet for did_id: {did_id}")
        return did_inner_hash, did_bundle

    async def generate_new_nft(
        self,
        metadata: Program,
        target_puzzle_hash: Optional[bytes32] = None,
        royalty_puzzle_hash: Optional[bytes32] = None,
        percentage: uint16 = uint16(0),
        did_id: Optional[bytes] = None,
        fee: uint64 = uint64(0),
        push_tx: bool = True,
    ) -> Optional[SpendBundle]:
        """
        This must be called under the wallet state manager lock
        """
        if self.did_id is not None and did_id is None:
            # For a DID enabled NFT wallet it cannot mint NFT0. Mint NFT1 instead.
            did_id = self.did_id
        amount = uint64(1)
        coins = await self.standard_wallet.select_coins(uint64(amount + fee))
        if coins is None:
            return None
        origin = coins.copy().pop()
        genesis_launcher_puz = nft_puzzles.LAUNCHER_PUZZLE
        # nft_id == singleton_id == launcher_id == launcher_coin.name()
        launcher_coin = Coin(origin.name(), genesis_launcher_puz.get_tree_hash(), uint64(amount))
        self.log.debug("Generating NFT with launcher coin %s and metadata: %s", launcher_coin, metadata)

        p2_inner_puzzle = await self.standard_wallet.get_new_puzzle()
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
            self.log.debug("Got back ownership inner puzzle: %s", disassemble(inner_puzzle))
        else:
            self.log.debug("Creating standard NFT")
            inner_puzzle = p2_inner_puzzle

        # singleton eve puzzle
        eve_fullpuz = nft_puzzles.create_full_puzzle(
            launcher_coin.name(), metadata, NFT_METADATA_UPDATER.get_tree_hash(), inner_puzzle
        )
        # launcher announcement
        announcement_set: Set[Announcement] = set()
        announcement_message = Program.to([eve_fullpuz.get_tree_hash(), amount, []]).get_tree_hash()
        announcement_set.add(Announcement(launcher_coin.name(), announcement_message))

        self.log.debug(
            "Creating transaction for launcher: %s and other coins: %s (%s)", origin, coins, announcement_set
        )
        # store the launcher transaction in the wallet state
        tx_record: Optional[TransactionRecord] = await self.standard_wallet.generate_signed_transaction(
            uint64(amount),
            genesis_launcher_puz.get_tree_hash(),
            fee,
            origin.name(),
            coins,
            None,
            False,
            announcement_set,
        )
        genesis_launcher_solution = Program.to([eve_fullpuz.get_tree_hash(), amount, []])

        # launcher spend to generate the singleton
        launcher_cs = CoinSpend(launcher_coin, genesis_launcher_puz, genesis_launcher_solution)
        launcher_sb = SpendBundle([launcher_cs], AugSchemeMPL.aggregate([]))

        eve_coin = Coin(launcher_coin.name(), eve_fullpuz.get_tree_hash(), uint64(amount))

        if tx_record is None or tx_record.spend_bundle is None:
            self.log.error("Couldn't produce a launcher spend")
            return None

        bundles_to_agg = [tx_record.spend_bundle, launcher_sb]

        # Create inner solution for eve spend
        did_inner_hash = b""
        if did_id is not None:
            if did_id != b"":
                did_inner_hash, did_bundle = await self.get_did_approval_info(launcher_coin.name())
                bundles_to_agg.append(did_bundle)
        nft_coin = NFTCoinInfo(
            nft_id=launcher_coin.name(),
            coin=eve_coin,
            lineage_proof=LineageProof(parent_name=launcher_coin.parent_coin_info, amount=uint64(launcher_coin.amount)),
            full_puzzle=eve_fullpuz,
            mint_height=uint32(0),
        )
        # Don't set fee, it is covered in the tx_record
        txs = await self.generate_signed_transaction(
            [uint64(eve_coin.amount)],
            [target_puzzle_hash],
            nft_coin=nft_coin,
            new_owner=did_id,
            new_did_inner_hash=did_inner_hash,
            additional_bundles=bundles_to_agg,
            memos=[[target_puzzle_hash]],
        )
        txs.append(dataclasses.replace(tx_record, spend_bundle=None))
        if push_tx:
            for tx in txs:
                await self.wallet_state_manager.add_pending_transaction(tx)
        return SpendBundle.aggregate([x.spend_bundle for x in txs if x.spend_bundle is not None])

    async def sign(self, spend_bundle: SpendBundle, puzzle_hashes: List[bytes32] = None) -> SpendBundle:
        if puzzle_hashes is None:
            puzzle_hashes = []
        sigs: List[G2Element] = []
        for spend in spend_bundle.coin_spends:
            pks = {}
            if not puzzle_hashes:
                uncurried_nft = UncurriedNFT.uncurry(*spend.puzzle_reveal.to_program().uncurry())
                if uncurried_nft is not None:
                    self.log.debug("Found a NFT state layer to sign")
                    puzzle_hashes.append(uncurried_nft.p2_puzzle.get_tree_hash())
            for ph in puzzle_hashes:
                keys = await self.wallet_state_manager.get_keys(ph)
                assert keys
                pks[bytes(keys[0])] = private = keys[1]
                synthetic_secret_key = calculate_synthetic_secret_key(private, DEFAULT_HIDDEN_PUZZLE_HASH)
                synthetic_pk = synthetic_secret_key.get_g1()
                pks[bytes(synthetic_pk)] = synthetic_secret_key
            error, conditions, cost = conditions_dict_for_solution(
                spend.puzzle_reveal.to_program(),
                spend.solution.to_program(),
                self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM,
            )
            if conditions is not None:
                for pk, msg in pkm_pairs_for_conditions_dict(
                    conditions, spend.coin.name(), self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA
                ):
                    try:
                        sk = pks.get(pk)
                        if sk:
                            self.log.debug("Found key, signing for pk: %s", pk)
                            sigs.append(AugSchemeMPL.sign(sk, msg))
                        else:
                            self.log.warning("Couldn't find key for: %s", pk)
                    except AssertionError:
                        raise ValueError("This spend bundle cannot be signed by the NFT wallet")

        agg_sig = AugSchemeMPL.aggregate(sigs)
        return SpendBundle.aggregate([spend_bundle, SpendBundle([], agg_sig)])

    async def update_metadata(
        self, nft_coin_info: NFTCoinInfo, key: str, uri: str, fee: uint64 = uint64(0)
    ) -> Optional[SpendBundle]:
        uncurried_nft = UncurriedNFT.uncurry(*nft_coin_info.full_puzzle.uncurry())
        assert uncurried_nft is not None
        puzzle_hash = uncurried_nft.p2_puzzle.get_tree_hash()

        self.log.info(
            "Attempting to add urls to NFT coin %s in the metadata: %s",
            nft_coin_info.coin.name(),
            uncurried_nft.metadata,
        )
        txs = await self.generate_signed_transaction(
            [uint64(nft_coin_info.coin.amount)], [puzzle_hash], fee, {nft_coin_info.coin}, metadata_update=(key, uri)
        )
        for tx in txs:
            await self.wallet_state_manager.add_pending_transaction(tx)
        await self.update_coin_status(nft_coin_info.coin.name(), True)
        self.wallet_state_manager.state_changed("nft_coin_updated", self.wallet_info.id)
        return SpendBundle.aggregate([x.spend_bundle for x in txs if x.spend_bundle is not None])

    def get_current_nfts(self) -> List[NFTCoinInfo]:
        return self.my_nft_coins

    async def load_current_nft(self) -> List[NFTCoinInfo]:
        self.my_nft_coins = await self.wallet_state_manager.nft_store.get_nft_list(wallet_id=self.wallet_id)
        return self.my_nft_coins

    async def update_coin_status(self, coin_id: bytes32, pending_transaction: bool) -> None:
        my_nft_coins = self.my_nft_coins
        target_nft: Optional[NFTCoinInfo] = None
        for coin_info in my_nft_coins:
            if coin_info.coin.name() == coin_id:
                target_nft = coin_info
                my_nft_coins.remove(coin_info)
        if target_nft is None:
            raise ValueError(f"NFT coin {coin_id} doesn't exist.")
        new_nft = NFTCoinInfo(
            target_nft.nft_id,
            target_nft.coin,
            target_nft.lineage_proof,
            target_nft.full_puzzle,
            target_nft.mint_height,
            target_nft.latest_height,
            pending_transaction,
        )
        my_nft_coins.append(new_nft)
        await self.wallet_state_manager.nft_store.save_nft(self.id(), self.get_did(), new_nft)

    async def save_info(self, nft_info: NFTWalletInfo) -> None:
        self.nft_wallet_info = nft_info
        current_info = self.wallet_info
        data_str = json.dumps(nft_info.to_json_dict())
        wallet_info = WalletInfo(current_info.id, current_info.name, current_info.type, data_str)
        self.wallet_info = wallet_info
        await self.wallet_state_manager.user_store.update_wallet(wallet_info)

    async def convert_puzzle_hash(self, puzhash: bytes32) -> bytes32:
        return puzhash

    def get_nft(self, launcher_id: bytes32) -> Optional[NFTCoinInfo]:
        for coin in self.my_nft_coins:
            if coin.nft_id == launcher_id:
                return coin
        return None

    def get_puzzle_info(self, nft_id: bytes32) -> PuzzleInfo:
        nft_coin: Optional[NFTCoinInfo] = self.get_nft(nft_id)
        if nft_coin is None:
            raise ValueError("An asset ID was specified that this wallet doesn't track")
        puzzle_info: Optional[PuzzleInfo] = match_puzzle(nft_coin.full_puzzle)
        if puzzle_info is None:
            raise ValueError("Internal Error: NFT wallet is tracking a non NFT coin")
        else:
            return puzzle_info

    async def get_coins_to_offer(
        self, nft_id: bytes32, amount: uint64, min_coin_amount: Optional[uint64] = None
    ) -> Set[Coin]:
        nft_coin: Optional[NFTCoinInfo] = self.get_nft(nft_id)
        if nft_coin is None:
            raise ValueError("An asset ID was specified that this wallet doesn't track")
        return {nft_coin.coin}

    def match_puzzle_info(self, puzzle_driver: PuzzleInfo) -> bool:
        return (
            AssetType(puzzle_driver.type()) == AssetType.SINGLETON
            and self.get_nft(puzzle_driver["launcher_id"]) is not None
            and puzzle_driver.also() is not None
            and AssetType(puzzle_driver.also().type()) == AssetType.METADATA  # type: ignore
            and puzzle_driver.also().also() is None  # type: ignore
        )

    @classmethod
    async def create_from_puzzle_info(
        cls,
        wallet_state_manager: Any,
        wallet: Wallet,
        puzzle_driver: PuzzleInfo,
        name=None,
    ) -> Any:
        # Off the bat we don't support multiple profile but when we do this will have to change
        for wallet in wallet_state_manager.wallets.values():
            if wallet.type() == WalletType.NFT:
                return wallet

        # TODO: These are not the arguments to this function yet but they will be
        return await cls.create_new_nft_wallet(
            wallet_state_manager,
            wallet,
            None,
            name,
        )

    async def create_tandem_xch_tx(
        self, fee: uint64, announcement_to_assert: Optional[Announcement] = None
    ) -> TransactionRecord:
        chia_coins = await self.standard_wallet.select_coins(fee)
        chia_tx = await self.standard_wallet.generate_signed_transaction(
            uint64(0),
            (await self.standard_wallet.get_new_puzzlehash()),
            fee=fee,
            coins=chia_coins,
            coin_announcements_to_consume={announcement_to_assert} if announcement_to_assert is not None else None,
        )
        assert chia_tx.spend_bundle is not None
        return chia_tx

    async def generate_signed_transaction(
        self,
        amounts: List[uint64],
        puzzle_hashes: List[bytes32],
        fee: uint64 = uint64(0),
        coins: Set[Coin] = None,
        nft_coin: Optional[NFTCoinInfo] = None,
        memos: Optional[List[List[bytes]]] = None,
        coin_announcements_to_consume: Optional[Set[Announcement]] = None,
        puzzle_announcements_to_consume: Optional[Set[Announcement]] = None,
        ignore_max_send_amount: bool = False,
        new_owner: Optional[bytes] = None,
        new_did_inner_hash: Optional[bytes] = None,
        trade_prices_list: Optional[Program] = None,
        additional_bundles: List[SpendBundle] = [],
        metadata_update: Tuple[str, str] = None,
    ) -> List[TransactionRecord]:
        if memos is None:
            memos = [[] for _ in range(len(puzzle_hashes))]

        if not (len(memos) == len(puzzle_hashes) == len(amounts)):
            raise ValueError("Memos, puzzle_hashes, and amounts must have the same length")

        payments = []
        for amount, puzhash, memo_list in zip(amounts, puzzle_hashes, memos):
            memos_with_hint: List[bytes] = [puzhash]
            memos_with_hint.extend(memo_list)
            payments.append(Payment(puzhash, amount, memos_with_hint))

        payment_sum = sum([p.amount for p in payments])

        unsigned_spend_bundle, chia_tx = await self.generate_unsigned_spendbundle(
            payments,
            fee,
            coins=coins,
            nft_coin=nft_coin,
            coin_announcements_to_consume=coin_announcements_to_consume,
            puzzle_announcements_to_consume=puzzle_announcements_to_consume,
            new_owner=new_owner,
            new_did_inner_hash=new_did_inner_hash,
            trade_prices_list=trade_prices_list,
            metadata_update=metadata_update,
        )
        spend_bundle = await self.sign(unsigned_spend_bundle)
        spend_bundle = SpendBundle.aggregate([spend_bundle] + additional_bundles)
        if chia_tx is not None and chia_tx.spend_bundle is not None:
            spend_bundle = SpendBundle.aggregate([spend_bundle, chia_tx.spend_bundle])
            chia_tx = dataclasses.replace(chia_tx, spend_bundle=None)

        tx_list = [
            TransactionRecord(
                confirmed_at_height=uint32(0),
                created_at_time=uint64(int(time.time())),
                to_puzzle_hash=puzzle_hashes[0],
                amount=uint64(payment_sum),
                fee_amount=fee,
                confirmed=False,
                sent=uint32(0),
                spend_bundle=spend_bundle,
                additions=spend_bundle.additions(),
                removals=spend_bundle.removals(),
                wallet_id=self.id(),
                sent_to=[],
                trade_id=None,
                type=uint32(TransactionType.OUTGOING_TX.value),
                name=spend_bundle.name(),
                memos=list(compute_memos(spend_bundle).items()),
            ),
        ]

        if chia_tx is not None:
            tx_list.append(chia_tx)

        return tx_list

    async def generate_unsigned_spendbundle(
        self,
        payments: List[Payment],
        fee: uint64 = uint64(0),
        coins: Set[Coin] = None,
        coin_announcements_to_consume: Optional[Set[Announcement]] = None,
        puzzle_announcements_to_consume: Optional[Set[Announcement]] = None,
        new_owner: Optional[bytes] = None,
        new_did_inner_hash: Optional[bytes] = None,
        trade_prices_list: Optional[Program] = None,
        metadata_update: Tuple[str, str] = None,
        nft_coin: Optional[NFTCoinInfo] = None,
    ) -> Tuple[SpendBundle, Optional[TransactionRecord]]:
        if nft_coin is None:
            if coins is None or len(coins) > 1:
                # Make sure the user is specifying which specific NFT coin to use
                raise ValueError("NFT spends require a single selected coin")
            elif len(payments) > 1:
                raise ValueError("NFTs can only be sent to one party")

            nft_coin = next(c for c in self.my_nft_coins if c.coin in coins)

        if coin_announcements_to_consume is not None:
            coin_announcements_bytes: Optional[Set[bytes32]] = {a.name() for a in coin_announcements_to_consume}
        else:
            coin_announcements_bytes = None

        if puzzle_announcements_to_consume is not None:
            puzzle_announcements_bytes: Optional[Set[bytes32]] = {a.name() for a in puzzle_announcements_to_consume}
        else:
            puzzle_announcements_bytes = None

        primaries: List = []
        for payment in payments:
            primaries.append({"puzzlehash": payment.puzzle_hash, "amount": payment.amount, "memos": payment.memos})

        if fee > 0:
            announcement_to_make = nft_coin.coin.name()
            chia_tx = await self.create_tandem_xch_tx(fee, Announcement(nft_coin.coin.name(), announcement_to_make))
        else:
            announcement_to_make = None
            chia_tx = None

        innersol: Program = self.standard_wallet.make_solution(
            primaries=primaries,
            coin_announcements=None if announcement_to_make is None else set((announcement_to_make,)),
            coin_announcements_to_assert=coin_announcements_bytes,
            puzzle_announcements_to_assert=puzzle_announcements_bytes,
        )

        unft = UncurriedNFT.uncurry(*nft_coin.full_puzzle.uncurry())
        assert unft is not None
        magic_condition = None
        if unft.supports_did:
            if new_owner is None:
                # If no new owner was specified and we're sending this to ourselves, let's not reset the DID
                derivation_record: Optional[
                    DerivationRecord
                ] = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(
                    payments[0].puzzle_hash
                )
                if derivation_record is not None:
                    new_owner = unft.owner_did
            magic_condition = Program.to([-10, new_owner, trade_prices_list, new_did_inner_hash])
        if metadata_update:
            # We don't support update metadata while changing the ownership
            magic_condition = Program.to([-24, NFT_METADATA_UPDATER, metadata_update])
        if magic_condition:
            # TODO: This line is a hack, make_solution should allow us to pass extra conditions to it
            innersol = Program.to([[], (1, magic_condition.cons(innersol.at("rfr"))), []])
        if unft.supports_did:
            innersol = Program.to([innersol])

        nft_layer_solution = Program.to([innersol])
        assert isinstance(nft_coin.lineage_proof, LineageProof)
        singleton_solution = Program.to([nft_coin.lineage_proof.to_program(), nft_coin.coin.amount, nft_layer_solution])
        coin_spend = CoinSpend(nft_coin.coin, nft_coin.full_puzzle, singleton_solution)

        nft_spend_bundle = SpendBundle([coin_spend], G2Element())

        return nft_spend_bundle, chia_tx

    @staticmethod
    async def make_nft1_offer(
        wallet_state_manager: Any,
        offer_dict: Dict[Optional[bytes32], int],
        driver_dict: Dict[bytes32, PuzzleInfo],
        fee: uint64,
        min_coin_amount: Optional[uint64] = None,
    ) -> Offer:
        amounts = list(offer_dict.values())  # Note: this does not include the royalties
        if len(offer_dict) != 2 or (amounts[0] > 0 == amounts[1] > 0):
            raise ValueError("Royalty enabled NFTs only support offering/requesting one NFT for one currency")

        offering_nft: bool = False
        for asset_id, amount in offer_dict.items():
            if amount < 0:  # negative means offering
                offered_asset_id: Optional[bytes32] = asset_id
                if asset_id is not None:
                    offering_nft = driver_dict[asset_id].check_type(  # check if asset is an NFT
                        [
                            AssetType.SINGLETON.value,
                            AssetType.METADATA.value,
                            AssetType.OWNERSHIP.value,
                        ]
                    )
            else:
                requested_asset_id: Optional[bytes32] = asset_id

        if offering_nft:  # if we are offering an NFT.
            assert offered_asset_id is not None  # hello mypy
            driver_dict[offered_asset_id].info["also"]["also"]["owner"] = "()"
            wallet = await wallet_state_manager.get_wallet_for_asset_id(offered_asset_id.hex())
            p2_ph = await wallet_state_manager.main_wallet.get_new_puzzlehash()
            offered_amount: uint64 = uint64(abs(offer_dict[offered_asset_id]))
            offered_coin_info = wallet.get_nft(offered_asset_id)
            offered_coin: Coin = offered_coin_info.coin
            requested_amount = offer_dict[requested_asset_id]
            if requested_asset_id is None:  # If we are just asking for xch.
                trade_prices = Program.to([[uint64(requested_amount), OFFER_MOD.get_tree_hash()]])
            else:
                trade_prices = Program.to(
                    [
                        [
                            uint64(requested_amount),
                            construct_puzzle(driver_dict[requested_asset_id], OFFER_MOD).get_tree_hash(),
                        ]
                    ]
                )
            notarized_payments: Dict[Optional[bytes32], List[NotarizedPayment]] = Offer.notarize_payments(
                {requested_asset_id: [Payment(p2_ph, uint64(requested_amount), [p2_ph])]}, [offered_coin]
            )
            announcements = Offer.calculate_announcements(notarized_payments, driver_dict)
            txs = await wallet.generate_signed_transaction(
                [offered_amount],
                [Offer.ph()],
                fee=fee,
                coins={offered_coin},
                puzzle_announcements_to_consume=set(announcements),
                trade_prices_list=trade_prices,
            )
            transaction_bundles: List[SpendBundle] = [tx.spend_bundle for tx in txs if tx.spend_bundle is not None]
            total_spend_bundle = SpendBundle.aggregate(transaction_bundles)

            return Offer(notarized_payments, total_spend_bundle, driver_dict)
        elif isinstance(requested_asset_id, bytes32):  # if we are requesting an NFT.
            driver_dict[requested_asset_id].info["also"]["also"]["owner"] = "()"
            requested_info = driver_dict[requested_asset_id]
            transfer_info = requested_info.also().also()  # type: ignore
            assert isinstance(transfer_info, PuzzleInfo)
            royalty_percentage = uint16(transfer_info["transfer_program"]["royalty_percentage"])
            royalty_address = bytes32(transfer_info["transfer_program"]["royalty_address"])
            p2_ph = await wallet_state_manager.main_wallet.get_new_puzzlehash()
            requested_payments: Dict[Optional[bytes32], List[Payment]] = {
                requested_asset_id: [Payment(p2_ph, uint64(offer_dict[requested_asset_id]), [p2_ph])]
            }
            offered_amount = uint64(abs(offer_dict[offered_asset_id]))
            royalty_amount = uint64(offered_amount * royalty_percentage / 10000)
            if offered_amount == royalty_amount:
                # Due to the coin id's matching this is impossible unless we use separate coins
                # when fulfilling the offer.
                raise ValueError("Amount offered and amount paid in royalties are equal")
            if offered_asset_id is None:  # xch offer
                wallet = wallet_state_manager.main_wallet
                coin_amount_needed: int = offered_amount + royalty_amount + fee
            else:
                # cat offer
                wallet = await wallet_state_manager.get_wallet_for_asset_id(offered_asset_id.hex())
                coin_amount_needed = offered_amount + royalty_amount

            pmt_coins = list(await wallet.get_coins_to_offer(offered_asset_id, coin_amount_needed, min_coin_amount))
            notarized_payments = Offer.notarize_payments(requested_payments, pmt_coins)
            announcements_to_assert = Offer.calculate_announcements(notarized_payments, driver_dict)
            # Calculate the royalty announcement separately
            announcements_to_assert.extend(
                Offer.calculate_announcements(
                    {
                        offered_asset_id: [
                            NotarizedPayment(royalty_address, royalty_amount, [royalty_address], requested_asset_id)
                        ]
                    },
                    driver_dict,
                )
            )
            if wallet.type() == WalletType.STANDARD_WALLET:
                tx = await wallet.generate_signed_transaction(
                    offered_amount,
                    Offer.ph(),
                    primaries=[AmountWithPuzzlehash({"amount": royalty_amount, "puzzlehash": Offer.ph(), "memos": []})],
                    fee=fee,
                    coins=set(pmt_coins),
                    puzzle_announcements_to_consume=announcements_to_assert,
                )
                all_transactions: List[TransactionRecord] = [tx]
            else:
                txs = await wallet.generate_signed_transaction(
                    [offered_amount, royalty_amount],
                    [Offer.ph(), Offer.ph()],
                    fee=fee,
                    coins=set(pmt_coins),
                    puzzle_announcements_to_consume=announcements_to_assert,
                )
                all_transactions = txs

            txn_bundles: List[SpendBundle] = [tx.spend_bundle for tx in all_transactions if tx.spend_bundle is not None]
            txn_spend_bundle = SpendBundle.aggregate(txn_bundles)
            # Create a spend bundle for the royalty payout from OFFER MOD
            # make the royalty payment solution
            # ((nft_launcher_id . ((ROYALTY_ADDRESS, royalty_amount, (ROYALTY_ADDRESS)))))
            # we are basically just recreating the royalty announcement above.
            inner_royalty_sol = Program.to([[requested_asset_id, [royalty_address, royalty_amount, [royalty_address]]]])
            if offered_asset_id is None:  # xch offer
                offer_puzzle: Program = OFFER_MOD
                royalty_sol = inner_royalty_sol
            else:  # CAT
                offer_puzzle = construct_puzzle(driver_dict[offered_asset_id], OFFER_MOD)
            royalty_ph = offer_puzzle.get_tree_hash()
            for txn in txn_bundles:
                for coin in txn.additions():
                    if coin.amount == royalty_amount and coin.puzzle_hash == royalty_ph:
                        royalty_coin = coin
                        parent_spend = txn.coin_spends[0]
            assert royalty_coin
            if offered_asset_id is not None:  # if CAT
                #  adapt royalty_sol to work with cat puzzle
                royalty_coin_hex = (
                    "0x"
                    + royalty_coin.parent_coin_info.hex()
                    + royalty_coin.puzzle_hash.hex()
                    + bytes(uint64(royalty_coin.amount)).hex()
                )
                parent_spend_hex: str = "0x" + bytes(parent_spend).hex()
                solver = Solver(
                    {
                        "coin": royalty_coin_hex,
                        "parent_spend": parent_spend_hex,
                        "siblings": "(" + royalty_coin_hex + ")",
                        "sibling_spends": "(" + parent_spend_hex + ")",
                        "sibling_puzzles": "()",
                        "sibling_solutions": "()",
                    }
                )
                royalty_sol = solve_puzzle(driver_dict[offered_asset_id], solver, OFFER_MOD, inner_royalty_sol)

            royalty_spend = SpendBundle([CoinSpend(royalty_coin, offer_puzzle, royalty_sol)], G2Element())
            total_spend_bundle = SpendBundle.aggregate([txn_spend_bundle, royalty_spend])
            offer = Offer(notarized_payments, total_spend_bundle, driver_dict)
            return offer
        else:
            raise ValueError("No NFT in offer!")

    async def set_nft_did(self, nft_coin_info: NFTCoinInfo, did_id: bytes, fee: uint64 = uint64(0)) -> SpendBundle:
        self.log.debug("Setting NFT DID with parameters: nft=%s did=%s", nft_coin_info, did_id)
        unft = UncurriedNFT.uncurry(*nft_coin_info.full_puzzle.uncurry())
        assert unft is not None
        nft_id = unft.singleton_launcher_id
        puzzle_hashes_to_sign = [unft.p2_puzzle.get_tree_hash()]
        did_inner_hash = b""
        additional_bundles = []
        if did_id != b"":
            did_inner_hash, did_bundle = await self.get_did_approval_info(nft_id, bytes32(did_id))
            additional_bundles.append(did_bundle)

        nft_tx_record = await self.generate_signed_transaction(
            [uint64(nft_coin_info.coin.amount)],
            puzzle_hashes_to_sign,
            fee,
            {nft_coin_info.coin},
            new_owner=did_id,
            new_did_inner_hash=did_inner_hash,
            additional_bundles=additional_bundles,
        )
        spend_bundle = SpendBundle.aggregate([x.spend_bundle for x in nft_tx_record if x.spend_bundle is not None])
        if spend_bundle:
            for tx in nft_tx_record:
                await self.wallet_state_manager.add_pending_transaction(tx)
            await self.update_coin_status(nft_coin_info.coin.name(), True)
            self.wallet_state_manager.state_changed("nft_coin_did_set", self.wallet_info.id)
            return spend_bundle
        else:
            raise ValueError("Couldn't set DID on given NFT")
