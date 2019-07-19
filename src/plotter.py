from typing import List
from chiapos import DiskPlotter, DiskProver
from blspy import PrivateKey
from hashlib import sha256
import secrets


class Plotter:
    def __init__(self):
        # Uses python secure random number generation
        seed = secrets.token_bytes(32)

        # Creates a private key and stores it in memory
        self.private_key_: PrivateKey = PrivateKey.from_seed(seed)
        self.provers_ = []

    def find_plotfiles(self, directories=[]) -> List[str]:
        return []

    def create_plot(self, k: int, filename: str, pool_pk):
        public_key_ser = self.private_key_.get_public_key().serialize()
        plot_seed: bytes = sha256(pool_pk + public_key_ser).digest()
        plotter = DiskPlotter()
        plotter.create_plot_disk(filename, k, bytes([]), plot_seed)
        self.provers_.append(DiskProver(filename))

    def new_challenge(self, challenge_hash: bytes):
        all_qualities = []
        for prover in self.provers_:
            qualities = prover.get_qualities_for_challenge(challenge_hash)
            for index, quality in enumerate(qualities):
                all_qualities.append((index, quality))
        return qualities

    def request_proof_of_space(self, challenge_hash: bytes, block_hash: bytes):
        pass
