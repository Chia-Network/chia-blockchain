import time
from secrets import token_bytes
from typing import Dict, Optional, List, Set, Tuple
import logging
from src.types.hashable.coin import Coin
from src.types.hashable.coin_record import CoinRecord
from src.types.hashable.spend_bundle import SpendBundle
from src.types.sized_bytes import bytes32
from src.types.full_block import FullBlock
from src.types.challenge import Challenge
from src.consensus.constants import constants as consensus_constants
from src.types.header_block import HeaderBlock
from src.util.ints import uint32, uint64
from src.util.hash import std_hash
from src.wallet.transaction_record import TransactionRecord
from src.wallet.block_record import BlockRecord
from src.wallet.wallet_store import WalletStore
from src.wallet.wallet_transaction_store import WalletTransactionStore
from src.full_node.blockchain import ReceiveBlockResult


class WalletStateManager:
    constants: Dict
    key_config: Dict
    config: Dict
    wallet_store: WalletStore
    tx_store: WalletTransactionStore
    # Map from header hash to BlockRecord
    block_records: Dict[bytes32, BlockRecord]
    # Specifies the LCA path
    height_to_hash: Dict[uint32, bytes32]
    # Header hash of tip (least common ancestor)
    lca: Optional[bytes32]
    start_index: int

    log: logging.Logger

    # TODO Don't allow user to send tx until wallet is synced
    synced: bool

    @staticmethod
    async def create(
        config: Dict,
        key_config: Dict,
        wallet_store: WalletStore,
        tx_store: WalletTransactionStore,
        name: str = None,
        override_constants: Dict = {},
    ):
        self = WalletStateManager()
        self.config = config
        self.constants = consensus_constants.copy()
        for key, value in override_constants.items():
            self.constants[key] = value
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_store = wallet_store
        self.tx_store = tx_store
        self.synced = False
        self.block_records = await wallet_store.get_lca_path()
        genesis = FullBlock.from_bytes(self.constants["GENESIS_BLOCK"])

        if len(self.block_records) > 0:
            # Header hash with the highest weight
            self.lca = max(
                (item[1].weight, item[0]) for item in self.block_records.items()
            )[1]
            for key, value in self.block_records.items():
                self.height_to_hash[value.height] = value.header_hash

            # Checks genesis block is the same in config, as in DB
            assert self.block_records[genesis.header_hash].height == 0
            assert self.block_records[genesis.header_hash].weight == genesis.weight
        else:
            # Loads the genesis block if there are no blocks
            genesis_challenge = Challenge(
                genesis.proof_of_space.challenge_hash,
                std_hash(
                    genesis.proof_of_space.get_hash()
                    + genesis.proof_of_time.output.get_hash()
                ),
                None,
            )
            genesis_hb = HeaderBlock(
                genesis.proof_of_space,
                genesis.proof_of_time,
                genesis_challenge,
                genesis.header,
            )
            # TODO(mariano): also check coinbase and fees coin
            await self.receive_block(
                BlockRecord(
                    genesis.header_hash,
                    genesis.prev_header_hash,
                    uint32(0),
                    genesis.weight,
                    [],
                    [],
                ),
                genesis_hb,
            )
        return self

    async def get_confirmed_balance(self) -> uint64:
        record_list: Set[
            CoinRecord
        ] = await self.wallet_store.get_coin_records_by_spent(False)
        amount: uint64 = uint64(0)

        for record in record_list:
            amount = uint64(amount + record.coin.amount)

        return uint64(amount)

    async def get_unconfirmed_balance(self) -> uint64:
        confirmed = await self.get_confirmed_balance()
        unconfirmed_tx = await self.tx_store.get_not_confirmed()
        addition_amount = 0
        removal_amount = 0

        for record in unconfirmed_tx:
            for coin in record.additions:
                if await self.tx_store.puzzle_hash_exists(coin.puzzle_hash):
                    addition_amount += coin.amount
            for coin in record.removals:
                removal_amount += coin.amount

        result = confirmed - removal_amount + addition_amount
        return uint64(result)

    async def unconfirmed_additions(self) -> Dict[bytes32, Coin]:
        additions: Dict[bytes32, Coin] = {}
        unconfirmed_tx = await self.tx_store.get_not_confirmed()
        for record in unconfirmed_tx:
            for coin in record.additions:
                additions[coin.name()] = coin
        return additions

    async def unconfirmed_removals(self) -> Dict[bytes32, Coin]:
        removals: Dict[bytes32, Coin] = {}
        unconfirmed_tx = await self.tx_store.get_not_confirmed()
        for record in unconfirmed_tx:
            for coin in record.removals:
                removals[coin.name()] = coin
        return removals

    async def select_coins(self, amount) -> Optional[Set[Coin]]:

        if amount > await self.get_unconfirmed_balance():
            return None

        unspent: Set[CoinRecord] = await self.wallet_store.get_coin_records_by_spent(
            False
        )
        sum = 0
        used_coins: Set = set()

        """
        Try to use coins from the store, if there isn't enough of "unused"
        coins use change coins that are not confirmed yet
        """
        for coinrecord in unspent:
            if sum >= amount:
                break
            if coinrecord.coin.name in await self.unconfirmed_removals():
                continue
            sum += coinrecord.coin.amount
            used_coins.add(coinrecord.coin)

        """
        This happens when we couldn't use one of the coins because it's already used
        but unconfirmed, and we are waiting for the change. (unconfirmed_additions)
        """
        if sum < amount:
            for coin in (await self.unconfirmed_additions()).values():
                if sum > amount:
                    break
                if coin.name in (await self.unconfirmed_removals()).values():
                    continue
                sum += coin.amount
                used_coins.add(coin)

        if sum >= amount:
            return used_coins
        else:
            # This shouldn't happen because of: if amount > self.get_unconfirmed_balance():
            return None

    async def coin_removed(self, coin_name: bytes32, index: uint32):
        """
        Called when coin gets spent
        """
        await self.wallet_store.set_spent(coin_name, index)

    async def coin_added(self, coin: Coin, index: uint32, coinbase: bool):
        """
        Adding coin to the db
        """
        coin_record: CoinRecord = CoinRecord(coin, index, uint32(0), False, coinbase)
        await self.wallet_store.add_coin_record(coin_record)

    async def add_pending_transaction(self, spend_bundle: SpendBundle):
        """
        Called from wallet_node before new transaction is sent to the full_node
        """
        now = uint64(int(time.time()))
        add_list: List[Coin] = []
        rem_list: List[Coin] = []
        total_removed = 0
        total_added = 0
        outgoing_amount = 0

        for add in spend_bundle.additions():
            total_added += add.amount
            add_list.append(add)
        for rem in spend_bundle.removals():
            total_removed += rem.amount
            rem_list.append(rem)

        fee_amount = total_removed - total_added

        # Figure out if we are sending to ourself or someone else.
        to_puzzle_hash: Optional[bytes32] = None
        for add in add_list:
            if not await self.tx_store.puzzle_hash_exists(add.puzzle_hash):
                to_puzzlehash = add.puzzle_hash
                outgoing_amount += to_puzzlehash
                break

        # If there is no addition for outside puzzlehash we are sending tx to ourself
        incoming = False
        if to_puzzle_hash is None:
            incoming = True
            to_puzzle_hash = add_list[0]

        if incoming:
            tx_record = TransactionRecord(
                uint32(0), uint32(0), False, False, now, spend_bundle,
                add_list, rem_list, incoming, to_puzzle_hash, total_added, fee_amount
            )
        else:
            tx_record = TransactionRecord(
                uint32(0), uint32(0), False, False, now, spend_bundle,
                add_list, rem_list, incoming, to_puzzle_hash, outgoing_amount, fee_amount
            )

        # Wallet node will use this queue to retry sending this transaction until full nodes receives it
        await self.tx_store.add_transaction_record(tx_record)

    async def remove_from_queue(self, spendbundle_id: bytes32):
        """
        Full node received our transaction, no need to keep it in queue anymore
        """
        await self.tx_store.set_sent(spendbundle_id)

    async def get_send_queue(self) -> List[TransactionRecord]:
        """
        Wallet Node uses this to retry sending transactions
        """
        records = await self.tx_store.get_not_sent()
        return records

    async def get_all_transactions(self) -> List[TransactionRecord]:
        """
        Retrieves all confirmed and pending transactions
        """
        records = await self.tx_store.get_all_transactions()
        return records

    async def receive_block(
        self, block: BlockRecord, header_block: Optional[HeaderBlock] = None,
    ) -> ReceiveBlockResult:
        if block.header_hash in self.block_records:
            return ReceiveBlockResult.ALREADY_HAVE_BLOCK

        if block.prev_header_hash not in self.block_records or block.height == 0:
            return ReceiveBlockResult.DISCONNECTED_BLOCK

        if header_block is not None:
            # TODO: validate header block
            pass

        self.block_records[block.header_hash] = block
        await self.wallet_store.add_block_record(block, False)

        # Genesis case
        if self.lca is None:
            assert block.height == 0
            await self.wallet_store.add_block_to_path(block.header_hash)
            self.lca = block.header_hash
            for coin in block.additions:
                await self.coin_added(coin, block.height, False)
            for coin_name in block.removals:
                await self.coin_removed(coin_name, block.height)
            self.height_to_hash[uint32(0)] = block.header_hash
            return ReceiveBlockResult.ADDED_TO_HEAD

        # Not genesis, updated LCA
        if block.weight > self.block_records[self.lca].weight:
            fork_h = self.find_fork_for_lca(block)
            await self.wallet_store.rollback_lca_to_block(fork_h)

            # Add blocks between fork point and new lca
            fork_hash = self.height_to_hash[fork_h]
            blocks_to_add: List[BlockRecord] = []
            tip_hash: bytes32 = block.header_hash
            while True:
                if tip_hash == fork_hash:
                    break
                record = self.block_records[tip_hash]
                blocks_to_add.append(record)
                tip_hash = record.prev_header_hash
            blocks_to_add.reverse()

            for path_block in blocks_to_add:
                self.height_to_hash[path_block.height] = path_block.header_hash
                await self.wallet_store.add_block_to_path(path_block.header_hash)
                for coin in path_block.additions:
                    await self.coin_added(coin, path_block.height, False)
                for coin_name in path_block.removals:
                    await self.coin_removed(coin_name, path_block.height)
            return ReceiveBlockResult.ADDED_TO_HEAD

        return ReceiveBlockResult.ADDED_AS_ORPHAN

    def find_fork_for_lca(self, new_lca: BlockRecord) -> uint32:
        """ Tries to find height where new chain (current) diverged from the old chain where old_lca was the LCA"""
        tmp_old: BlockRecord = self.block_records[self.lca]
        while tmp_old.header_hash != self.height_to_hash[uint32(0)]:
            if tmp_old.header_hash == self.height_to_hash[uint32(0)]:
                return uint32(0)
            if tmp_old.height in self.height_to_hash:
                chain_hash_at_h = self.height_to_hash[tmp_old.height]
                if (
                    chain_hash_at_h == tmp_old.header_hash
                    and chain_hash_at_h != new_lca.header_hash
                ):
                    return tmp_old.height
            tmp_old = self.block_records[tmp_old.prev_header_hash]
        return uint32(0)

    def get_filter_additions_removals(
        self, transactions_fitler: bytes
    ) -> Tuple[List[bytes32], List[Coin]]:
        # TODO(straya): get all of wallet's additions and removals which are included in filter
        return ([], [])

    def get_relevant_additions(self, additions: List[Coin]) -> List[Coin]:
        # TODO(straya): get all additions which are relevant to us (we can spend) from the list
        return []

    def get_relevant_removals(self, removals: List[Coin]) -> List[Coin]:
        # TODO(straya): get all removals which are relevant to us (our money was spent) from the list
        return []
