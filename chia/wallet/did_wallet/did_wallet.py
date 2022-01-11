import logging
import time
import json

from typing import Dict, Optional, List, Any, Set, Tuple
from blspy import AugSchemeMPL, G1Element
from secrets import token_bytes
from chia.protocols import wallet_protocol
from chia.protocols.wallet_protocol import CoinState
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint64, uint32, uint8
from chia.wallet.util.transaction_type import TransactionType

from chia.wallet.did_wallet.did_info import DIDInfo
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.did_wallet import did_wallet_puzzles
from chia.wallet.derive_keys import master_sk_to_wallet_sk_unhardened


class DIDWallet:
    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    did_info: DIDInfo
    standard_wallet: Wallet
    base_puzzle_program: Optional[bytes]
    base_inner_puzzle_hash: Optional[bytes32]
    wallet_id: int

    @staticmethod
    async def create_new_did_wallet(
        wallet_state_manager: Any,
        wallet: Wallet,
        amount: uint64,
        backups_ids: List = [],
        num_of_backup_ids_needed: uint64 = None,
        name: str = None,
    ):
        """
        This must be called under the wallet state manager lock
        """
        self = DIDWallet()
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        self.standard_wallet = wallet
        self.log = logging.getLogger(name if name else __name__)
        std_wallet_id = self.standard_wallet.wallet_id
        bal = await wallet_state_manager.get_confirmed_balance_for_wallet_already_locked(std_wallet_id)
        if amount > bal:
            raise ValueError("Not enough balance")
        if amount & 1 == 0:
            raise ValueError("DID amount must be odd number")
        self.wallet_state_manager = wallet_state_manager
        if num_of_backup_ids_needed is None:
            num_of_backup_ids_needed = uint64(len(backups_ids))
        if num_of_backup_ids_needed > len(backups_ids):
            raise ValueError("Cannot require more IDs than are known.")
        self.did_info = DIDInfo(None, backups_ids, num_of_backup_ids_needed, [], None, None, None, None, False)
        info_as_string = json.dumps(self.did_info.to_json_dict())
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            "DID Wallet", WalletType.DISTRIBUTED_ID.value, info_as_string
        )
        if self.wallet_info is None:
            raise ValueError("Internal Error")
        self.wallet_id = self.wallet_info.id
        std_wallet_id = self.standard_wallet.wallet_id
        bal = await wallet_state_manager.get_confirmed_balance_for_wallet_already_locked(std_wallet_id)
        if amount > bal:
            raise ValueError("Not enough balance")

        try:
            spend_bundle = await self.generate_new_decentralised_id(uint64(amount))
        except Exception:
            await wallet_state_manager.user_store.delete_wallet(self.id(), False)
            raise

        if spend_bundle is None:
            await wallet_state_manager.user_store.delete_wallet(self.id(), False)
            raise ValueError("Failed to create spend.")
        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id)
        assert self.did_info.origin_coin is not None
        assert self.did_info.current_inner is not None
        did_puzzle_hash = did_wallet_puzzles.create_fullpuz(
            self.did_info.current_inner, self.did_info.origin_coin.name()
        ).get_tree_hash()

        did_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=did_puzzle_hash,
            amount=uint64(amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(10),
            spend_bundle=None,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.INCOMING_TX.value),
            name=bytes32(token_bytes()),
            memos=[],
        )
        regular_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=did_puzzle_hash,
            amount=uint64(amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.wallet_state_manager.main_wallet.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=bytes32(token_bytes()),
            memos=list(spend_bundle.get_memos().items()),
        )
        await self.standard_wallet.push_transaction(regular_record)
        await self.standard_wallet.push_transaction(did_record)
        return self

    @staticmethod
    async def create_new_did_wallet_from_recovery(
        wallet_state_manager: Any,
        wallet: Wallet,
        filename: str,
        name: str = None,
    ):
        self = DIDWallet()
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        self.standard_wallet = wallet
        self.log = logging.getLogger(name if name else __name__)
        self.wallet_state_manager = wallet_state_manager
        self.did_info = DIDInfo(None, [], uint64(0), [], None, None, None, None, False)
        info_as_string = json.dumps(self.did_info.to_json_dict())
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            "DID Wallet", WalletType.DISTRIBUTED_ID.value, info_as_string
        )
        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id)
        # load backup will also set our DIDInfo
        await self.load_backup(filename)

        if self.wallet_info is None:
            raise ValueError("Internal Error")
        self.wallet_id = self.wallet_info.id
        return self

    @staticmethod
    async def create(
        wallet_state_manager: Any,
        wallet: Wallet,
        wallet_info: WalletInfo,
        name: str = None,
    ):
        self = DIDWallet()
        self.log = logging.getLogger(name if name else __name__)
        self.wallet_state_manager = wallet_state_manager
        self.wallet_info = wallet_info
        self.wallet_id = wallet_info.id
        self.standard_wallet = wallet
        self.wallet_info = wallet_info
        self.did_info = DIDInfo.from_json_dict(json.loads(wallet_info.data))
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        return self

    @classmethod
    def type(cls) -> uint8:
        return uint8(WalletType.DISTRIBUTED_ID)

    def id(self):
        return self.wallet_info.id

    async def get_confirmed_balance(self, record_list=None) -> uint64:
        if record_list is None:
            record_list = await self.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(self.id())

        amount: uint64 = uint64(0)
        for record in record_list:
            parent = self.get_parent_for_coin(record.coin)
            if parent is not None:
                amount = uint64(amount + record.coin.amount)

        self.log.info(f"Confirmed balance for did wallet is {amount}")
        return uint64(amount)

    async def get_pending_change_balance(self) -> uint64:
        unconfirmed_tx = await self.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(self.id())
        addition_amount = 0

        for record in unconfirmed_tx:
            our_spend = False
            for coin in record.removals:
                if await self.wallet_state_manager.does_coin_belong_to_wallet(coin, self.id()):
                    our_spend = True
                    break

            if our_spend is not True:
                continue

            for coin in record.additions:
                if await self.wallet_state_manager.does_coin_belong_to_wallet(coin, self.id()):
                    addition_amount += coin.amount

        return uint64(addition_amount)

    async def get_unconfirmed_balance(self, record_list=None) -> uint64:
        confirmed = await self.get_confirmed_balance(record_list)
        return await self.wallet_state_manager._get_unconfirmed_balance(self.id(), confirmed)

    async def select_coins(self, amount, exclude: List[Coin] = None) -> Optional[Set[Coin]]:
        """Returns a set of coins that can be used for generating a new transaction."""
        if exclude is None:
            exclude = []

        spendable_amount = await self.get_spendable_balance()
        if amount > spendable_amount:
            self.log.warning(f"Can't select {amount}, from spendable {spendable_amount} for wallet id {self.id()}")
            return None

        self.log.info(f"About to select coins for amount {amount}")
        unspent: List[WalletCoinRecord] = list(
            await self.wallet_state_manager.get_spendable_coins_for_wallet(self.wallet_info.id)
        )
        sum_value = 0
        used_coins: Set = set()

        # Use older coins first
        unspent.sort(key=lambda r: r.confirmed_block_height)

        # Try to use coins from the store, if there isn't enough of "unused"
        # coins use change coins that are not confirmed yet
        unconfirmed_removals: Dict[bytes32, Coin] = await self.wallet_state_manager.unconfirmed_removals_for_wallet(
            self.wallet_info.id
        )
        for coinrecord in unspent:
            if sum_value >= amount and len(used_coins) > 0:
                break
            if coinrecord.coin.name() in unconfirmed_removals:
                continue
            if coinrecord.coin in exclude:
                continue
            sum_value += coinrecord.coin.amount
            used_coins.add(coinrecord.coin)

        # This happens when we couldn't use one of the coins because it's already used
        # but unconfirmed, and we are waiting for the change. (unconfirmed_additions)
        if sum_value < amount:
            raise ValueError(
                "Can't make this transaction at the moment. Waiting for the change from the previous transaction."
            )

        self.log.info(f"Successfully selected coins: {used_coins}")
        return used_coins

    # This will be used in the recovery case where we don't have the parent info already
    async def coin_added(self, coin: Coin, _: uint32):
        """Notification from wallet state manager that wallet has been received."""
        self.log.info(f"DID wallet has been notified that coin was added: {coin.name()}:{coin}")
        inner_puzzle = await self.inner_puzzle_for_did_puzzle(coin.puzzle_hash)
        if self.did_info.temp_coin is not None:
            self.wallet_state_manager.state_changed("did_coin_added", self.wallet_info.id)
        new_info = DIDInfo(
            self.did_info.origin_coin,
            self.did_info.backup_ids,
            self.did_info.num_of_backup_ids_needed,
            self.did_info.parent_info,
            inner_puzzle,
            None,
            None,
            None,
            False,
        )
        await self.save_info(new_info, True)

        future_parent = LineageProof(
            coin.parent_coin_info,
            inner_puzzle.get_tree_hash(),
            coin.amount,
        )

        await self.add_parent(coin.name(), future_parent, True)
        parent = self.get_parent_for_coin(coin)
        if parent is None:
            parent_state: CoinState = (
                await self.wallet_state_manager.wallet_node.get_coin_state([coin.parent_coin_info])
            )[0]
            node = self.wallet_state_manager.wallet_node.get_full_node_peer()
            assert parent_state.spent_height is not None
            puzzle_solution_request = wallet_protocol.RequestPuzzleSolution(
                coin.parent_coin_info, parent_state.spent_height
            )
            response = await node.request_puzzle_solution(puzzle_solution_request)
            req_puz_sol = response.response
            assert req_puz_sol.puzzle is not None
            parent_innerpuz = did_wallet_puzzles.get_innerpuzzle_from_puzzle(req_puz_sol.puzzle)
            assert parent_innerpuz is not None
            parent_info = LineageProof(
                parent_state.coin.parent_coin_info,
                parent_innerpuz.get_tree_hash(),
                parent_state.coin.amount,
            )
            await self.add_parent(coin.parent_coin_info, parent_info, False)

    def create_backup(self, filename: str):
        assert self.did_info.current_inner is not None
        assert self.did_info.origin_coin is not None
        try:
            f = open(filename, "w")
            output_str = f"{self.did_info.origin_coin.parent_coin_info}:"
            output_str += f"{self.did_info.origin_coin.puzzle_hash}:"
            output_str += f"{self.did_info.origin_coin.amount}:"
            for did in self.did_info.backup_ids:
                output_str = output_str + did.hex() + ","
            output_str = output_str[:-1]
            output_str = (
                output_str + f":{bytes(self.did_info.current_inner).hex()}:{self.did_info.num_of_backup_ids_needed}"
            )
            f.write(output_str)
            f.close()
        except Exception as e:
            raise e
        return None

    async def load_backup(self, filename: str):
        try:
            f = open(filename, "r")
            details = f.readline().split(":")
            f.close()
            origin = Coin(
                bytes32.fromhex(details[0]),
                bytes32.fromhex(details[1]),
                uint64(int(details[2])),
            )
            backup_ids = []
            for d in details[3].split(","):
                backup_ids.append(bytes.fromhex(d))
            num_of_backup_ids_needed = uint64(int(details[5]))
            if num_of_backup_ids_needed > len(backup_ids):
                raise Exception
            innerpuz: Program = Program.from_bytes(bytes.fromhex(details[4]))
            did_info: DIDInfo = DIDInfo(
                origin,
                backup_ids,
                num_of_backup_ids_needed,
                self.did_info.parent_info,
                innerpuz,
                None,
                None,
                None,
                False,
            )
            await self.save_info(did_info, False)
            await self.wallet_state_manager.update_wallet_puzzle_hashes(self.wallet_info.id)

            # full_puz = did_wallet_puzzles.create_fullpuz(innerpuz, origin.name())
            # All additions in this block here:
            new_puzhash = await self.get_new_inner_hash()
            new_pubkey = bytes(
                (await self.wallet_state_manager.get_unused_derivation_record(self.wallet_info.id)).pubkey
            )
            parent_info = None

            node = self.wallet_state_manager.wallet_node.get_full_node_peer()
            children = await self.wallet_state_manager.wallet_node.fetch_children(node, origin.name())
            while True:
                if len(children) == 0:
                    break

                children_state: CoinState = children[0]
                coin = children_state.coin
                name = coin.name()
                children = await self.wallet_state_manager.wallet_node.fetch_children(node, name)
                future_parent = LineageProof(
                    coin.parent_coin_info,
                    innerpuz.get_tree_hash(),
                    coin.amount,
                )
                await self.add_parent(coin.name(), future_parent, False)
                if children_state.spent_height != children_state.created_height:
                    did_info = DIDInfo(
                        origin,
                        backup_ids,
                        num_of_backup_ids_needed,
                        self.did_info.parent_info,
                        innerpuz,
                        coin,
                        new_puzhash,
                        new_pubkey,
                        False,
                    )
                    await self.save_info(did_info, False)
                    assert children_state.created_height
                    puzzle_solution_request = wallet_protocol.RequestPuzzleSolution(
                        coin.parent_coin_info, children_state.created_height
                    )
                    parent_state: CoinState = (
                        await self.wallet_state_manager.wallet_node.get_coin_state([coin.parent_coin_info])
                    )[0]
                    response = await node.request_puzzle_solution(puzzle_solution_request)
                    req_puz_sol = response.response
                    assert req_puz_sol.puzzle is not None
                    parent_innerpuz = did_wallet_puzzles.get_innerpuzzle_from_puzzle(req_puz_sol.puzzle)
                    assert parent_innerpuz is not None
                    parent_info = LineageProof(
                        parent_state.coin.parent_coin_info,
                        parent_innerpuz.get_tree_hash(),
                        parent_state.coin.amount,
                    )
                    await self.add_parent(coin.parent_coin_info, parent_info, False)
            assert parent_info is not None
            return None
        except Exception as e:
            raise e

    def puzzle_for_pk(self, pubkey: bytes) -> Program:
        innerpuz = did_wallet_puzzles.create_innerpuz(
            pubkey, self.did_info.backup_ids, self.did_info.num_of_backup_ids_needed
        )
        if self.did_info.origin_coin is not None:
            return did_wallet_puzzles.create_fullpuz(innerpuz, self.did_info.origin_coin.name())
        else:
            # TODO: address hint error and remove ignore
            #       error: Argument 2 to "create_fullpuz" has incompatible type "int"; expected "bytes32"  [arg-type]
            return did_wallet_puzzles.create_fullpuz(innerpuz, 0x00)  # type: ignore[arg-type]

    async def get_new_puzzle(self) -> Program:
        return self.puzzle_for_pk(
            bytes((await self.wallet_state_manager.get_unused_derivation_record(self.wallet_info.id)).pubkey)
        )

    def get_my_DID(self) -> str:
        assert self.did_info.origin_coin is not None
        core = self.did_info.origin_coin.name()
        assert core is not None
        return core.hex()

    async def create_update_spend(self):
        assert self.did_info.current_inner is not None
        assert self.did_info.origin_coin is not None
        coins = await self.select_coins(1)
        assert coins is not None
        coin = coins.pop()
        new_puzhash = await self.get_new_inner_hash()
        # innerpuz solution is (mode amount messages new_puz)
        innersol: Program = Program.to([1, coin.amount, [], new_puzhash])
        # full solution is (corehash parent_info my_amount innerpuz_reveal solution)
        innerpuz: Program = self.did_info.current_inner

        full_puzzle: Program = did_wallet_puzzles.create_fullpuz(
            innerpuz,
            self.did_info.origin_coin.name(),
        )
        parent_info = self.get_parent_for_coin(coin)
        assert parent_info is not None
        fullsol = Program.to(
            [
                [
                    parent_info.parent_name,
                    parent_info.inner_puzzle_hash,
                    parent_info.amount,
                ],
                coin.amount,
                innersol,
            ]
        )
        list_of_solutions = [CoinSpend(coin, full_puzzle, fullsol)]
        # sign for AGG_SIG_ME
        message = (
            Program.to([new_puzhash, coin.amount, []]).get_tree_hash()
            + coin.name()
            + self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA
        )
        pubkey = did_wallet_puzzles.get_pubkey_from_innerpuz(innerpuz)
        index = await self.wallet_state_manager.puzzle_store.index_for_pubkey(pubkey)
        private = master_sk_to_wallet_sk_unhardened(self.wallet_state_manager.private_key, index)
        signature = AugSchemeMPL.sign(private, message)
        # assert signature.validate([signature.PkMessagePair(pubkey, message)])
        sigs = [signature]
        aggsig = AugSchemeMPL.aggregate(sigs)
        spend_bundle = SpendBundle(list_of_solutions, aggsig)

        did_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=new_puzhash,
            amount=uint64(coin.amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.wallet_info.id,
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=token_bytes(),
            memos=list(spend_bundle.get_memos().items()),
        )
        await self.standard_wallet.push_transaction(did_record)
        return spend_bundle

    # The message spend can send messages and also change your innerpuz
    async def create_message_spend(self, messages: List[Tuple[int, bytes]], new_innerpuzhash: Optional[bytes32] = None):
        assert self.did_info.current_inner is not None
        assert self.did_info.origin_coin is not None
        coins = await self.select_coins(1)
        assert coins is not None
        coin = coins.pop()
        innerpuz: Program = self.did_info.current_inner
        if new_innerpuzhash is None:
            new_innerpuzhash = innerpuz.get_tree_hash()
        # innerpuz solution is (mode amount messages new_puz)
        innersol: Program = Program.to([1, coin.amount, messages, new_innerpuzhash])
        # full solution is (corehash parent_info my_amount innerpuz_reveal solution)

        full_puzzle: Program = did_wallet_puzzles.create_fullpuz(
            innerpuz,
            self.did_info.origin_coin.name(),
        )
        parent_info = self.get_parent_for_coin(coin)
        assert parent_info is not None
        fullsol = Program.to(
            [
                [
                    parent_info.parent_name,
                    parent_info.inner_puzzle_hash,
                    parent_info.amount,
                ],
                coin.amount,
                innersol,
            ]
        )
        list_of_solutions = [CoinSpend(coin, full_puzzle, fullsol)]
        # sign for AGG_SIG_ME
        # new_inner_puzhash amount message
        message = (
            Program.to([new_innerpuzhash, coin.amount, messages]).get_tree_hash()
            + coin.name()
            + self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA
        )
        pubkey = did_wallet_puzzles.get_pubkey_from_innerpuz(innerpuz)
        index = await self.wallet_state_manager.puzzle_store.index_for_pubkey(pubkey)
        private = master_sk_to_wallet_sk_unhardened(self.wallet_state_manager.private_key, index)
        signature = AugSchemeMPL.sign(private, message)
        # assert signature.validate([signature.PkMessagePair(pubkey, message)])
        sigs = [signature]
        aggsig = AugSchemeMPL.aggregate(sigs)
        spend_bundle = SpendBundle(list_of_solutions, aggsig)

        did_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=new_innerpuzhash,
            amount=uint64(coin.amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.wallet_info.id,
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=bytes32(token_bytes()),
            memos=list(spend_bundle.get_memos().items()),
        )
        await self.standard_wallet.push_transaction(did_record)
        return spend_bundle

    # This is used to cash out, or update the id_list
    async def create_exit_spend(self, puzhash: bytes32):
        assert self.did_info.current_inner is not None
        assert self.did_info.origin_coin is not None
        coins = await self.select_coins(1)
        assert coins is not None
        coin = coins.pop()
        amount = coin.amount - 1
        # innerpuz solution is (mode amount new_puzhash)
        innersol: Program = Program.to([0, amount, puzhash])
        # full solution is (corehash parent_info my_amount innerpuz_reveal solution)
        innerpuz: Program = self.did_info.current_inner

        full_puzzle: Program = did_wallet_puzzles.create_fullpuz(
            innerpuz,
            self.did_info.origin_coin.name(),
        )
        parent_info = self.get_parent_for_coin(coin)
        assert parent_info is not None
        fullsol = Program.to(
            [
                [
                    parent_info.parent_name,
                    parent_info.inner_puzzle_hash,
                    parent_info.amount,
                ],
                coin.amount,
                innersol,
            ]
        )
        list_of_solutions = [CoinSpend(coin, full_puzzle, fullsol)]
        # sign for AGG_SIG_ME
        message = (
            Program.to([amount, puzhash]).get_tree_hash()
            + coin.name()
            + self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA
        )
        pubkey = did_wallet_puzzles.get_pubkey_from_innerpuz(innerpuz)
        index = await self.wallet_state_manager.puzzle_store.index_for_pubkey(pubkey)
        private = master_sk_to_wallet_sk_unhardened(self.wallet_state_manager.private_key, index)
        signature = AugSchemeMPL.sign(private, message)
        # assert signature.validate([signature.PkMessagePair(pubkey, message)])
        sigs = [signature]
        aggsig = AugSchemeMPL.aggregate(sigs)
        spend_bundle = SpendBundle(list_of_solutions, aggsig)

        did_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=puzhash,
            amount=uint64(coin.amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.wallet_info.id,
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=bytes32(token_bytes()),
            memos=list(spend_bundle.get_memos().items()),
        )
        await self.standard_wallet.push_transaction(did_record)
        return spend_bundle

    # Pushes the a SpendBundle to create a message coin on the blockchain
    # Returns a SpendBundle for the recoverer to spend the message coin
    async def create_attestment(
        self, recovering_coin_name: bytes32, newpuz: bytes32, pubkey: G1Element, filename=None
    ) -> SpendBundle:
        assert self.did_info.current_inner is not None
        assert self.did_info.origin_coin is not None
        coins = await self.select_coins(1)
        assert coins is not None and coins != set()
        coin = coins.pop()
        message = did_wallet_puzzles.create_recovery_message_puzzle(recovering_coin_name, newpuz, pubkey)
        innermessage = message.get_tree_hash()
        innerpuz: Program = self.did_info.current_inner
        # innerpuz solution is (mode, amount, message, new_inner_puzhash)
        messages = [(0, innermessage)]
        innersol = Program.to([1, coin.amount, messages, innerpuz.get_tree_hash()])

        # full solution is (corehash parent_info my_amount innerpuz_reveal solution)
        full_puzzle: Program = did_wallet_puzzles.create_fullpuz(
            innerpuz,
            self.did_info.origin_coin.name(),
        )
        parent_info = self.get_parent_for_coin(coin)
        assert parent_info is not None

        fullsol = Program.to(
            [
                [
                    parent_info.parent_name,
                    parent_info.inner_puzzle_hash,
                    parent_info.amount,
                ],
                coin.amount,
                innersol,
            ]
        )
        list_of_solutions = [CoinSpend(coin, full_puzzle, fullsol)]
        message_spend = did_wallet_puzzles.create_spend_for_message(coin.name(), recovering_coin_name, newpuz, pubkey)
        message_spend_bundle = SpendBundle([message_spend], AugSchemeMPL.aggregate([]))
        # sign for AGG_SIG_ME
        to_sign = Program.to([innerpuz.get_tree_hash(), coin.amount, messages]).get_tree_hash()
        message = to_sign + coin.name() + self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA
        pubkey = did_wallet_puzzles.get_pubkey_from_innerpuz(innerpuz)
        index = await self.wallet_state_manager.puzzle_store.index_for_pubkey(pubkey)
        private = master_sk_to_wallet_sk_unhardened(self.wallet_state_manager.private_key, index)
        signature = AugSchemeMPL.sign(private, message)
        # assert signature.validate([signature.PkMessagePair(pubkey, message)])
        spend_bundle = SpendBundle(list_of_solutions, signature)
        did_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=coin.puzzle_hash,
            amount=uint64(coin.amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.wallet_info.id,
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.INCOMING_TX.value),
            name=bytes32(token_bytes()),
            memos=list(spend_bundle.get_memos().items()),
        )
        await self.standard_wallet.push_transaction(did_record)
        if filename is not None:
            f = open(filename, "w")
            f.write(self.get_my_DID())
            f.write(":")
            f.write(bytes(message_spend_bundle).hex())
            f.write(":")
            parent = coin.parent_coin_info.hex()
            innerpuzhash = self.did_info.current_inner.get_tree_hash().hex()
            amount = coin.amount
            f.write(parent)
            f.write(":")
            f.write(innerpuzhash)
            f.write(":")
            f.write(str(amount))
            f.close()
        return message_spend_bundle

    # this is just for testing purposes, API should use create_attestment_now
    async def get_info_for_recovery(self):
        coins = await self.select_coins(1)
        coin = coins.pop()
        parent = coin.parent_coin_info
        innerpuzhash = self.did_info.current_inner.get_tree_hash()
        amount = coin.amount
        return [parent, innerpuzhash, amount]

    async def load_attest_files_for_recovery_spend(self, filenames):
        spend_bundle_list = []
        info_dict = {}
        try:
            for i in filenames:
                f = open(i)
                info = f.read().split(":")
                info_dict[info[0]] = [
                    bytes.fromhex(info[2]),
                    bytes.fromhex(info[3]),
                    uint64(info[4]),
                ]

                new_sb = SpendBundle.from_bytes(bytes.fromhex(info[1]))
                spend_bundle_list.append(new_sb)
                f.close()
            # info_dict {0xidentity: "(0xparent_info 0xinnerpuz amount)"}
            my_recovery_list: List[bytes] = self.did_info.backup_ids

            # convert info dict into recovery list - same order as wallet
            info_list = []
            for entry in my_recovery_list:
                if entry.hex() in info_dict:
                    info_list.append(
                        [
                            info_dict[entry.hex()][0],
                            info_dict[entry.hex()][1],
                            info_dict[entry.hex()][2],
                        ]
                    )
                else:
                    info_list.append([])
            message_spend_bundle = SpendBundle.aggregate(spend_bundle_list)
            return info_list, message_spend_bundle
        except Exception:
            raise

    async def recovery_spend(
        self,
        coin: Coin,
        puzhash: bytes32,
        parent_innerpuzhash_amounts_for_recovery_ids: List[Tuple[bytes, bytes, int]],
        pubkey: G1Element,
        spend_bundle: SpendBundle,
    ) -> SpendBundle:
        assert self.did_info.origin_coin is not None

        # innersol is mode new_amount message new_inner_puzhash parent_innerpuzhash_amounts_for_recovery_ids pubkey recovery_list_reveal)  # noqa
        innersol: Program = Program.to(
            [
                2,
                coin.amount,
                puzhash,
                puzhash,
                parent_innerpuzhash_amounts_for_recovery_ids,
                bytes(pubkey),
                self.did_info.backup_ids,
            ]
        )
        # full solution is (parent_info my_amount solution)
        assert self.did_info.current_inner is not None
        innerpuz: Program = self.did_info.current_inner
        full_puzzle: Program = did_wallet_puzzles.create_fullpuz(
            innerpuz,
            self.did_info.origin_coin.name(),
        )
        parent_info = self.get_parent_for_coin(coin)
        assert parent_info is not None
        fullsol = Program.to(
            [
                [
                    parent_info.parent_name,
                    parent_info.inner_puzzle_hash,
                    parent_info.amount,
                ],
                coin.amount,
                innersol,
            ]
        )
        list_of_solutions = [CoinSpend(coin, full_puzzle, fullsol)]

        index = await self.wallet_state_manager.puzzle_store.index_for_pubkey(pubkey)
        if index is None:
            raise ValueError("Unknown pubkey.")
        private = master_sk_to_wallet_sk_unhardened(self.wallet_state_manager.private_key, index)
        message = bytes(puzhash)
        sigs = [AugSchemeMPL.sign(private, message)]
        for _ in spend_bundle.coin_spends:
            sigs.append(AugSchemeMPL.sign(private, message))
        aggsig = AugSchemeMPL.aggregate(sigs)
        # assert AugSchemeMPL.verify(pubkey, message, aggsig)
        if spend_bundle is None:
            spend_bundle = SpendBundle(list_of_solutions, aggsig)
        else:
            spend_bundle = spend_bundle.aggregate([spend_bundle, SpendBundle(list_of_solutions, aggsig)])

        did_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=puzhash,
            amount=uint64(coin.amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.wallet_info.id,
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=bytes32(token_bytes()),
            memos=list(spend_bundle.get_memos().items()),
        )
        await self.standard_wallet.push_transaction(did_record)
        new_did_info = DIDInfo(
            self.did_info.origin_coin,
            self.did_info.backup_ids,
            self.did_info.num_of_backup_ids_needed,
            self.did_info.parent_info,
            self.did_info.current_inner,
            self.did_info.temp_coin,
            self.did_info.temp_puzhash,
            self.did_info.temp_pubkey,
            True,
        )
        await self.save_info(new_did_info, True)
        return spend_bundle

    async def get_new_innerpuz(self) -> Program:
        devrec = await self.wallet_state_manager.get_unused_derivation_record(self.standard_wallet.id())
        pubkey = bytes(devrec.pubkey)
        innerpuz = did_wallet_puzzles.create_innerpuz(
            pubkey,
            self.did_info.backup_ids,
            uint64(self.did_info.num_of_backup_ids_needed),
        )

        return innerpuz

    async def get_new_inner_hash(self) -> bytes32:
        innerpuz = await self.get_new_innerpuz()
        return innerpuz.get_tree_hash()

    async def get_innerhash_for_pubkey(self, pubkey: bytes):
        innerpuz = did_wallet_puzzles.create_innerpuz(
            pubkey,
            self.did_info.backup_ids,
            uint64(self.did_info.num_of_backup_ids_needed),
        )
        return innerpuz.get_tree_hash()

    async def inner_puzzle_for_did_puzzle(self, did_hash: bytes32) -> Program:
        record: DerivationRecord = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(
            did_hash
        )
        inner_puzzle: Program = did_wallet_puzzles.create_innerpuz(
            bytes(record.pubkey),
            self.did_info.backup_ids,
            self.did_info.num_of_backup_ids_needed,
        )
        return inner_puzzle

    def get_parent_for_coin(self, coin) -> Optional[LineageProof]:
        parent_info = None
        for name, ccparent in self.did_info.parent_info:
            if name == coin.parent_coin_info:
                parent_info = ccparent

        return parent_info

    async def generate_new_decentralised_id(self, amount: uint64) -> Optional[SpendBundle]:
        """
        This must be called under the wallet state manager lock
        """

        coins = await self.standard_wallet.select_coins(amount)
        if coins is None:
            return None

        origin = coins.copy().pop()
        genesis_launcher_puz = did_wallet_puzzles.SINGLETON_LAUNCHER
        launcher_coin = Coin(origin.name(), genesis_launcher_puz.get_tree_hash(), amount)

        did_inner: Program = await self.get_new_innerpuz()
        did_inner_hash = did_inner.get_tree_hash()
        did_full_puz = did_wallet_puzzles.create_fullpuz(did_inner, launcher_coin.name())
        did_puzzle_hash = did_full_puz.get_tree_hash()

        announcement_set: Set[Announcement] = set()
        announcement_message = Program.to([did_puzzle_hash, amount, bytes(0x80)]).get_tree_hash()
        announcement_set.add(Announcement(launcher_coin.name(), announcement_message))

        tx_record: Optional[TransactionRecord] = await self.standard_wallet.generate_signed_transaction(
            amount, genesis_launcher_puz.get_tree_hash(), uint64(0), origin.name(), coins, None, False, announcement_set
        )

        genesis_launcher_solution = Program.to([did_puzzle_hash, amount, bytes(0x80)])

        launcher_cs = CoinSpend(launcher_coin, genesis_launcher_puz, genesis_launcher_solution)
        launcher_sb = SpendBundle([launcher_cs], AugSchemeMPL.aggregate([]))
        eve_coin = Coin(launcher_coin.name(), did_puzzle_hash, amount)
        future_parent = LineageProof(
            eve_coin.parent_coin_info,
            did_inner_hash,
            eve_coin.amount,
        )
        eve_parent = LineageProof(
            launcher_coin.parent_coin_info,
            launcher_coin.puzzle_hash,
            launcher_coin.amount,
        )
        await self.add_parent(eve_coin.parent_coin_info, eve_parent, False)
        await self.add_parent(eve_coin.name(), future_parent, False)

        if tx_record is None or tx_record.spend_bundle is None:
            return None

        # Only want to save this information if the transaction is valid
        did_info: DIDInfo = DIDInfo(
            launcher_coin,
            self.did_info.backup_ids,
            self.did_info.num_of_backup_ids_needed,
            self.did_info.parent_info,
            did_inner,
            None,
            None,
            None,
            False,
        )
        await self.save_info(did_info, False)
        eve_spend = await self.generate_eve_spend(eve_coin, did_full_puz, did_inner)
        full_spend = SpendBundle.aggregate([tx_record.spend_bundle, eve_spend, launcher_sb])
        return full_spend

    async def generate_eve_spend(self, coin: Coin, full_puzzle: Program, innerpuz: Program):
        assert self.did_info.origin_coin is not None
        # innerpuz solution is (mode amount message new_puzhash)
        innersol = Program.to([1, coin.amount, [], innerpuz.get_tree_hash()])
        # full solution is (lineage_proof my_amount inner_solution)
        fullsol = Program.to(
            [
                [self.did_info.origin_coin.parent_coin_info, self.did_info.origin_coin.amount],
                coin.amount,
                innersol,
            ]
        )
        list_of_solutions = [CoinSpend(coin, full_puzzle, fullsol)]
        # sign for AGG_SIG_ME
        message = (
            Program.to([innerpuz.get_tree_hash(), coin.amount, []]).get_tree_hash()
            + coin.name()
            + self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA
        )
        pubkey = did_wallet_puzzles.get_pubkey_from_innerpuz(innerpuz)
        record: Optional[DerivationRecord] = await self.wallet_state_manager.puzzle_store.record_for_pubkey(pubkey)
        assert record is not None
        private = master_sk_to_wallet_sk_unhardened(self.wallet_state_manager.private_key, record.index)
        signature = AugSchemeMPL.sign(private, message)
        sigs = [signature]
        aggsig = AugSchemeMPL.aggregate(sigs)
        spend_bundle = SpendBundle(list_of_solutions, aggsig)
        return spend_bundle

    async def get_frozen_amount(self) -> uint64:
        return await self.wallet_state_manager.get_frozen_balance(self.wallet_info.id)

    async def get_spendable_balance(self, unspent_records=None) -> uint64:
        spendable_am = await self.wallet_state_manager.get_confirmed_spendable_balance_for_wallet(
            self.wallet_info.id, unspent_records
        )
        return spendable_am

    async def get_max_send_amount(self, records=None):
        max_send_amount = await self.get_confirmed_balance()

        return max_send_amount

    async def add_parent(self, name: bytes32, parent: Optional[LineageProof], in_transaction: bool):
        self.log.info(f"Adding parent {name}: {parent}")
        current_list = self.did_info.parent_info.copy()
        current_list.append((name, parent))
        did_info: DIDInfo = DIDInfo(
            self.did_info.origin_coin,
            self.did_info.backup_ids,
            self.did_info.num_of_backup_ids_needed,
            current_list,
            self.did_info.current_inner,
            self.did_info.temp_coin,
            self.did_info.temp_puzhash,
            self.did_info.temp_pubkey,
            self.did_info.sent_recovery_transaction,
        )
        await self.save_info(did_info, in_transaction)

    async def update_recovery_list(self, recover_list: List[bytes], num_of_backup_ids_needed: uint64):
        if num_of_backup_ids_needed > len(recover_list):
            return False
        did_info: DIDInfo = DIDInfo(
            self.did_info.origin_coin,
            recover_list,
            num_of_backup_ids_needed,
            self.did_info.parent_info,
            self.did_info.current_inner,
            self.did_info.temp_coin,
            self.did_info.temp_puzhash,
            self.did_info.temp_pubkey,
            self.did_info.sent_recovery_transaction,
        )
        await self.save_info(did_info, False)
        await self.wallet_state_manager.update_wallet_puzzle_hashes(self.wallet_info.id)
        return True

    async def save_info(self, did_info: DIDInfo, in_transaction: bool):
        self.did_info = did_info
        current_info = self.wallet_info
        data_str = json.dumps(did_info.to_json_dict())
        wallet_info = WalletInfo(current_info.id, current_info.name, current_info.type, data_str)
        self.wallet_info = wallet_info
        await self.wallet_state_manager.user_store.update_wallet(wallet_info, in_transaction)
