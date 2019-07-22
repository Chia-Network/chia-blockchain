from typing import List
from hashlib import sha256
import secrets
from blspy import PrivateKey
from .util.api_decorators import api_request
from chiapos import DiskPlotter, DiskProver
from .types import plotter_api


class Plotter:
    def __init__(self):
        self.plots_ = {}

    def find_plotfiles(self, directories=[]) -> List[str]:
        return []

    @api_request(create_plot=plotter_api.CreatePlot.from_bin)
    def create_plot(self, create_plot: plotter_api.CreatePlot):
        # TODO: Check if we have enough disk space

        # Uses python secure random number generation
        seed = secrets.token_bytes(32)

        # Creates a private key and stores it in memory
        private_key: PrivateKey = PrivateKey.from_seed(seed)

        # TODO: store the private key and plot id on disk
        public_key_ser = private_key.get_public_key().serialize()
        plot_seed: bytes = sha256(create_plot.pool_pubkey.serialize() + public_key_ser).digest()
        plotter = DiskPlotter()
        plotter.create_plot_disk(create_plot.filename, create_plot.size, bytes([]), plot_seed)
        self.plots_[plot_seed] = (private_key, DiskProver(create_plot.filename))

    @api_request(new_challenge=plotter_api.NewChallenge.from_bin)
    def new_challenge(self, new_challenge: plotter_api.NewChallenge):
        # TODO: Create an ID based on plot id and index
        all_qualities = []
        for _, (_, prover) in self.plots_.items():
            qualities = prover.get_qualities_for_challenge(new_challenge.challenge_hash)
            for index, quality in enumerate(qualities):
                all_qualities.append((index, quality))
        return all_qualities

    @api_request(request=plotter_api.RequestProofOfSpace.from_bin)
    def request_proof_of_space(self, request: plotter_api.RequestProofOfSpace):
        # TODO: Lookup private key, plot id
        pass
