from chiasim.hashable import Body, Header, HeaderHash
from chiasim.storage import RAM_DB
from chiasim.validation.chainview import apply_deltas
from chiasim.wallet.deltas import additions_for_body, removals_for_body


class Storage(RAM_DB):
    def __init__(self, path, ledger_sim):
        self._path = path
        self._ledger_sim = ledger_sim
        self._interested_puzzled_hashes = set()
        self._header_list = []
        super(Storage, self).__init__()

    def add_interested_puzzle_hashes(self, puzzle_hashes):
        """
        Add the given puzzle hashes to the list of "interesting" ones.
        """
        self._interested_puzzled_hashes.update(puzzle_hashes)

    async def sync(self):
        """
        Get blocks from ledger sim and make a note of new and spent coins
        that are "interesting".
        """
        headers = []
        tip_dict = await self._ledger_sim.get_tip()
        genesis_hash = tip_dict["genesis_hash"]
        header_hash = tip_dict["tip_hash"]
        header_index = tip_dict["tip_index"]
        while True:
            if header_hash == genesis_hash:
                break
            if len(self._header_list) >= header_index and header_hash == HeaderHash(
                self._header_list[header_index - 1]
            ):
                break
            preimage = await self._ledger_sim.hash_preimage(hash=header_hash)
            header = Header.from_bytes(preimage)
            headers.append(header)
            header_hash = header.previous_hash
            header_index -= 1
        await self.rollback_to_block(header_index)
        new_block_count = len(headers)
        while headers:
            header = headers.pop()
            preimage = await self._ledger_sim.hash_preimage(hash=header.body_hash)
            body = Body.from_bytes(preimage)
            additions = [
                _
                for _ in additions_for_body(body)
                if _.puzzle_hash in self._interested_puzzled_hashes
            ]
            removals = [
                _
                for _ in removals_for_body(body)
                if _ in self._interested_puzzled_hashes
            ]
            await apply_deltas(header_index, additions, removals, self, self)
            self._header_list.append(header)
            header_index += 1
        return new_block_count

    def ledger_sim(self):
        return self._ledger_sim
