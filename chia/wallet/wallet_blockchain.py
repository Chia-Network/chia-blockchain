import asyncio
import logging
from typing import Dict, Optional
from chia.consensus.constants import ConsensusConstants
from chia.types.header_block import HeaderBlock
from chia.util.ints import uint32
from chia.wallet.key_val_store import KeyValStore

log = logging.getLogger(__name__)


class WalletBlockchain:
    constants: ConsensusConstants
    constants_json: Dict
    # peak of the blockchain
    _peak_height: uint32
    wallet_state_manager_lock: asyncio.Lock
    # Whether blockchain is shut down or not
    _shut_down: bool

    # Lock to prevent simultaneous reads and writes
    lock: asyncio.Lock
    log: logging.Logger
    basic_store: KeyValStore
    latest_tx_block: Optional[HeaderBlock]
    peak: Optional[HeaderBlock]

    @staticmethod
    async def create(basic_store: KeyValStore):
        """
        Initializes a blockchain with the BlockRecords from disk, assuming they have all been
        validated. Uses the genesis block given in override_constants, or as a fallback,
        in the consensus constants config.
        """
        self = WalletBlockchain()
        self.basic_store = basic_store
        stored_height = await self.basic_store.get_str("STORED_HEIGHT")
        self.latest_tx_block = None
        self.latest_tx_block = await self.get_latest_tx_block()
        self.peak = None
        self.peak = await self.get_peak_block()
        if stored_height is None:
            self._peak_height = uint32(0)
        else:
            self._peak_height = uint32(int(stored_height))
        return self

    async def set_peak_height(self, height):
        self._peak_height = height
        await self.basic_store.set_str("STORED_HEIGHT", f"{height}")

    async def set_synced_height(self, height):
        await self.basic_store.set_str("SYNCED_HEIGHT", f"{height}")

    async def get_synced_height(self) -> int:
        synced_height = await self.basic_store.get_str("SYNCED_HEIGHT")
        if synced_height is not None:
            return int(synced_height)
        return 0

    def get_peak_height(self) -> Optional[uint32]:
        return self._peak_height

    async def set_latest_tx_block(self, block: HeaderBlock):
        await self.basic_store.set_object("LATEST_TX_BLOCK", block)
        self.latest_tx_block = block

    async def get_latest_tx_block(self) -> Optional[HeaderBlock]:
        if self.latest_tx_block is not None:
            return self.latest_tx_block
        obj = await self.basic_store.get_object("LATEST_TX_BLOCK", HeaderBlock)
        return obj

    async def set_peak_block(self, block: HeaderBlock):
        await self.basic_store.set_object("PEAK_BLOCK", block)
        self.peak = block

    async def get_peak_block(self) -> Optional[HeaderBlock]:
        if self.peak is not None:
            return self.peak
        obj = await self.basic_store.get_object("PEAK_BLOCK", HeaderBlock)
        return obj
