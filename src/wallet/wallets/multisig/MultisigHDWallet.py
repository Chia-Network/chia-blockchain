from chiasim.hashable import ProgramHash
from .address import address_for_puzzle_hash, puzzle_hash_for_address

from chiasim.puzzles.p2_m_of_n_delegate_direct import puzzle_for_m_of_public_key_list


class MultisigHDWallet:
    """
    A class implementing address generation for a hierarchical deterministic
    wallet.
    """

    def __init__(self, m, pub_hd_keys):
        self._m = m
        self._pub_hd_keys = pub_hd_keys
        self._ph_to_index_cache = {}
        self._index_to_ph_cache = {}

    def m(self):
        return self._m

    def pub_hd_keys(self):
        return self._pub_hd_keys

    def pub_keys_for_index(self, index) -> bytes:
        """
        Return N public keys corresponding to the given index.
        """
        pub_keys = []
        for pub_hd_key in self._pub_hd_keys:
            pub_keys.append(pub_hd_key.public_child(index))
        return pub_keys

    def puzzle_hash_for_index(self, index) -> bytes:
        """
        Return the puzzle hash corresponding to the given index.
        """
        if index not in self._index_to_ph_cache:
            pub_keys = self.pub_keys_for_index(index)
            puzzle = puzzle_for_m_of_public_key_list(self._m, pub_keys)
            puzzle_hash = ProgramHash(puzzle)
            self._index_to_ph_cache[index] = puzzle_hash
            self._ph_to_index_cache[puzzle_hash] = index
        return self._index_to_ph_cache[index]

    def address_for_index(self, index):
        """
        Return the address corresponding to the given index.
        """
        return address_for_puzzle_hash(self.puzzle_hash_for_index(index))

    def _index_for_puzzle_hash(self, puzzle_hash, search_limit) -> bytes:
        """
        Search for the index corresponding to the given puzzle hash.
        """
        index = 0
        while index <= search_limit:
            if self.puzzle_hash_for_index(index) == puzzle_hash:
                return index
            index += 1

    def index_for_puzzle_hash(self, puzzle_hash, search_limit) -> bytes:
        """
        Search for the index corresponding to the given puzzle hash
        (using the cache for previously calculated subkeys).
        """
        if puzzle_hash not in self._ph_to_index_cache:
            self._index_for_puzzle_hash(puzzle_hash, search_limit)
        return self._ph_to_index_cache[puzzle_hash]

    def index_for_address(self, address, search_limit):
        """
        Search for the index corresponding to the given address
        (using the cache for previously calculated subkeys).
        """
        puzzle_hash = puzzle_hash_for_address(address)
        return self.index_for_puzzle_hash(puzzle_hash, search_limit)
