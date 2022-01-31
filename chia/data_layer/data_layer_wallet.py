import logging
import json
import time
import dataclasses
from typing import Any, Optional, Tuple, Set, List, Dict, Type, TypeVar

from blspy import G2Element

from chia.consensus.block_record import BlockRecord
from chia.protocols.wallet_protocol import PuzzleSolutionResponse, CoinState
from chia.server.outbound_message import NodeType
from chia.wallet.db_wallet.db_wallet_puzzles import (
    create_host_fullpuz,
    SINGLETON_LAUNCHER,
    create_host_layer_puzzle,
    launch_solution_to_singleton_info,
    match_dl_singleton,
)
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.json_util import dict_to_json_str
from chia.util.streamable import Streamable, streamable
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.sign_coin_spends import sign_coin_spends
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import AmountWithPuzzlehash, WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_info import WalletInfo


@dataclasses.dataclass(frozen=True)
@streamable
class SingletonRecord(Streamable):
    coin_id: bytes32
    launcher_id: bytes32
    root: bytes32
    inner_puzzle_hash: bytes32
    confirmed: bool
    confirmed_at_height: uint32
    lineage_proof: LineageProof
    generation: uint32


_T_DataLayerWallet = TypeVar("_T_DataLayerWallet", bound="DataLayerWallet")


class DataLayerWallet:
    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    wallet_id: uint8
    standard_wallet: Wallet
    """
    interface used by datalayer for interacting with the chain
    """

    @classmethod
    async def create(
        cls: Type[_T_DataLayerWallet],
        wallet_state_manager: Any,
        wallet: Wallet,
        wallet_info: WalletInfo,
        name: Optional[str] = None,
    ) -> _T_DataLayerWallet:
        self = cls()
        self.wallet_state_manager = wallet_state_manager
        self.log = logging.getLogger(name if name else __name__)
        self.standard_wallet = wallet
        self.wallet_info = wallet_info
        self.wallet_id = uint8(self.wallet_info.id)

        return self

    @classmethod
    def type(cls) -> uint8:
        return uint8(WalletType.DATA_LAYER)

    def id(self) -> uint32:
        return self.wallet_info.id

    @classmethod
    async def create_new_dl_wallet(
        cls: Type[_T_DataLayerWallet],
        wallet_state_manager: Any,
        wallet: Wallet,
        name: Optional[str] = "DataLayer Wallet",
    ) -> _T_DataLayerWallet:
        """
        This must be called under the wallet state manager lock
        """

        self = cls()
        self.wallet_state_manager = wallet_state_manager
        self.log = logging.getLogger(name if name else __name__)
        self.standard_wallet = wallet

        for _, wallet in self.wallet_state_manager.wallets.items():
            if wallet.type() == uint8(WalletType.DATA_LAYER):
                raise ValueError("DataLayer Wallet already exists for this key")

        self.wallet_info = await wallet_state_manager.user_store.create_wallet(name, WalletType.DATA_LAYER.value, "")
        if self.wallet_info is None:
            raise ValueError("Internal Error")
        self.wallet_id = uint8(self.wallet_info.id)

        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id)

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
            full_puzhash != create_host_fullpuz(inner_puzhash, root, launcher_spend.coin.name()).get_tree_hash()
            or amount % 2 == 0
        ):
            return False, None

        return True, inner_puzhash

    async def get_launcher_coin_state(self, launcher_id: bytes32) -> CoinState:
        coin_states: List[CoinState] = await self.wallet_state_manager.get_coin_state([launcher_id])

        if len(coin_states) == 0:
            raise ValueError(f"Launcher ID {launcher_id} is not a valid coin")
        if coin_states[0].coin.puzzle_hash != SINGLETON_LAUNCHER.get_tree_hash():
            raise ValueError(f"Coin with ID {launcher_id} is not a singleton launcher")
        if coin_states[0].created_height is None:
            raise ValueError(f"Launcher with ID {launcher_id} has not been created (maybe reorged)")
        if coin_states[0].spent_height is None:
            raise ValueError(f"Launcher with ID {launcher_id} has not been spent")

        return coin_states[0]

    async def track_new_launcher_id(  # This is the entry point for non-owned singletons
        self,
        launcher_id: bytes32,
        spend: Optional[CoinSpend] = None,
        height: Optional[uint32] = None,
        in_transaction: bool = False,
    ) -> None:
        if spend is not None and spend.coin.name() == launcher_id:  # spend.coin.name() == launcher_id is a sanity check
            await self.new_launcher_spend(spend, height, in_transaction)
        else:
            launcher_state: CoinState = await self.get_launcher_coin_state(launcher_id)

            data: Dict[str, Any] = {
                "data": {
                    "action_data": {
                        "api_name": "request_puzzle_solution",
                        "height": launcher_state.spent_height,
                        "coin_name": launcher_id,
                        "launcher_coin": {
                            "parent_id": launcher_state.coin.parent_coin_info.hex(),
                            "puzzle_hash": launcher_state.coin.puzzle_hash.hex(),
                            "amount": str(launcher_state.coin.amount),
                        },
                    }
                }
            }

            data_str = dict_to_json_str(data)
            await self.wallet_state_manager.create_action(
                name="request_puzzle_solution",
                wallet_id=self.id(),
                wallet_type=self.type(),
                callback="new_launcher_spend_response",
                done=False,
                data=data_str,
                in_transaction=False,  # We should never be fetching this during sync, it will provide us with the spend
            )

    async def new_launcher_spend_response(self, response: PuzzleSolutionResponse, action_id: int) -> None:
        action = await self.wallet_state_manager.action_store.get_wallet_action(action_id)
        coin_dict = json.loads(action.data)["data"]["action_data"]["launcher_coin"]
        launcher_coin = Coin(
            bytes32.from_hexstr(coin_dict["parent_id"]),
            bytes32.from_hexstr(coin_dict["puzzle_hash"]),
            uint64(int(coin_dict["amount"])),
        )
        await self.new_launcher_spend(
            CoinSpend(launcher_coin, response.puzzle, response.solution),
            height=response.height,
        )

    async def new_launcher_spend(
        self,
        launcher_spend: CoinSpend,
        height: Optional[uint32] = None,
        in_transaction: bool = False,
    ) -> None:
        launcher_id: bytes32 = launcher_spend.coin.name()
        if height is None:
            height = (await self.get_launcher_coin_state(launcher_id)).spent_height
            assert height is not None

        full_puzhash, amount, root, inner_puzhash = launch_solution_to_singleton_info(
            launcher_spend.solution.to_program()
        )
        new_singleton = Coin(launcher_id, full_puzhash, amount)

        singleton_record: Optional[SingletonRecord] = await self.wallet_state_manager.dl_store.get_latest_singleton(
            launcher_id
        )
        if singleton_record is not None:
            if (  # This is an unconfirmed singleton that we know about
                singleton_record.coin_id == new_singleton.name() and not singleton_record.confirmed
            ):
                await self.wallet_state_manager.dl_store.set_confirmed(singleton_record.coin_id, height)
            else:
                self.log.info(f"Spend of launcher {launcher_id} has already been processed")
        else:
            await self.wallet_state_manager.dl_store.add_singleton_record(
                SingletonRecord(
                    coin_id=new_singleton.name(),
                    launcher_id=launcher_id,
                    root=root,
                    inner_puzzle_hash=inner_puzhash,
                    confirmed=True,
                    confirmed_at_height=height,
                    lineage_proof=LineageProof(
                        launcher_id,
                        create_host_layer_puzzle(inner_puzhash, root).get_tree_hash(),
                        amount,
                    ),
                    generation=uint32(0),
                ),
                in_transaction,
            )

        await self.wallet_state_manager.dl_store.add_launcher(launcher_spend.coin, in_transaction)
        await self.wallet_state_manager.add_interested_puzzle_hash(launcher_id, self.id(), in_transaction)
        await self.wallet_state_manager.coin_store.add_coin_record(
            WalletCoinRecord(
                new_singleton,
                height,
                uint32(0),
                False,
                False,
                WalletType(self.type()),
                self.id(),
            )
        )

        # TODO
        # Below is some out of place sync code
        # We don't currently have the ability to process coins in the past that have hinted to us
        # We need to validate these states after receiving them too
        all_coin_states: Set[CoinState] = set()

        # First we need to make sure we have all of the coin states
        puzzle_hashes_to_search_for: Set[bytes32] = set({launcher_id})
        while len(puzzle_hashes_to_search_for) != 0:
            coin_states: List[CoinState] = await self.wallet_state_manager.wallet_node.get_coins_with_puzzle_hash(
                [launcher_id, new_singleton.puzzle_hash]
            )
            state_set = set(
                filter(lambda cs: cs.coin.puzzle_hash != launcher_id, coin_states)
            )  # Sanity check for troublemakers
            all_coin_states.update(state_set)
            puzzle_hashes_to_search_for = set()
            all_coin_ids: Set[bytes32] = {cs.coin.name() for cs in all_coin_states}
            all_coin_ids.update({launcher_id})
            for state in coin_states:
                if state.coin.parent_coin_info not in all_coin_ids:
                    puzzle_hashes_to_search_for.add(state.coin.puzzle_hash)

        # Force them all to be noticed (len will be zero for newly created singletons, this is only for existing ones)
        if len(all_coin_states) > 0:
            # Select a peer for fetching puzzles
            all_nodes = self.wallet_state_manager.wallet_node.server.connection_by_type[NodeType.FULL_NODE]
            if len(all_nodes.keys()) == 0:
                raise ValueError("Not connected to the full node")
            peer = list(all_nodes.values())[0]

            # Sync the singleton history
            previous_coin_id: bytes32 = launcher_id
            while True:
                next_coin_state: CoinState = list(
                    filter(lambda cs: cs.coin.parent_coin_info == previous_coin_id, all_coin_states)
                )[0]
                if next_coin_state.spent_height is None:
                    break
                else:
                    cs: CoinSpend = await self.wallet_state_manager.wallet_node.fetch_puzzle_solution(
                        peer, next_coin_state.spent_height, next_coin_state.coin
                    )
                    await self.singleton_removed(cs, next_coin_state.spent_height)
                    previous_coin_id = next_coin_state.coin.name()

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
        full_puzzle: Program = create_host_fullpuz(inner_puzzle.get_tree_hash(), initial_root, launcher_coin.name())

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
            memos=list(full_spend.get_memos().items()),
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
            lineage_proof=LineageProof(
                launcher_coin.name(),
                create_host_layer_puzzle(inner_puzzle.get_tree_hash(), initial_root).get_tree_hash(),
                uint64(1),
            ),
            generation=uint32(0),
        )

        await self.wallet_state_manager.dl_store.add_singleton_record(singleton_record, False)
        await self.wallet_state_manager.add_interested_puzzle_hash(singleton_record.launcher_id, self.id(), False)

        return dl_record, std_record, launcher_coin.name()

    async def create_update_state_spend(
        self,
        launcher_id: bytes32,
        root_hash: bytes32,
    ) -> TransactionRecord:
        singleton_record, parent_lineage = await self.get_spendable_singleton_info(launcher_id)

        inner_puzzle_derivation: Optional[
            DerivationRecord
        ] = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(
            singleton_record.inner_puzzle_hash
        )
        if inner_puzzle_derivation is None:
            raise ValueError(f"DL Wallet does not have permission to update Singleton with launcher ID {launcher_id}")

        # Make the child's puzzles
        next_inner_puzzle: Program = await self.standard_wallet.get_new_puzzle()
        next_db_layer_puzzle: Program = create_host_layer_puzzle(next_inner_puzzle.get_tree_hash(), root_hash)
        next_full_puz = create_host_fullpuz(next_inner_puzzle.get_tree_hash(), root_hash, launcher_id)

        # Construct the current puzzles
        current_inner_puzzle: Program = self.standard_wallet.puzzle_for_pk(inner_puzzle_derivation.pubkey)
        current_full_puz = create_host_fullpuz(
            current_inner_puzzle.get_tree_hash(),
            singleton_record.root,
            launcher_id,
        )

        # Make the solution to the current coin
        assert singleton_record.lineage_proof.parent_name is not None
        assert singleton_record.lineage_proof.amount is not None
        primaries: List[AmountWithPuzzlehash] = [
            {
                "puzzlehash": next_db_layer_puzzle.get_tree_hash(),
                "amount": singleton_record.lineage_proof.amount,
                "memos": [launcher_id, root_hash, next_inner_puzzle.get_tree_hash()],
            }
        ]
        inner_sol: Program = self.standard_wallet.make_solution(primaries=primaries)
        db_layer_sol = Program.to([0, inner_sol, current_inner_puzzle])
        full_sol = Program.to(
            [
                parent_lineage.to_program(),
                singleton_record.lineage_proof.amount,
                db_layer_sol,
            ]
        )

        # Create the spend
        current_coin = Coin(
            singleton_record.lineage_proof.parent_name,
            current_full_puz.get_tree_hash(),
            singleton_record.lineage_proof.amount,
        )
        coin_spend = CoinSpend(
            current_coin,
            SerializedProgram.from_program(current_full_puz),
            SerializedProgram.from_program(full_sol),
        )
        await self.standard_wallet.hack_populate_secret_key_for_puzzle_hash(current_inner_puzzle.get_tree_hash())
        spend_bundle = await self.sign(coin_spend)

        dl_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=next_inner_puzzle.get_tree_hash(),
            amount=uint64(singleton_record.lineage_proof.amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(10),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            memos=list(spend_bundle.get_memos().items()),
            wallet_id=self.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=singleton_record.coin_id,
        )
        new_singleton_record = SingletonRecord(
            coin_id=Coin(
                current_coin.name(), next_full_puz.get_tree_hash(), singleton_record.lineage_proof.amount
            ).name(),
            launcher_id=launcher_id,
            root=root_hash,
            inner_puzzle_hash=next_inner_puzzle.get_tree_hash(),
            confirmed=False,
            confirmed_at_height=uint32(0),
            lineage_proof=LineageProof(
                singleton_record.coin_id,
                next_inner_puzzle.get_tree_hash(),
                singleton_record.lineage_proof.amount,
            ),
            generation=uint32(singleton_record.generation + 1),
        )
        await self.wallet_state_manager.dl_store.add_singleton_record(new_singleton_record, False)
        return dl_record

    async def create_report_spend(self, launcher_id: bytes32) -> Tuple[TransactionRecord, Announcement]:
        singleton_record, parent_lineage = await self.get_spendable_singleton_info(launcher_id)

        # Create the puzzle
        current_full_puz = create_host_fullpuz(
            singleton_record.inner_puzzle_hash,
            singleton_record.root,
            launcher_id,
        )

        # Create the solution
        assert singleton_record.lineage_proof.parent_name is not None
        assert singleton_record.lineage_proof.amount is not None
        db_layer_sol = Program.to([1, singleton_record.lineage_proof.amount, []])
        full_sol = Program.to(
            [
                parent_lineage.to_program(),
                singleton_record.lineage_proof.amount,
                db_layer_sol,
            ]
        )

        # Create the spend
        current_coin = Coin(
            singleton_record.lineage_proof.parent_name,
            current_full_puz.get_tree_hash(),
            singleton_record.lineage_proof.amount,
        )
        coin_spend = CoinSpend(
            current_coin,
            SerializedProgram.from_program(current_full_puz),
            SerializedProgram.from_program(full_sol),
        )
        spend_bundle = SpendBundle([coin_spend], G2Element())

        # Create the relevant records
        dl_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=singleton_record.inner_puzzle_hash,
            amount=uint64(singleton_record.lineage_proof.amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(10),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            memos=list(spend_bundle.get_memos().items()),
            wallet_id=self.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=singleton_record.coin_id,
        )
        new_singleton_record = SingletonRecord(
            coin_id=Coin(
                current_coin.name(), current_full_puz.get_tree_hash(), singleton_record.lineage_proof.amount
            ).name(),
            launcher_id=launcher_id,
            root=singleton_record.root,
            confirmed=False,
            confirmed_at_height=uint32(0),
            inner_puzzle_hash=singleton_record.inner_puzzle_hash,
            lineage_proof=LineageProof(
                singleton_record.coin_id,
                create_host_layer_puzzle(
                    singleton_record.inner_puzzle_hash,
                    singleton_record.root,
                ).get_tree_hash(),
                singleton_record.lineage_proof.amount,
            ),
            generation=uint32(singleton_record.generation + 1),
        )
        await self.wallet_state_manager.dl_store.add_singleton_record(new_singleton_record, False)
        return dl_record, Announcement(current_full_puz.get_tree_hash(), singleton_record.root)

    async def get_spendable_singleton_info(self, launcher_id: bytes32) -> Tuple[SingletonRecord, LineageProof]:
        # First, let's make sure this is a singleton that we track and that we can spend
        singleton_record: Optional[SingletonRecord] = await self.get_latest_singleton(launcher_id)
        if singleton_record is None:
            raise ValueError(f"Singleton with launcher ID {launcher_id} is not tracked by DL Wallet")

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
                    parent_lineage = LineageProof(launcher_coin.parent_coin_info, None, launcher_coin.amount)
        else:
            parent_lineage = parent_singleton.lineage_proof

        return singleton_record, parent_lineage

    ###########
    # SYNCING #
    ###########

    async def singleton_removed(self, parent_spend: CoinSpend, height: uint32) -> None:
        parent_name = parent_spend.coin.name()
        puzzle: Program = parent_spend.puzzle_reveal.to_program()
        solution: Program = parent_spend.solution.to_program()

        matched, curried_args = match_dl_singleton(puzzle)
        if matched:
            singleton_record: Optional[SingletonRecord] = await self.wallet_state_manager.dl_store.get_singleton_record(
                parent_name
            )
            if singleton_record is None:
                self.log.warning(f"DL wallet received coin it does not have parent for. Expected parent {parent_name}.")
                return

            # First let's create the singleton's full puz to check if it's the same (report spend)
            current_full_puz: Program = create_host_fullpuz(
                singleton_record.inner_puzzle_hash,
                singleton_record.root,
                singleton_record.launcher_id,
            )

            # Information we need to create the singleton record
            full_puzzle_hash: bytes32
            amount: uint64
            root: bytes32
            inner_puzzle_hash: bytes32

            conditions = puzzle.run(solution).as_python()
            found_singleton: bool = False
            for condition in conditions:
                if condition[0] == ConditionOpcode.CREATE_COIN and int.from_bytes(condition[2], "big") % 2 == 1:
                    full_puzzle_hash = bytes32(condition[1])
                    amount = uint64(int.from_bytes(condition[2], "big"))
                    if current_full_puz.get_tree_hash() == full_puzzle_hash:
                        root = singleton_record.root
                        inner_puzzle_hash = singleton_record.inner_puzzle_hash
                    else:
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
            await self.wallet_state_manager.dl_store.add_singleton_record(
                SingletonRecord(
                    coin_id=new_singleton.name(),
                    launcher_id=singleton_record.launcher_id,
                    root=root,
                    inner_puzzle_hash=inner_puzzle_hash,
                    confirmed=True,
                    confirmed_at_height=height,
                    lineage_proof=LineageProof(
                        parent_name,
                        create_host_layer_puzzle(inner_puzzle_hash, root).get_tree_hash(),
                        amount,
                    ),
                    generation=uint32(singleton_record.generation + 1),
                ),
                True,
            )
            await self.wallet_state_manager.coin_store.add_coin_record(
                WalletCoinRecord(
                    new_singleton,
                    height,
                    uint32(0),
                    False,
                    False,
                    WalletType(self.type()),
                    self.id(),
                )
            )

    async def stop_tracking_singleton(self, launcher_id: bytes32) -> None:
        await self.wallet_state_manager.dl_store.delete_singleton_records_by_launcher_id(launcher_id)
        await self.wallet_state_manager.dl_store.delete_launcher(launcher_id)

    #############
    # DL OFFERS #
    #############

    async def get_info_for_offer_claim(
        self,
        launcher_id: bytes32,
    ) -> Tuple[Program, bytes32, bytes32]:
        singleton_record: Optional[SingletonRecord] = await self.get_latest_singleton(launcher_id)
        if singleton_record is None:
            raise ValueError(f"Singleton with launcher ID {launcher_id} is not tracked by DL Wallet")
        elif not singleton_record.confirmed:
            raise ValueError(f"Singleton with launcher ID {launcher_id} is in an unconfirmed state")

        current_full_puz = create_host_fullpuz(
            singleton_record.inner_puzzle_hash,
            singleton_record.root,
            launcher_id,
        )
        return current_full_puz, singleton_record.inner_puzzle_hash, singleton_record.root

    ###########
    # UTILITY #
    ###########

    async def get_latest_singleton(self, launcher_id: bytes32) -> Optional[SingletonRecord]:
        singleton: Optional[SingletonRecord] = await self.wallet_state_manager.dl_store.get_latest_singleton(
            launcher_id
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

    ##########
    # WALLET #
    ##########

    def puzzle_for_pk(self, pubkey: bytes) -> Program:
        return self.standard_wallet.puzzle_for_pk(pubkey)

    async def get_new_puzzle(self) -> Program:
        return self.puzzle_for_pk(
            bytes((await self.wallet_state_manager.get_unused_derivation_record(self.wallet_info.id)).pubkey)
        )

    async def new_peak(self, peak: BlockRecord) -> None:
        pass

    async def get_confirmed_balance(self, record_list: Optional[Set[WalletCoinRecord]] = None) -> uint64:
        return uint64(0)

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
