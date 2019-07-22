from typing import List
from chiapos import DiskPlotter, DiskProver
from blspy import PrivateKey
from hashlib import sha256
import secrets


class Plotter:
    def __init__(self):
        self.plots_ = {}

    def find_plotfiles(self, directories=[]) -> List[str]:
        return []

    def create_plot(self, k: int, filename: str, pool_pk):
        # TODO: Check if we have enough disk space

        # Uses python secure random number generation
        seed = secrets.token_bytes(32)

        # Creates a private key and stores it in memory
        private_key: PrivateKey = PrivateKey.from_seed(seed)

        # TODO: store the private key and plot id on disk
        public_key_ser = private_key.get_public_key().serialize()
        plot_seed: bytes = sha256(pool_pk + public_key_ser).digest()
        plotter = DiskPlotter()
        plotter.create_plot_disk(filename, k, bytes([]), plot_seed)
        self.plots_[plot_seed] = (private_key, DiskProver(filename))

    def new_challenge(self, challenge_hash: bytes):
        # TODO: Create an ID based on plot id and index
        all_qualities = []
        for _, (_, prover) in self.plots_.items():
            qualities = prover.get_qualities_for_challenge(challenge_hash)
            for index, quality in enumerate(qualities):
                all_qualities.append((index, quality))
        return all_qualities

    def request_proof_of_space(self, challenge_hash: bytes, block_hash: bytes):
        # TODO: Lookup private key, plot id
        pass
