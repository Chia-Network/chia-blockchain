import time
import os
import sys
from hashlib import sha256
from chiapos import DiskPlotter, DiskProver
from typing import List
from blspy import PublicKey, PrivateKey, PrependSignature
from src.types.sized_bytes import bytes32
from src.types.full_block import FullBlock
from src.types.trunk_block import TrunkBlock
from src.types.block_body import BlockBody
from src.types.challenge import Challenge
from src.types.block_header import BlockHeader, BlockHeaderData
from src.types.proof_of_space import ProofOfSpace
from src.types.proof_of_time import ProofOfTime, ProofOfTimeOutput
from src.types.classgroup import ClassgroupElement
from src.consensus import constants, pot_iterations, block_rewards
from src.util.ints import uint64, uint32, uint8
from src.util.errors import NoProofsOfSpaceFound
from src.types.coinbase import CoinbaseInfo
from src.types.fees_target import FeesTarget
from lib.chiavdf.inkfish.create_discriminant import create_discriminant
from lib.chiavdf.inkfish.classgroup import ClassGroup
from lib.chiavdf.inkfish.proof_of_time import create_proof_of_time_nwesolowski


# Use the empty string as the seed for the private key
sk: PrivateKey = PrivateKey.from_seed(b'')
pool_pk: PublicKey = sk.get_public_key()
plot_pk: PublicKey = sk.get_public_key()
coinbase_target = sha256(sk.get_public_key().serialize()).digest()
fee_target = sha256(sk.get_public_key().serialize()).digest()
k = 20
num_plots = 4
n_wesolowski = 3


class BlockTools:
    """
    Tools to generate blocks for testing.
    """

    def __init__(self):
        self.plot_seed: bytes32 = ProofOfSpace.calculate_plot_seed(pool_pk, plot_pk)
        self.filenames: List[str] = [os.path.join("tests", "plots", "genesis-plot-" + str(k) +
                                                           sha256(int.to_bytes(i, 4, "big")).digest().hex() + ".dat")
                                     for i in range(num_plots)]

        try:
            for filename in self.filenames:
                if not os.path.exists(filename):
                    plotter = DiskPlotter()
                    plotter.create_plot_disk(filename, k, b"genesis", self.plot_seed)
        except KeyboardInterrupt:
            for filename in self.filenames:
                if os.path.exists(filename):
                    os.remove(filename)
            sys.exit(1)

    def get_consecutive_blocks(self, num_blocks: int) -> List[FullBlock]:
        for i in range(100):
            block_list = []
            try:
                block_list.append(self.create_genesis_block(bytes([i]*32)))
                for _ in range(num_blocks - 1):
                    block_list.append(self.create_next_block(block_list[-1]))
                return block_list
            except NoProofsOfSpaceFound:
                pass
        raise NoProofsOfSpaceFound

    def create_genesis_block(self, challenge_hash=bytes([0]*32)) -> FullBlock:
        return self._create_block(
            challenge_hash,
            uint32(0),
            bytes([0]*32),
            uint64(0),
            uint64(0),
            uint64(constants.DIFFICULTY_STARTING)
        )

    def create_next_block(self, prev_block: FullBlock) -> FullBlock:
        return self._create_block(
            prev_block.trunk_block.challenge.get_hash(),
            prev_block.height + 1,
            prev_block.header_hash,
            prev_block.trunk_block.challenge.total_iters,
            prev_block.weight,
            uint64(constants.DIFFICULTY_STARTING))

    def _create_block(self, challenge_hash: bytes32, height: uint32, prev_header_hash: bytes32,
                      prev_iters: uint64, prev_weight: uint64, difficulty: uint64) -> FullBlock:
        prover = None
        qualities = []
        for filename in self.filenames:
            prover = DiskProver(filename)
            qualities = prover.get_qualities_for_challenge(challenge_hash)
            if len(qualities) > 0:
                break

        if len(qualities) == 0:
            raise NoProofsOfSpaceFound("No proofs for this challenge")

        proof_xs: bytes = prover.get_full_proof(challenge_hash, 0)
        proof_of_space: ProofOfSpace = ProofOfSpace(pool_pk, plot_pk, k, list(proof_xs))

        number_iters: uint64 = pot_iterations.calculate_iterations(proof_of_space, challenge_hash,
                                                                   difficulty)

        disc: int = create_discriminant(challenge_hash, constants.DISCRIMINANT_SIZE_BITS)
        start_x: ClassGroup = ClassGroup.from_ab_discriminant(2, 1, disc)

        y_cl, proof_bytes = create_proof_of_time_nwesolowski(
            disc, start_x, number_iters, constants.DISCRIMINANT_SIZE_BITS, n_wesolowski)

        output = ProofOfTimeOutput(challenge_hash, number_iters,
                                   ClassgroupElement(y_cl[0], y_cl[1]))

        proof_of_time = ProofOfTime(output, n_wesolowski, [uint8(b) for b in proof_bytes])

        coinbase: CoinbaseInfo = CoinbaseInfo(height, block_rewards.calculate_block_reward(uint32(height)),
                                              coinbase_target)
        coinbase_sig: PrependSignature = sk.sign_prepend(coinbase.serialize())

        fees_target: FeesTarget = FeesTarget(fee_target, 0)

        body: BlockBody = BlockBody(coinbase, coinbase_sig, fees_target, None, bytes([0]*32))

        timestamp = uint64(time.time())

        header_data: BlockHeaderData = BlockHeaderData(prev_header_hash, timestamp, bytes([0]*32),
                                                       proof_of_space.get_hash(), body.get_hash(),
                                                       bytes([0]*32))

        header_hash_sig: PrependSignature = sk.sign_prepend(header_data.get_hash())

        header: BlockHeader = BlockHeader(header_data, header_hash_sig)

        challenge = Challenge(proof_of_space.get_hash(), proof_of_time.get_hash(), height,
                              prev_weight + difficulty, prev_iters + number_iters)
        trunk_block = TrunkBlock(proof_of_space, proof_of_time, challenge, header)

        full_block: FullBlock = FullBlock(trunk_block, body)

        return full_block


# print(create_genesis_block().serialize())
