from __future__ import annotations

import dataclasses
import logging
import time
from operator import attrgetter
from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional, Set, Tuple, cast

from blspy import G1Element, G2Element
from clvm.EvalError import EvalError
from typing_extensions import Unpack, final

from chia.consensus.block_record import BlockRecord
from chia.data_layer.data_layer_errors import LauncherCoinNotFoundError, OfferIntegrityError
from chia.data_layer.data_layer_util import OfferStore, ProofOfInclusion, ProofOfInclusionLayer, StoreProofs, leaf_hash
from chia.protocols.wallet_protocol import CoinState
from chia.server.ws_connection import WSChiaConnection
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend, compute_additions
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.streamable import Streamable, streamable
from chia.wallet.db_wallet.db_wallet_puzzles import (
    ACS_MU,
    ACS_MU_PH,
    GRAFTROOT_DL_OFFERS,
    SINGLETON_LAUNCHER,
    create_graftroot_offer_puz,
    create_host_fullpuz,
    create_host_layer_puzzle,
    create_mirror_puzzle,
    get_mirror_info,
    launch_solution_to_singleton_info,
    launcher_to_struct,
    match_dl_singleton,
)
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.outer_puzzles import AssetType
from chia.wallet.payment import Payment
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.puzzles.singleton_top_layer_v1_1 import SINGLETON_LAUNCHER_HASH
from chia.wallet.sign_coin_spends import sign_coin_spends
from chia.wallet.trading.offer import NotarizedPayment, Offer
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.merkle_utils import _simplify_merkle_proof
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_sync_utils import fetch_coin_spend, fetch_coin_spend_for_coin_state
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_protocol import GSTOptionalArgs, WalletProtocol

if TYPE_CHECKING:
    from chia.wallet.wallet_state_manager import WalletStateManager


@streamable
@dataclasses.dataclass(frozen=True)
class SingletonRecord(Streamable):
    coin_id: bytes32
    launcher_id: bytes32
    root: bytes32
    inner_puzzle_hash: bytes32
    confirmed: bool
    confirmed_at_height: uint32
    lineage_proof: LineageProof
    generation: uint32
    timestamp: uint64


@dataclasses.dataclass(frozen=True)
class Mirror:
    coin_id: bytes32
    launcher_id: bytes32
    amount: uint64
    urls: List[bytes]
    ours: bool

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            "coin_id": self.coin_id.hex(),
            "launcher_id": self.launcher_id.hex(),
            "amount": self.amount,
            "urls": [url.decode("utf8") for url in self.urls],
            "ours": self.ours,
        }

    @classmethod
    def from_json_dict(cls, json_dict: Dict[str, Any]) -> "Mirror":
        return cls(
            bytes32.from_hexstr(json_dict["coin_id"]),
            bytes32.from_hexstr(json_dict["launcher_id"]),
            json_dict["amount"],
            [bytes(url, "utf8") for url in json_dict["urls"]],
            json_dict["ours"],
        )


@final
class DataLayerWallet:
    if TYPE_CHECKING:
        _protocol_check: ClassVar[WalletProtocol] = cast("DataLayerWallet", None)

    wallet_state_manager: WalletStateManager
    log: logging.Logger
    wallet_info: WalletInfo
    wallet_id: uint8
    standard_wallet: Wallet
    """
    interface used by datalayer for interacting with the chain
    """

    @classmethod
    async def create(
        cls,
        wallet_state_manager: WalletStateManager,
        wallet_info: WalletInfo,
    ) -> DataLayerWallet:
        self = cls()
        self.wallet_state_manager = wallet_state_manager
        self.log = logging.getLogger(__name__)
        self.standard_wallet = wallet_state_manager.main_wallet
        self.wallet_info = wallet_info
        self.wallet_id = uint8(self.wallet_info.id)

        return self

    @classmethod
    def type(cls) -> WalletType:
        return WalletType.DATA_LAYER

    def id(self) -> uint32:
        return self.wallet_info.id

    @classmethod
    async def create_new_dl_wallet(cls, wallet_state_manager: WalletStateManager) -> DataLayerWallet:
        """
        This must be called under the wallet state manager lock
        """

        self = cls()
        self.wallet_state_manager = wallet_state_manager
        self.log = logging.getLogger(__name__)
        self.standard_wallet = wallet_state_manager.main_wallet

        for _, w in self.wallet_state_manager.wallets.items():
            if w.type() == WalletType.DATA_LAYER:
                raise ValueError("DataLayer Wallet already exists for this key")

        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            "DataLayer Wallet",
            WalletType.DATA_LAYER.value,
            "",
        )
        await self.wallet_state_manager.add_new_wallet(self)

        return self

    #############
    # LAUNCHING #
    #############

    @staticmethod
    async def match_dl_launcher(launcher_spend: CoinSpend) -> Tuple[bool, Optional[bytes32]]:
        # Sanity check it's a launcher
        if launcher_spend.puzzle_reveal.to_program() != SINGLETON_LAUNCHER:
            return False, None

        # Let's make sure the solution looks how we expect it to
        try:
            full_puzhash, amount, root, inner_puzhash = launch_solution_to_singleton_info(
                launcher_spend.solution.to_program()
            )
        except ValueError:
            return False, None

        # Now let's check that the full puzzle is an odd data layer singleton
        if (
            full_puzhash
            != create_host_fullpuz(inner_puzhash, root, launcher_spend.coin.name()).get_tree_hash_precalc(inner_puzhash)
            or amount % 2 == 0
        ):
            return False, None

        return True, inner_puzhash

    async def get_launcher_coin_state(self, launcher_id: bytes32, peer: WSChiaConnection) -> CoinState:
        coin_states: List[CoinState] = await self.wallet_state_manager.wallet_node.get_coin_state(
            [launcher_id], peer=peer
        )

        if len(coin_states) == 0:
            raise LauncherCoinNotFoundError(f"Launcher ID {launcher_id} is not a valid coin")
        if coin_states[0].coin.puzzle_hash != SINGLETON_LAUNCHER.get_tree_hash():
            raise ValueError(f"Coin with ID {launcher_id} is not a singleton launcher")
        if coin_states[0].created_height is None:
            raise ValueError(f"Launcher with ID {launcher_id} has not been created (maybe reorged)")
        if coin_states[0].spent_height is None:
            raise ValueError(f"Launcher with ID {launcher_id} has not been spent")

        return coin_states[0]

    # This is the entry point for non-owned singletons
    async def track_new_launcher_id(
        self,
        launcher_id: bytes32,
        peer: WSChiaConnection,
        spend: Optional[CoinSpend] = None,
        height: Optional[uint32] = None,
    ) -> None:
        if await self.wallet_state_manager.dl_store.get_launcher(launcher_id) is not None:
            self.log.info(f"Spend of launcher {launcher_id} has already been processed")
            return None
        if spend is None or height is None:
            launcher_state: CoinState = await self.get_launcher_coin_state(launcher_id, peer)
            spend = await fetch_coin_spend_for_coin_state(launcher_state, peer)
            assert launcher_state.spent_height is not None
            height = uint32(launcher_state.spent_height)

        assert spend.coin.name() == launcher_id, "coin_id should always match the launcher_id here"

        full_puzhash, amount, root, inner_puzhash = launch_solution_to_singleton_info(spend.solution.to_program())
        new_singleton = Coin(launcher_id, full_puzhash, amount)

        singleton_record: Optional[SingletonRecord] = await self.wallet_state_manager.dl_store.get_latest_singleton(
            launcher_id
        )
        if singleton_record is not None:
            if (  # This is an unconfirmed singleton that we know about
                singleton_record.coin_id == new_singleton.name() and not singleton_record.confirmed
            ):
                timestamp = await self.wallet_state_manager.wallet_node.get_timestamp_for_height(height)
                await self.wallet_state_manager.dl_store.set_confirmed(singleton_record.coin_id, height, timestamp)
            else:
                self.log.info(f"Spend of launcher {launcher_id} has already been processed")
                return None
        else:
            timestamp = await self.wallet_state_manager.wallet_node.get_timestamp_for_height(height)
            await self.wallet_state_manager.dl_store.add_singleton_record(
                SingletonRecord(
                    coin_id=new_singleton.name(),
                    launcher_id=launcher_id,
                    root=root,
                    inner_puzzle_hash=inner_puzhash,
                    confirmed=True,
                    confirmed_at_height=height,
                    timestamp=timestamp,
                    lineage_proof=LineageProof(
                        launcher_id,
                        create_host_layer_puzzle(inner_puzhash, root).get_tree_hash_precalc(inner_puzhash),
                        amount,
                    ),
                    generation=uint32(0),
                )
            )

        await self.wallet_state_manager.dl_store.add_launcher(spend.coin)
        await self.wallet_state_manager.add_interested_puzzle_hashes([launcher_id], [self.id()])
        await self.wallet_state_manager.add_interested_coin_ids([new_singleton.name()])

        new_singleton_coin_record: Optional[
            WalletCoinRecord
        ] = await self.wallet_state_manager.coin_store.get_coin_record(new_singleton.name())
        while new_singleton_coin_record is not None and new_singleton_coin_record.spent_block_height > 0:
            # We've already synced this before, so we need to sort of force a resync
            parent_spend = await fetch_coin_spend(new_singleton_coin_record.spent_block_height, new_singleton, peer)
            await self.singleton_removed(parent_spend, new_singleton_coin_record.spent_block_height)
            try:
                additions = compute_additions(parent_spend)
                new_singleton = next(coin for coin in additions if coin.amount % 2 != 0)
                new_singleton_coin_record = await self.wallet_state_manager.coin_store.get_coin_record(
                    new_singleton.name()
                )
            except StopIteration:
                new_singleton_coin_record = None

    ################
    # TRANSACTIONS #
    ################

    async def generate_new_reporter(
        self,
        initial_root: bytes32,
        fee: uint64 = uint64(0),
    ) -> Tuple[TransactionRecord, TransactionRecord, bytes32]:
        """
        Creates the initial singleton, which includes spending an origin coin, the launcher, and creating a singleton
        """

        coins: Set[Coin] = await self.standard_wallet.select_coins(uint64(fee + 1))
        if coins is None:
            raise ValueError("Not enough coins to create new data layer singleton")

        launcher_parent: Coin = list(coins)[0]
        launcher_coin: Coin = Coin(launcher_parent.name(), SINGLETON_LAUNCHER.get_tree_hash(), uint64(1))

        inner_puzzle: Program = await self.standard_wallet.get_new_puzzle()
        full_puzzle: Program = create_host_fullpuz(inner_puzzle, initial_root, launcher_coin.name())

        genesis_launcher_solution: Program = Program.to(
            [full_puzzle.get_tree_hash(), 1, [initial_root, inner_puzzle.get_tree_hash()]]
        )
        announcement_message: bytes32 = genesis_launcher_solution.get_tree_hash()
        announcement = Announcement(launcher_coin.name(), announcement_message)
        create_launcher_tx_record: Optional[TransactionRecord] = await self.standard_wallet.generate_signed_transaction(
            amount=uint64(1),
            puzzle_hash=SINGLETON_LAUNCHER.get_tree_hash(),
            fee=fee,
            origin_id=launcher_parent.name(),
            coins=coins,
            primaries=None,
            ignore_max_send_amount=False,
            coin_announcements_to_consume={announcement},
        )
        assert create_launcher_tx_record is not None and create_launcher_tx_record.spend_bundle is not None

        launcher_cs: CoinSpend = CoinSpend(
            launcher_coin,
            SerializedProgram.from_program(SINGLETON_LAUNCHER),
            SerializedProgram.from_program(genesis_launcher_solution),
        )
        launcher_sb: SpendBundle = SpendBundle([launcher_cs], G2Element())
        full_spend: SpendBundle = SpendBundle.aggregate([create_launcher_tx_record.spend_bundle, launcher_sb])

        # Delete from standard transaction so we don't push duplicate spends
        std_record: TransactionRecord = dataclasses.replace(create_launcher_tx_record, spend_bundle=None)
        dl_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=bytes32([2] * 32),
            amount=uint64(1),
            fee_amount=fee,
            confirmed=False,
            sent=uint32(10),
            spend_bundle=full_spend,
            additions=full_spend.additions(),
            removals=full_spend.removals(),
            memos=list(compute_memos(full_spend).items()),
            wallet_id=uint32(0),  # This is being called before the wallet is created so we're using a temp ID of 0
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.INCOMING_TX.value),
            name=full_spend.name(),
        )
        singleton_record = SingletonRecord(
            coin_id=Coin(launcher_coin.name(), full_puzzle.get_tree_hash(), uint64(1)).name(),
            launcher_id=launcher_coin.name(),
            root=initial_root,
            inner_puzzle_hash=inner_puzzle.get_tree_hash(),
            confirmed=False,
            confirmed_at_height=uint32(0),
            timestamp=uint64(0),
            lineage_proof=LineageProof(
                launcher_coin.name(),
                create_host_layer_puzzle(inner_puzzle, initial_root).get_tree_hash(),
                uint64(1),
            ),
            generation=uint32(0),
        )

        await self.wallet_state_manager.dl_store.add_singleton_record(singleton_record)
        await self.wallet_state_manager.add_interested_puzzle_hashes([singleton_record.launcher_id], [self.id()])

        return dl_record, std_record, launcher_coin.name()

    async def create_tandem_xch_tx(
        self,
        fee: uint64,
        announcement_to_assert: Announcement,
        coin_announcement: bool = True,
    ) -> TransactionRecord:
        chia_tx = await self.standard_wallet.generate_signed_transaction(
            amount=uint64(0),
            puzzle_hash=await self.standard_wallet.get_new_puzzlehash(),
            fee=fee,
            negative_change_allowed=False,
            coin_announcements_to_consume={announcement_to_assert} if coin_announcement else None,
            puzzle_announcements_to_consume=None if coin_announcement else {announcement_to_assert},
        )
        assert chia_tx.spend_bundle is not None
        return chia_tx

    async def create_update_state_spend(
        self,
        launcher_id: bytes32,
        root_hash: Optional[bytes32],
        new_puz_hash: Optional[bytes32] = None,
        new_amount: Optional[uint64] = None,
        fee: uint64 = uint64(0),
        coin_announcements_to_consume: Optional[Set[Announcement]] = None,
        puzzle_announcements_to_consume: Optional[Set[Announcement]] = None,
        sign: bool = True,
        add_pending_singleton: bool = True,
        announce_new_state: bool = False,
    ) -> List[TransactionRecord]:
        singleton_record, parent_lineage = await self.get_spendable_singleton_info(launcher_id)

        if root_hash is None:
            root_hash = singleton_record.root

        inner_puzzle_derivation: Optional[
            DerivationRecord
        ] = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(
            singleton_record.inner_puzzle_hash
        )
        if inner_puzzle_derivation is None:
            raise ValueError(f"DL Wallet does not have permission to update Singleton with launcher ID {launcher_id}")

        # Make the child's puzzles
        if new_puz_hash is None:
            new_puz_hash = (await self.standard_wallet.get_new_puzzle()).get_tree_hash()
        assert new_puz_hash is not None
        next_full_puz_hash: bytes32 = create_host_fullpuz(new_puz_hash, root_hash, launcher_id).get_tree_hash_precalc(
            new_puz_hash
        )

        # Construct the current puzzles
        current_inner_puzzle: Program = self.standard_wallet.puzzle_for_pk(inner_puzzle_derivation.pubkey)
        current_full_puz = create_host_fullpuz(
            current_inner_puzzle,
            singleton_record.root,
            launcher_id,
        )
        assert singleton_record.lineage_proof.parent_name is not None
        assert singleton_record.lineage_proof.amount is not None
        current_coin = Coin(
            singleton_record.lineage_proof.parent_name,
            current_full_puz.get_tree_hash(),
            singleton_record.lineage_proof.amount,
        )

        new_singleton_record = SingletonRecord(
            coin_id=Coin(current_coin.name(), next_full_puz_hash, singleton_record.lineage_proof.amount).name(),
            launcher_id=launcher_id,
            root=root_hash,
            inner_puzzle_hash=new_puz_hash,
            confirmed=False,
            confirmed_at_height=uint32(0),
            timestamp=uint64(0),
            lineage_proof=LineageProof(
                singleton_record.coin_id,
                new_puz_hash,
                singleton_record.lineage_proof.amount,
            ),
            generation=uint32(singleton_record.generation + 1),
        )

        # Optionally add an ephemeral spend to announce
        if announce_new_state:
            announce_only: Program = Program.to(
                (
                    1,
                    [
                        [
                            51,
                            new_puz_hash,
                            singleton_record.lineage_proof.amount,
                            [launcher_id, root_hash, new_puz_hash],
                        ],
                        [62, b"$"],
                    ],
                )
            )
            second_full_puz: Program = create_host_fullpuz(
                announce_only,
                root_hash,
                launcher_id,
            )
            second_coin = Coin(
                current_coin.name(), second_full_puz.get_tree_hash(), singleton_record.lineage_proof.amount
            )
            second_coin_spend = CoinSpend(
                second_coin,
                SerializedProgram.from_program(second_full_puz),
                Program.to(
                    [
                        LineageProof(
                            current_coin.parent_coin_info,
                            create_host_layer_puzzle(current_inner_puzzle, singleton_record.root).get_tree_hash(),
                            singleton_record.lineage_proof.amount,
                        ).to_program(),
                        singleton_record.lineage_proof.amount,
                        [[]],
                    ]
                ),
            )
            root_announce = Announcement(second_full_puz.get_tree_hash(), b"$")
            if puzzle_announcements_to_consume is None:
                puzzle_announcements_to_consume = set((root_announce,))
            else:
                puzzle_announcements_to_consume.add(root_announce)
            second_singleton_record = SingletonRecord(
                coin_id=second_coin.name(),
                launcher_id=launcher_id,
                root=root_hash,
                inner_puzzle_hash=announce_only.get_tree_hash(),
                confirmed=False,
                confirmed_at_height=uint32(0),
                timestamp=uint64(0),
                lineage_proof=LineageProof(
                    second_coin.parent_coin_info,
                    announce_only.get_tree_hash(),
                    singleton_record.lineage_proof.amount,
                ),
                generation=uint32(singleton_record.generation + 1),
            )
            new_singleton_record = dataclasses.replace(
                new_singleton_record,
                coin_id=Coin(second_coin.name(), next_full_puz_hash, singleton_record.lineage_proof.amount).name(),
                lineage_proof=LineageProof(
                    second_coin.name(),
                    next_full_puz_hash,
                    singleton_record.lineage_proof.amount,
                ),
                generation=uint32(second_singleton_record.generation + 1),
            )

        # Create the solution
        primaries = [
            Payment(
                announce_only.get_tree_hash() if announce_new_state else new_puz_hash,
                singleton_record.lineage_proof.amount if new_amount is None else new_amount,
                [
                    launcher_id,
                    root_hash,
                    announce_only.get_tree_hash() if announce_new_state else new_puz_hash,
                ],
            )
        ]
        inner_sol: Program = self.standard_wallet.make_solution(
            primaries=primaries,
            coin_announcements={b"$"} if fee > 0 else None,
            coin_announcements_to_assert={a.name() for a in coin_announcements_to_consume}
            if coin_announcements_to_consume is not None
            else None,
            puzzle_announcements_to_assert={a.name() for a in puzzle_announcements_to_consume}
            if puzzle_announcements_to_consume is not None
            else None,
        )
        if root_hash != singleton_record.root:
            magic_condition = Program.to([-24, ACS_MU, [[Program.to((root_hash, None)), ACS_MU_PH], None]])
            # TODO: This line is a hack, make_solution should allow us to pass extra conditions to it
            inner_sol = Program.to([[], (1, magic_condition.cons(inner_sol.at("rfr"))), []])
        db_layer_sol = Program.to([inner_sol])
        full_sol = Program.to(
            [
                parent_lineage.to_program(),
                singleton_record.lineage_proof.amount,
                db_layer_sol,
            ]
        )

        # Create the spend
        coin_spend = CoinSpend(
            current_coin,
            SerializedProgram.from_program(current_full_puz),
            SerializedProgram.from_program(full_sol),
        )
        await self.standard_wallet.hack_populate_secret_key_for_puzzle_hash(current_inner_puzzle.get_tree_hash())

        if sign:
            spend_bundle = await self.sign(coin_spend)
        else:
            spend_bundle = SpendBundle([coin_spend], G2Element())

        if announce_new_state:
            spend_bundle = dataclasses.replace(spend_bundle, coin_spends=[coin_spend, second_coin_spend])

        dl_tx = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=new_puz_hash,
            amount=uint64(singleton_record.lineage_proof.amount),
            fee_amount=fee,
            confirmed=False,
            sent=uint32(10),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            memos=list(compute_memos(spend_bundle).items()),
            wallet_id=self.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=singleton_record.coin_id,
        )
        assert dl_tx.spend_bundle is not None
        if fee > 0:
            chia_tx = await self.create_tandem_xch_tx(
                fee, Announcement(current_coin.name(), b"$"), coin_announcement=True
            )
            assert chia_tx.spend_bundle is not None
            aggregate_bundle = SpendBundle.aggregate([dl_tx.spend_bundle, chia_tx.spend_bundle])
            dl_tx = dataclasses.replace(dl_tx, spend_bundle=aggregate_bundle)
            chia_tx = dataclasses.replace(chia_tx, spend_bundle=None)
            txs: List[TransactionRecord] = [dl_tx, chia_tx]
        else:
            txs = [dl_tx]

        if add_pending_singleton:
            await self.wallet_state_manager.dl_store.add_singleton_record(
                new_singleton_record,
            )
            if announce_new_state:
                await self.wallet_state_manager.dl_store.add_singleton_record(
                    second_singleton_record,
                )

        return txs

    async def generate_signed_transaction(
        self,
        amounts: List[uint64],
        puzzle_hashes: List[bytes32],
        fee: uint64 = uint64(0),
        coins: Set[Coin] = set(),
        memos: Optional[List[List[bytes]]] = None,  # ignored
        coin_announcements_to_consume: Optional[Set[Announcement]] = None,
        puzzle_announcements_to_consume: Optional[Set[Announcement]] = None,
        ignore_max_send_amount: bool = False,  # ignored
        **kwargs: Unpack[GSTOptionalArgs],
    ) -> List[TransactionRecord]:
        launcher_id: Optional[bytes32] = kwargs.get("launcher_id", None)
        new_root_hash: Optional[bytes32] = kwargs.get("new_root_hash", None)
        sign: bool = kwargs.get(
            "sign", True
        )  # This only prevent signing of THIS wallet's part of the tx (fee will still be signed)
        add_pending_singleton: bool = kwargs.get("add_pending_singleton", True)
        announce_new_state: bool = kwargs.get("announce_new_state", False)
        # Figure out the launcher ID
        if len(coins) == 0:
            if launcher_id is None:
                raise ValueError("Not enough info to know which DL coin to send")
        else:
            if len(coins) != 1:
                raise ValueError("The wallet can only send one DL coin at a time")
            else:
                record = await self.wallet_state_manager.dl_store.get_singleton_record(next(iter(coins)).name())
                if record is None:
                    raise ValueError("The specified coin is not a tracked DL")
                else:
                    launcher_id = record.launcher_id

        if len(amounts) != 1 or len(puzzle_hashes) != 1:
            raise ValueError("The wallet can only send one DL coin to one place at a time")

        return await self.create_update_state_spend(
            launcher_id,
            new_root_hash,
            puzzle_hashes[0],
            amounts[0],
            fee,
            coin_announcements_to_consume,
            puzzle_announcements_to_consume,
            sign,
            add_pending_singleton,
            announce_new_state,
        )

    async def get_spendable_singleton_info(self, launcher_id: bytes32) -> Tuple[SingletonRecord, LineageProof]:
        # First, let's make sure this is a singleton that we track and that we can spend
        singleton_record: Optional[SingletonRecord] = await self.get_latest_singleton(launcher_id)
        if singleton_record is None:
            raise ValueError(f"Singleton with launcher ID {launcher_id} is not tracked by DL Wallet")

        # Next, the singleton should be confirmed or else we shouldn't be ready to spend it
        if not singleton_record.confirmed:
            raise ValueError(f"Singleton with launcher ID {launcher_id} is currently pending")

        # Next, let's verify we have all of the relevant coin information
        if singleton_record.lineage_proof.parent_name is None or singleton_record.lineage_proof.amount is None:
            raise ValueError(f"Singleton with launcher ID {launcher_id} has insufficient information to spend")

        # Finally, let's get the parent record for its lineage proof
        parent_singleton: Optional[SingletonRecord] = await self.wallet_state_manager.dl_store.get_singleton_record(
            singleton_record.lineage_proof.parent_name
        )
        parent_lineage: LineageProof
        if parent_singleton is None:
            if singleton_record.lineage_proof.parent_name != launcher_id:
                raise ValueError(f"Have not found the parent of singleton with launcher ID {launcher_id}")
            else:
                launcher_coin: Optional[Coin] = await self.wallet_state_manager.dl_store.get_launcher(launcher_id)
                if launcher_coin is None:
                    raise ValueError(f"DL Wallet does not have launcher info for id {launcher_id}")
                else:
                    parent_lineage = LineageProof(launcher_coin.parent_coin_info, None, uint64(launcher_coin.amount))
        else:
            parent_lineage = parent_singleton.lineage_proof

        return singleton_record, parent_lineage

    async def get_owned_singletons(self) -> List[SingletonRecord]:
        launcher_ids = await self.wallet_state_manager.dl_store.get_all_launchers()

        collected = []

        for launcher_id in launcher_ids:
            singleton_record = await self.wallet_state_manager.dl_store.get_latest_singleton(launcher_id=launcher_id)
            if singleton_record is None:
                # this is likely due to a race between getting the list and acquiring the extra data
                continue

            inner_puzzle_derivation: Optional[
                DerivationRecord
            ] = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(
                singleton_record.inner_puzzle_hash
            )
            if inner_puzzle_derivation is not None:
                collected.append(singleton_record)

        return collected

    async def create_new_mirror(
        self, launcher_id: bytes32, amount: uint64, urls: List[bytes], fee: uint64 = uint64(0)
    ) -> List[TransactionRecord]:
        create_mirror_tx_record: Optional[TransactionRecord] = await self.standard_wallet.generate_signed_transaction(
            amount=amount,
            puzzle_hash=create_mirror_puzzle().get_tree_hash(),
            fee=fee,
            primaries=[],
            memos=[launcher_id, *(url for url in urls)],
            ignore_max_send_amount=False,
        )
        assert create_mirror_tx_record is not None and create_mirror_tx_record.spend_bundle is not None
        return [create_mirror_tx_record]

    async def delete_mirror(
        self, mirror_id: bytes32, peer: WSChiaConnection, fee: uint64 = uint64(0)
    ) -> List[TransactionRecord]:
        mirror: Mirror = await self.get_mirror(mirror_id)
        mirror_coin: Coin = (await self.wallet_state_manager.wallet_node.get_coin_state([mirror.coin_id], peer=peer))[
            0
        ].coin
        parent_coin: Coin = (
            await self.wallet_state_manager.wallet_node.get_coin_state([mirror_coin.parent_coin_info], peer=peer)
        )[0].coin
        inner_puzzle_derivation: Optional[
            DerivationRecord
        ] = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(parent_coin.puzzle_hash)
        if inner_puzzle_derivation is None:
            raise ValueError(f"DL Wallet does not have permission to delete mirror with ID {mirror_id}")

        await self.standard_wallet.hack_populate_secret_key_for_puzzle_hash(parent_coin.puzzle_hash)

        parent_inner_puzzle: Program = self.standard_wallet.puzzle_for_pk(inner_puzzle_derivation.pubkey)
        new_puzhash: bytes32 = await self.get_new_puzzlehash()
        excess_fee: int = fee - mirror_coin.amount
        inner_sol: Program = self.standard_wallet.make_solution(
            primaries=[Payment(new_puzhash, uint64(mirror_coin.amount - fee))] if excess_fee < 0 else [],
            coin_announcements={b"$"} if excess_fee > 0 else None,
        )
        mirror_spend = CoinSpend(
            mirror_coin,
            SerializedProgram.from_program(create_mirror_puzzle()),
            Program.to(
                [
                    parent_coin.parent_coin_info,
                    parent_inner_puzzle,
                    parent_coin.amount,
                    inner_sol,
                ]
            ),
        )
        mirror_bundle: SpendBundle = await self.sign(mirror_spend)
        txs = [
            TransactionRecord(
                confirmed_at_height=uint32(0),
                created_at_time=uint64(int(time.time())),
                to_puzzle_hash=new_puzhash,
                amount=uint64(mirror_coin.amount),
                fee_amount=fee,
                confirmed=False,
                sent=uint32(10),
                spend_bundle=mirror_bundle,
                additions=mirror_bundle.additions(),
                removals=mirror_bundle.removals(),
                memos=list(compute_memos(mirror_bundle).items()),
                wallet_id=self.id(),  # This is being called before the wallet is created so we're using a temp ID of 0
                sent_to=[],
                trade_id=None,
                type=uint32(TransactionType.OUTGOING_TX.value),
                name=mirror_bundle.name(),
            )
        ]

        if excess_fee > 0:
            chia_tx: TransactionRecord = await self.wallet_state_manager.main_wallet.generate_signed_transaction(
                uint64(1),
                new_puzhash,
                fee=uint64(excess_fee),
                coin_announcements_to_consume={Announcement(mirror_coin.name(), b"$")},
            )
            assert txs[0].spend_bundle is not None
            assert chia_tx.spend_bundle is not None
            txs = [
                dataclasses.replace(
                    txs[0], spend_bundle=SpendBundle.aggregate([txs[0].spend_bundle, chia_tx.spend_bundle])
                ),
                dataclasses.replace(chia_tx, spend_bundle=None),
            ]

        return txs

    ###########
    # SYNCING #
    ###########

    async def coin_added(self, coin: Coin, height: uint32, peer: WSChiaConnection) -> None:
        if coin.puzzle_hash == create_mirror_puzzle().get_tree_hash():
            parent_state: CoinState = (
                await self.wallet_state_manager.wallet_node.get_coin_state([coin.parent_coin_info], peer=peer)
            )[0]
            parent_spend = await fetch_coin_spend(height, parent_state.coin, peer)
            assert parent_spend is not None
            launcher_id, urls = get_mirror_info(
                parent_spend.puzzle_reveal.to_program(), parent_spend.solution.to_program()
            )
            if await self.wallet_state_manager.dl_store.is_launcher_tracked(launcher_id):
                ours: bool = await self.wallet_state_manager.get_wallet_for_coin(coin.parent_coin_info) is not None
                await self.wallet_state_manager.dl_store.add_mirror(
                    Mirror(
                        coin.name(),
                        launcher_id,
                        uint64(coin.amount),
                        urls,
                        ours,
                    )
                )
                await self.wallet_state_manager.add_interested_coin_ids([coin.name()])

    async def singleton_removed(self, parent_spend: CoinSpend, height: uint32) -> None:
        parent_name = parent_spend.coin.name()
        puzzle = parent_spend.puzzle_reveal
        solution = parent_spend.solution

        matched, _ = match_dl_singleton(puzzle.to_program())
        if matched:
            self.log.info(f"DL singleton removed: {parent_spend.coin}")
            singleton_record: Optional[SingletonRecord] = await self.wallet_state_manager.dl_store.get_singleton_record(
                parent_name
            )
            if singleton_record is None:
                self.log.warning(f"DL wallet received coin it does not have parent for. Expected parent {parent_name}.")
                return

            # Information we need to create the singleton record
            full_puzzle_hash: bytes32
            amount: uint64
            root: bytes32
            inner_puzzle_hash: bytes32

            conditions = puzzle.run_with_cost(self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM, solution)[
                1
            ].as_python()
            found_singleton: bool = False
            for condition in conditions:
                if condition[0] == ConditionOpcode.CREATE_COIN and int.from_bytes(condition[2], "big") % 2 == 1:
                    full_puzzle_hash = bytes32(condition[1])
                    amount = uint64(int.from_bytes(condition[2], "big"))
                    try:
                        root = bytes32(condition[3][1])
                        inner_puzzle_hash = bytes32(condition[3][2])
                    except IndexError:
                        self.log.warning(
                            f"Parent {parent_name} with launcher {singleton_record.launcher_id} "
                            "did not hint its child properly"
                        )
                        return
                    found_singleton = True
                    break

            if not found_singleton:
                self.log.warning(f"Singleton with launcher ID {singleton_record.launcher_id} was melted")
                return

            new_singleton = Coin(parent_name, full_puzzle_hash, amount)
            timestamp = await self.wallet_state_manager.wallet_node.get_timestamp_for_height(height)
            await self.wallet_state_manager.dl_store.add_singleton_record(
                SingletonRecord(
                    coin_id=new_singleton.name(),
                    launcher_id=singleton_record.launcher_id,
                    root=root,
                    inner_puzzle_hash=inner_puzzle_hash,
                    confirmed=True,
                    confirmed_at_height=height,
                    timestamp=timestamp,
                    lineage_proof=LineageProof(
                        parent_name,
                        create_host_layer_puzzle(inner_puzzle_hash, root).get_tree_hash_precalc(inner_puzzle_hash),
                        amount,
                    ),
                    generation=uint32(singleton_record.generation + 1),
                )
            )
            await self.wallet_state_manager.add_interested_coin_ids(
                [new_singleton.name()],
            )
            await self.potentially_handle_resubmit(singleton_record.launcher_id)
        elif parent_spend.coin.puzzle_hash == create_mirror_puzzle().get_tree_hash():
            await self.wallet_state_manager.dl_store.delete_mirror(parent_name)

    async def potentially_handle_resubmit(self, launcher_id: bytes32) -> None:
        """
        This method is meant to detect a fork in our expected pending singletons and the singletons that have actually
        been confirmed on chain.  If there is a fork and the root on chain never changed, we will attempt to rebase our
        singletons on to the new latest singleton.  If there is a fork and the root changed, we assume that everything
        has failed and delete any pending state.
        """
        unconfirmed_singletons = await self.wallet_state_manager.dl_store.get_unconfirmed_singletons(launcher_id)
        if len(unconfirmed_singletons) == 0:
            return
        unconfirmed_singletons = sorted(unconfirmed_singletons, key=attrgetter("generation"))
        full_branch: List[SingletonRecord] = await self.wallet_state_manager.dl_store.get_all_singletons_for_launcher(
            launcher_id,
            min_generation=unconfirmed_singletons[0].generation,
        )
        if len(unconfirmed_singletons) == len(full_branch) and set(unconfirmed_singletons) == set(full_branch):
            return

        # Now we have detected a fork so we should check whether the root changed at all
        self.log.info("Attempting automatic rebase")
        parent_name = unconfirmed_singletons[0].lineage_proof.parent_name
        assert parent_name is not None
        parent_singleton = await self.wallet_state_manager.dl_store.get_singleton_record(parent_name)
        if parent_singleton is None or any(parent_singleton.root != s.root for s in full_branch if s.confirmed):
            root_changed: bool = True
        else:
            root_changed = False

        # Regardless of whether the root changed or not, our old state is bad so let's eliminate it
        # First let's find all of our txs matching our unconfirmed singletons
        relevant_dl_txs: List[TransactionRecord] = []
        for singleton in unconfirmed_singletons:
            parent_name = singleton.lineage_proof.parent_name
            if parent_name is None:
                continue

            tx = await self.wallet_state_manager.tx_store.get_transaction_record(parent_name)
            if tx is not None:
                relevant_dl_txs.append(tx)
        # Let's check our standard wallet for fee transactions related to these dl txs
        all_spends: List[SpendBundle] = [tx.spend_bundle for tx in relevant_dl_txs if tx.spend_bundle is not None]
        all_removal_ids: Set[bytes32] = {removal.name() for sb in all_spends for removal in sb.removals()}
        unconfirmed_std_txs: List[
            TransactionRecord
        ] = await self.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(self.standard_wallet.id())
        relevant_std_txs: List[TransactionRecord] = [
            tx for tx in unconfirmed_std_txs if any(c.name() in all_removal_ids for c in tx.removals)
        ]
        # Delete all of the relevant transactions
        for tx in [*relevant_dl_txs, *relevant_std_txs]:
            await self.wallet_state_manager.tx_store.delete_transaction_record(tx.name)
        # Delete all of the unconfirmed singleton records
        for singleton in unconfirmed_singletons:
            await self.wallet_state_manager.dl_store.delete_singleton_record(singleton.coin_id)

        if not root_changed:
            # The root never changed so let's attempt a rebase
            try:
                all_txs: List[TransactionRecord] = []
                for singleton in unconfirmed_singletons:
                    for tx in relevant_dl_txs:
                        if any(c.name() == singleton.coin_id for c in tx.additions):
                            if tx.spend_bundle is not None:
                                fee = uint64(tx.spend_bundle.fees())
                            else:
                                fee = uint64(0)

                            all_txs.extend(
                                await self.create_update_state_spend(
                                    launcher_id,
                                    singleton.root,
                                    fee=fee,
                                )
                            )
                for tx in all_txs:
                    await self.wallet_state_manager.add_pending_transaction(tx)
            except Exception as e:
                self.log.warning(f"Something went wrong during attempted DL resubmit: {str(e)}")
                # Something went wrong so let's delete anything pending that was created
                for singleton in unconfirmed_singletons:
                    await self.wallet_state_manager.dl_store.delete_singleton_record(singleton.coin_id)

    async def stop_tracking_singleton(self, launcher_id: bytes32) -> None:
        await self.wallet_state_manager.dl_store.delete_singleton_records_by_launcher_id(launcher_id)
        await self.wallet_state_manager.dl_store.delete_launcher(launcher_id)

    ###########
    # UTILITY #
    ###########

    async def get_latest_singleton(
        self, launcher_id: bytes32, only_confirmed: bool = False
    ) -> Optional[SingletonRecord]:
        singleton: Optional[SingletonRecord] = await self.wallet_state_manager.dl_store.get_latest_singleton(
            launcher_id, only_confirmed
        )
        return singleton

    async def get_history(
        self,
        launcher_id: bytes32,
        min_generation: Optional[uint32] = None,
        max_generation: Optional[uint32] = None,
        num_results: Optional[uint32] = None,
    ) -> List[SingletonRecord]:
        history: List[SingletonRecord] = await self.wallet_state_manager.dl_store.get_all_singletons_for_launcher(
            launcher_id,
            min_generation,
            max_generation,
            num_results,
        )
        return history

    async def get_singleton_record(self, coin_id: bytes32) -> Optional[SingletonRecord]:
        singleton: Optional[SingletonRecord] = await self.wallet_state_manager.dl_store.get_singleton_record(coin_id)
        return singleton

    async def get_singletons_by_root(self, launcher_id: bytes32, root: bytes32) -> List[SingletonRecord]:
        singletons: List[SingletonRecord] = await self.wallet_state_manager.dl_store.get_singletons_by_root(
            launcher_id, root
        )
        return singletons

    async def get_mirrors_for_launcher(self, launcher_id: bytes32) -> List[Mirror]:
        return await self.wallet_state_manager.dl_store.get_mirrors(launcher_id)

    async def get_mirror(self, coin_id: bytes32) -> Mirror:
        return await self.wallet_state_manager.dl_store.get_mirror(coin_id)

    ##########
    # WALLET #
    ##########

    def require_derivation_paths(self) -> bool:
        return True

    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:
        puzzle: Program = self.puzzle_for_pk(pubkey)
        return puzzle.get_tree_hash()

    def puzzle_for_pk(self, pubkey: G1Element) -> Program:
        return self.standard_wallet.puzzle_for_pk(pubkey)

    async def get_new_puzzle(self) -> Program:
        return self.puzzle_for_pk(
            (await self.wallet_state_manager.get_unused_derivation_record(self.wallet_info.id)).pubkey
        )

    async def get_new_puzzlehash(self) -> bytes32:
        return (await self.get_new_puzzle()).get_tree_hash()

    async def new_peak(self, peak: BlockRecord) -> None:
        pass

    async def get_confirmed_balance(self, record_list: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        return uint128(0)

    async def get_unconfirmed_balance(self, record_list: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        return uint128(0)

    async def get_spendable_balance(self, unspent_records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        return uint128(0)

    async def get_pending_change_balance(self) -> uint64:
        return uint64(0)

    async def get_max_send_amount(self, unspent_records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        return uint128(0)

    async def sign(self, coin_spend: CoinSpend) -> SpendBundle:
        return await sign_coin_spends(
            [coin_spend],
            self.standard_wallet.secret_key_store.secret_key_for_public_key,
            self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA,
            self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM,
        )

    def get_name(self) -> str:
        return self.wallet_info.name

    ##########
    # OFFERS #
    ##########

    async def get_puzzle_info(self, launcher_id: bytes32) -> PuzzleInfo:
        record = await self.get_latest_singleton(launcher_id)
        if record is None:
            raise ValueError(f"DL wallet does not know about launcher ID {launcher_id}")
        return PuzzleInfo(
            {
                "type": AssetType.SINGLETON.value,
                "launcher_id": "0x" + launcher_id.hex(),
                "launcher_ph": "0x" + SINGLETON_LAUNCHER_HASH.hex(),
                "also": {
                    "type": AssetType.METADATA.value,
                    "metadata": f"(0x{record.root} . ())",
                    "updater_hash": "0x" + ACS_MU_PH.hex(),
                },
            }
        )

    async def get_coins_to_offer(self, launcher_id: bytes32, *args: Any, **kwargs: Any) -> Set[Coin]:
        record = await self.get_latest_singleton(launcher_id)
        if record is None:
            raise ValueError(f"DL wallet does not know about launcher ID {launcher_id}")
        puzhash: bytes32 = create_host_fullpuz(
            record.inner_puzzle_hash, record.root, launcher_id
        ).get_tree_hash_precalc(record.inner_puzzle_hash)
        assert record.lineage_proof.parent_name is not None
        assert record.lineage_proof.amount is not None
        return set([Coin(record.lineage_proof.parent_name, puzhash, record.lineage_proof.amount)])

    @staticmethod
    async def make_update_offer(
        wallet_state_manager: Any,
        offer_dict: Dict[Optional[bytes32], int],
        driver_dict: Dict[bytes32, PuzzleInfo],
        solver: Solver,
        fee: uint64 = uint64(0),
    ) -> Offer:
        dl_wallet = None
        for wallet in wallet_state_manager.wallets.values():
            if wallet.type() == WalletType.DATA_LAYER.value:
                dl_wallet = wallet
                break
        if dl_wallet is None:
            raise ValueError("DL Wallet is not initialized")

        offered_launchers: List[bytes32] = [k for k, v in offer_dict.items() if v < 0 and k is not None]
        fee_left_to_pay: uint64 = fee
        all_bundles: List[SpendBundle] = []
        for launcher in offered_launchers:
            try:
                this_solver: Solver = solver[launcher.hex()]
            except KeyError:
                this_solver = solver["0x" + launcher.hex()]
            new_root: bytes32 = this_solver["new_root"]
            new_ph: bytes32 = await wallet_state_manager.main_wallet.get_new_puzzlehash()
            txs: List[TransactionRecord] = await dl_wallet.generate_signed_transaction(
                [uint64(1)],
                [new_ph],
                fee=fee_left_to_pay,
                launcher_id=launcher,
                new_root_hash=new_root,
                sign=False,
                add_pending_singleton=False,
                announce_new_state=True,
            )
            fee_left_to_pay = uint64(0)

            assert txs[0].spend_bundle is not None
            dl_spend: CoinSpend = next(
                cs for cs in txs[0].spend_bundle.coin_spends if match_dl_singleton(cs.puzzle_reveal.to_program())[0]
            )
            all_other_spends: List[CoinSpend] = [cs for cs in txs[0].spend_bundle.coin_spends if cs != dl_spend]
            dl_solution: Program = dl_spend.solution.to_program()
            old_graftroot: Program = dl_solution.at("rrffrf")
            new_graftroot: Program = create_graftroot_offer_puz(
                [bytes32(dep["launcher_id"]) for dep in this_solver["dependencies"]],
                [list(v for v in dep["values_to_prove"]) for dep in this_solver["dependencies"]],
                old_graftroot,
            )

            new_solution: Program = dl_solution.replace(rrffrf=new_graftroot, rrffrrf=Program.to([None] * 5))
            new_spend: CoinSpend = dataclasses.replace(
                dl_spend,
                solution=SerializedProgram.from_program(new_solution),
            )
            signed_bundle = await dl_wallet.sign(new_spend)
            new_bundle: SpendBundle = dataclasses.replace(
                txs[0].spend_bundle,
                coin_spends=all_other_spends,
            )
            all_bundles.append(SpendBundle.aggregate([signed_bundle, new_bundle]))

        # create some dummy requested payments
        requested_payments = {
            k: [NotarizedPayment(bytes32([0] * 32), uint64(v), [], bytes32([0] * 32))]
            for k, v in offer_dict.items()
            if v > 0
        }
        return Offer(requested_payments, SpendBundle.aggregate(all_bundles), driver_dict)

    @staticmethod
    async def finish_graftroot_solutions(offer: Offer, solver: Solver) -> Offer:
        # Build a mapping of launcher IDs to their new innerpuz
        singleton_to_innerpuzhash: Dict[bytes32, bytes32] = {}
        singleton_to_root: Dict[bytes32, bytes32] = {}
        all_parent_ids: List[bytes32] = [cs.coin.parent_coin_info for cs in offer.coin_spends()]
        for spend in offer.coin_spends():
            matched, curried_args = match_dl_singleton(spend.puzzle_reveal.to_program())
            if matched and spend.coin.name() not in all_parent_ids:
                innerpuz, root, launcher_id = curried_args
                singleton_struct = launcher_to_struct(bytes32(launcher_id.as_python())).get_tree_hash()
                singleton_to_root[singleton_struct] = bytes32(root.as_python())
                singleton_to_innerpuzhash[singleton_struct] = innerpuz.get_tree_hash()

        # Create all of the new solutions
        new_spends: List[CoinSpend] = []
        for spend in offer.coin_spends():
            solution = spend.solution.to_program()
            if match_dl_singleton(spend.puzzle_reveal.to_program())[0]:
                try:
                    graftroot: Program = solution.at("rrffrf")
                except EvalError:
                    new_spends.append(spend)
                    continue
                mod, curried_args = graftroot.uncurry()
                if mod == GRAFTROOT_DL_OFFERS:
                    _, singleton_structs, _, values_to_prove = curried_args.as_iter()
                    all_proofs = []
                    roots = []
                    for singleton, values in zip(singleton_structs.as_iter(), values_to_prove.as_python()):
                        asserted_root: Optional[str] = None
                        proofs_of_inclusion = []
                        for value in values:
                            for proof_of_inclusion in solver["proofs_of_inclusion"]:
                                root = proof_of_inclusion[0]
                                proof: Tuple[int, List[bytes32]] = (proof_of_inclusion[1], proof_of_inclusion[2])
                                calculated_root: bytes32 = _simplify_merkle_proof(value, proof)
                                if (
                                    calculated_root == bytes32.from_hexstr(root)
                                    and calculated_root == singleton_to_root[singleton.get_tree_hash()]
                                ):
                                    proofs_of_inclusion.append(proof)
                                    if asserted_root is None:
                                        asserted_root = root
                                    elif asserted_root != root:
                                        raise ValueError("Malformed DL offer")
                                    break
                        roots.append(asserted_root)
                        all_proofs.append(proofs_of_inclusion)
                    if sum(len(proofs) for proofs in all_proofs) < sum(1 for _ in values_to_prove.as_iter()):
                        raise ValueError("One or more proofs of inclusion were invalid")
                    new_solution: Program = solution.replace(
                        rrffrrf=Program.to(
                            [
                                all_proofs,
                                [Program.to((bytes32.from_hexstr(root), None)) for root in roots if root is not None],
                                [ACS_MU_PH] * len(all_proofs),
                                [
                                    singleton_to_innerpuzhash[struct.get_tree_hash()]
                                    for struct in singleton_structs.as_iter()
                                ],
                                solution.at("rrffrrfrrrrf"),
                            ]
                        )
                    )
                    new_spend: CoinSpend = dataclasses.replace(
                        spend,
                        solution=SerializedProgram.from_program(new_solution),
                    )
                    spend = new_spend
            new_spends.append(spend)

        return Offer({}, SpendBundle(new_spends, offer.aggregated_signature()), offer.driver_dict)

    @staticmethod
    async def get_offer_summary(offer: Offer) -> Dict[str, Any]:
        summary: Dict[str, Any] = {"offered": []}
        for spend in offer.coin_spends():
            solution = spend.solution.to_program()
            matched, curried_args = match_dl_singleton(spend.puzzle_reveal.to_program())
            if matched:
                try:
                    graftroot: Program = solution.at("rrffrf")
                except EvalError:
                    continue
                mod, graftroot_curried_args = graftroot.uncurry()
                if mod == GRAFTROOT_DL_OFFERS:
                    child_spend: CoinSpend = next(
                        cs for cs in offer.coin_spends() if cs.coin.parent_coin_info == spend.coin.name()
                    )
                    _, child_curried_args = match_dl_singleton(child_spend.puzzle_reveal.to_program())
                    singleton_summary = {
                        "launcher_id": list(curried_args)[2].as_python().hex(),
                        "new_root": list(child_curried_args)[1].as_python().hex(),
                        "dependencies": [],
                    }
                    _, singleton_structs, _, values_to_prove = graftroot_curried_args.as_iter()
                    for struct, values in zip(singleton_structs.as_iter(), values_to_prove.as_iter()):
                        singleton_summary["dependencies"].append(
                            {
                                "launcher_id": struct.at("rf").as_python().hex(),
                                "values_to_prove": [value.as_python().hex() for value in values.as_iter()],
                            }
                        )
                    summary["offered"].append(singleton_summary)
        return summary

    async def select_coins(
        self,
        amount: uint64,
        exclude: Optional[List[Coin]] = None,
        min_coin_amount: Optional[uint64] = None,
        max_coin_amount: Optional[uint64] = None,
        excluded_coin_amounts: Optional[List[uint64]] = None,
    ) -> Set[Coin]:
        raise RuntimeError("DataLayerWallet does not support select_coins()")


def verify_offer(
    maker: Tuple[StoreProofs, ...],
    taker: Tuple[OfferStore, ...],
    summary: Dict[str, Any],
) -> None:
    # TODO: consistency in error messages
    # TODO: custom exceptions
    # TODO: show data in errors?
    # TODO: collect and report all failures
    # TODO: review for case coverage (and test those cases)

    if len({store_proof.store_id for store_proof in maker}) != len(maker):
        raise OfferIntegrityError("maker: repeated store id")

    for store_proof in maker:
        proofs: List[ProofOfInclusion] = []
        for reference_proof in store_proof.proofs:
            proof = ProofOfInclusion(
                node_hash=reference_proof.node_hash,
                layers=[
                    ProofOfInclusionLayer(
                        other_hash_side=layer.other_hash_side,
                        other_hash=layer.other_hash,
                        combined_hash=layer.combined_hash,
                    )
                    for layer in reference_proof.layers
                ],
            )

            proofs.append(proof)

            if leaf_hash(key=reference_proof.key, value=reference_proof.value) != proof.node_hash:
                raise OfferIntegrityError("maker: node hash does not match key and value")

            if not proof.valid():
                raise OfferIntegrityError("maker: invalid proof of inclusion found")

        # TODO: verify each kv hash to the proof's node hash
        roots = {proof.root_hash for proof in proofs}
        if len(roots) > 1:
            raise OfferIntegrityError("maker: multiple roots referenced for a single store id")
        if len(roots) < 1:
            raise OfferIntegrityError("maker: no roots referenced for store id")

    # TODO: what about validating duplicate entries are consistent?
    maker_from_offer = {
        bytes32.from_hexstr(offered["launcher_id"]): bytes32.from_hexstr(offered["new_root"])
        for offered in summary["offered"]
    }

    maker_from_reference = {
        # verified above that there is at least one proof and all combined hashes match
        store_proof.store_id: store_proof.proofs[0].root()
        for store_proof in maker
    }

    if maker_from_offer != maker_from_reference:
        raise OfferIntegrityError("maker: offered stores and their roots do not match the reference data")

    taker_from_offer = {
        bytes32.from_hexstr(dependency["launcher_id"]): [
            bytes32.from_hexstr(value) for value in dependency["values_to_prove"]
        ]
        for offered in summary["offered"]
        for dependency in offered["dependencies"]
    }

    taker_from_reference = {
        store.store_id: [leaf_hash(key=inclusion.key, value=inclusion.value) for inclusion in store.inclusions]
        for store in taker
    }

    if taker_from_offer != taker_from_reference:
        raise OfferIntegrityError("taker: reference and offer inclusions do not match")
