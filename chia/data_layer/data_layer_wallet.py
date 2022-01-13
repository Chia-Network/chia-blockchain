import logging
import os
import json
import time
import dataclasses
from typing import Any, Optional, Tuple, Set, List, Dict, Type, TypeVar

from blspy import G2Element, AugSchemeMPL

from chia.consensus.block_record import BlockRecord
from chia.protocols.wallet_protocol import PuzzleSolutionResponse
from chia.wallet.db_wallet.db_wallet_puzzles import (
    create_host_fullpuz,
    SINGLETON_LAUNCHER,
    create_host_layer_puzzle,
    create_singleton_fullpuz,
)
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint8, uint32, uint64, uint128
from secrets import token_bytes
from chia.util.streamable import Streamable, streamable
from chia.wallet.sign_coin_spends import sign_coin_spends
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.transaction_record import ItemAndTransactionRecords
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
    lineage_proof: Optional[LineageProof]


_T_DataLayerWallet = TypeVar("_T_DataLayerWallet", bound="DataLayerWallet")


class DataLayerWallet:
    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    standard_wallet: Wallet
    """
    interface used by datalayer for interacting with the chain
    """

    @classmethod
    def type(cls) -> uint8:
        return uint8(WalletType.DATA_LAYER)

    def id(self) -> uint32:
        return self.wallet_info.id

    # todo remove
    async def create_data_store(self, name: str = "") -> bytes32:
        tree_id = bytes32.from_bytes(os.urandom(32))
        return tree_id

    @classmethod
    async def create_new_dl_wallet(
        cls: Type[_T_DataLayerWallet],
        wallet_state_manager: Any,
        wallet: Wallet,
        name: Optional[str] = "DataLayer Wallet",
    ) -> ItemAndTransactionRecords[_T_DataLayerWallet]:
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
        self.wallet_id = self.wallet_info.id

        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id)

        return self

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
            confirmed_at_height=uint64(0),
            lineage_proof=LineageProof(
                launcher_coin.name(),
                create_host_layer_puzzle(inner_puzzle.get_tree_hash(), initial_root).get_tree_hash(),
                1,
            ),
        )

        await self.wallet_state_manager.dl_store.add_singleton_record(singleton_record, False)
        await self.wallet_state_manager.add_interested_puzzle_hash(singleton_record.launcher_id, self.id())
        await self.wallet_state_manager.add_interested_puzzle_hash(full_puzzle.get_tree_hash(), self.id())

        return dl_record, std_record, launcher_coin.name()

    async def get_spendable_singleton_records(self, launcher_id: bytes32) -> Tuple[SingletonRecord, SingletonRecord]:
        # First, let's make sure this is a singleton that we track and that we can spend
        singleton_record: Optional[SingletonRecord] = await self.get_latest_singleton(launcher_id)
        if singleton_record is None:
            raise ValueError(f"Singleton with launcher ID {launcher_id} is not tracked by DL Wallet")

        # Next, let's verify we have all of the relevant coin information
        if (
            singleton_record.lineage_proof is None
            or singleton_record.lineage_proof.parent_coin_info is None
            or singleton_record.lineage_proof.amount is None
        ):
            raise ValueError(f"Singleton with launcher ID {launcher_id} has insufficient information to spend")

        # Finally, let's get the parent record for its lineage proof
        parent_singleton: Optional[SingletonRecord] = await self.wallet_state_manager.dl_store.get_singleton_record(
            singleton_record.lineage_proof.parent_coin_info
        )
        if parent_singleton is None or parent_singleton.lineage_proof is None:
            raise ValueError(f"Have not found the parent of singleton with launcher ID {launcher_id}")

        return singleton_record, parent_singleton

    async def create_update_state_spend(
        self,
        launcher_id: bytes32,
        root_hash: bytes32,
    ) -> TransactionRecord:

        singleton_record, parent_singleton = await self.get_spendable_singleton_records(launcher_id)

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
        primaries: List[AmountWithPuzzlehash] = [
            {
                "puzzlehash": new_db_layer_puzzle.get_tree_hash(),
                "amount": singleton_record.lineage_proof.amount,
                "memos": [launcher_id, root_hash, inner_puzzle_hash],
            }
        ]
        inner_sol: Program = self.standard_wallet.make_solution(primaries=primaries)
        db_layer_sol = Program.to([0, inner_sol, current_inner_puzzle])
        full_sol = Program.to(
            [
                parent_singleton.lineage_proof.to_program(),
                singleton_record.lineage_proof.amount,
                db_layer_sol,
            ]
        )

        # Create the spend
        current_coin = Coin(
            singleton_record.lineage_proof.parent_coin_info,
            current_full_puz.get_tree_hash(),
            singleton_record.lineage_proof.amount,
        )
        coin_spend = CoinSpend(
            current_coin,
            SerializedProgram.from_program(current_full_puz),
            SerializedProgram.from_program(full_sol),
        )
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
            confirmed=False,
            confirmed_at_height=uint32(0),
            lineage_proof=LineageProof(
                singleton_record.coin_id,
                next_inner_puzzle.get_tree_hash(),
                singleton_record.lineage_proof.amount,
            ),
        )
        await self.wallet_state_manager.dl_store.add_singleton_record(new_singleton_record)
        return dl_record

    async def create_report_spend(self, launcher_id: bytes32) -> Tuple[TransactionRecord, Announcement]:
        singleton_record, parent_singleton = await self.get_spendable_singleton_records(launcher_id)

        # Create the puzzle
        current_full_puz = create_host_fullpuz(
            singleton_record.inner_puzzle_hash,
            singleton_record.root,
            launcher_id,
        )

        # Create the solution
        db_layer_sol = Program.to(
            [
                1,
                (  # (my_puzhash . my_amount)
                    current_full_puz.get_tree_hash(),
                    singleton_record.lineage_proof.amount,
                ),
            ]
        )
        full_sol = Program.to(
            [
                parent_singleton.lineage_proof.to_program(),
                singleton_record.lineage_proof.amount,
                db_layer_sol,
            ]
        )

        # Create the spend
        current_coin = Coin(
            parent_singleton.coin_id, current_full_puz.get_tree_hash(), singleton_record.lineage_proof.amount
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
            lineage_proof=LineageProof(
                singleton_record.coin_id,
                create_host_layer_puzzle(
                    singleton_record.inner_puzzle_hash,
                    singleton_record.root,
                ).get_tree_hash(),
                singleton_record.lineage_proof.amount,
            ),
        )
        await self.wallet_state_manager.dl_store.add_singleton_record(new_singleton_record)
        return dl_record, Announcement(current_full_puz.get_tree_hash(), singleton_record.root)

    async def get_info_for_offer_claim(
        self,
        launcher_id: bytes32,
    ) -> Tuple[Program, Optional[Program], bytes32]:
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

    async def coin_added(self, coin: Coin, height: uint32):
        """Notification from wallet state manager that coin has been received."""
        self.log.info(f"DL wallet has been notified that {coin} was added")

        existing_singleton_records: List[
            SingletonRecord
        ] = await self.wallet_state_manager.dl_store.get_all_singletons_for_launcher(coin.parent_coin_info)
        if len(existing_singleton_records) > 0:
            if len(existing_singleton_records) > 1:
                self.log.warning(f"Unexpected singleton received for launcher id {coin.parent_coin_info}")
                return
            elif len(existing_singleton_records) == 1:
                await self.wallet_state_manager.dl_store.set_confirmed(existing_singleton_records[0].coin_id, height)
        else:
            data: Dict[str, Any] = {
                "data": {
                    "action_data": {
                        "api_name": "request_puzzle_solution",
                        "height": height,
                        "coin_name": coin.parent_coin_info,
                        "received_coin": coin.name(),
                    }
                }
            }

            data_str = dict_to_json_str(data)
            await self.wallet_state_manager.create_action(
                name="request_puzzle_solution",
                wallet_id=self.id(),
                wallet_type=self.type(),
                callback="puzzle_solution_received",
                done=False,
                data=data_str,
                in_transaction=True,
            )

    async def puzzle_solution_received(self, response: PuzzleSolutionResponse, action_id: int) -> None:
        coin_name = response.coin_name
        puzzle: Program = response.puzzle
        solution: Program = response.solution

        matched, curried_args = match_dl_singleton(puzzle)
        if matched:
            singleton_record: Optional[SingletonRecord] = await self.wallet_state_manager.dl_store.get_singleton_record(
                coin_name
            )
            if singleton_record is None:
                self.log.warning(f"DL wallet received a coin it does not have parent for. Expected parent {coin_name}.")
                return

            # Information we need to create the singleton record
            root: bytes32
            inner_puzzle_hash: bytes32
            full_puzzle_hash: bytes32
            amount: uint64

            conditions = puzzle.run(solution).as_python()
            found_singleton: bool = False
            for condition in conditions:
                if condition[0] == ConditionOpcode.CREATE_COIN and condition[2] % 2 == 1:
                    try:
                        root = bytes32(condition[3][1])
                        inner_puzzle_hash = bytes32(condition[3][1])
                        full_puzzle_hash = bytes32(condition[1])
                        amount = uint64(condition[2])
                        break
                    except IndexError:
                        self.log.warning(
                            f"Parent {coin_name} with launcher {singleton_record.launcher_id} "
                            "did not hint its child properly"
                        )
                        return

            await self.add_singleton_record(
                SingletonRecord(
                    coin_id=Coin(coin_name, full_puzzle_hash, amount).name(),
                    launcher_id=singleton_record.launcher_id,
                    root=root,
                    confirmed=True,
                    confirmed_at_height=uint32(response.height),
                    lineage_proof=LineageProof(
                        coin_name,
                        create_host_layer_puzzle(inner_puzzle_hash, root).get_tree_hash(),
                        amount,
                    ),
                )
            )

    async def get_latest_singleton(self, launcher_id: bytes32) -> Optional[SingletonRecord]:
        return await self.wallet_state_manager.dl_store.get_latest_singleton(launcher_id)

    async def get_history(self, launcher_id: bytes32) -> List[SingletonRecord]:
        return await self.wallet_state_manager.dl_store.get_all_singletons_for_launcher(launcher_id)

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

    async def sign(self, coin_spend: CoinSpend) -> SpendBundle:
        # async def pk_to_sk(pk: G1Element) -> PrivateKey:
        #     owner_sk: Optional[PrivateKey] = await find_owner_sk([self.wallet_state_manager.private_key], pk)
        #     assert owner_sk is not None
        #     return owner_sk

        return await sign_coin_spends(
            [coin_spend],
            self.standard_wallet.secret_key_store.secret_key_for_public_key,
            self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA,
            self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM,
        )
