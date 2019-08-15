import time
import os
import sys
from hashlib import sha256
from secrets import token_hex
from chiapos import DiskPlotter, DiskProver
from blspy import PrivateKey, PrependSignature
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
from src.types.coinbase import CoinbaseInfo
from src.types.fees_target import FeesTarget
from lib.chiavdf.inkfish.create_discriminant import create_discriminant
from lib.chiavdf.inkfish.classgroup import ClassGroup
from lib.chiavdf.inkfish.proof_of_time import create_proof_of_time_nwesolowski


# Use the empty string as the seed for the private key
sk: PrivateKey = PrivateKey.from_seed(b'')
pool_pk = sk.get_public_key()
plot_pk = sk.get_public_key()
coinbase_target = sha256(sk.get_public_key().serialize()).digest()
fee_target = sha256(sk.get_public_key().serialize()).digest()
k = 19
n_wesolowski = 3


def create_genesis_block(challenge_hash=bytes([0]*32)) -> FullBlock:
    plot_seed: bytes32 = ProofOfSpace.calculate_plot_seed(pool_pk, plot_pk)
    filename: str = "genesis-plot-" + token_hex(10)

    plotter = DiskPlotter()
    try:
        plotter.create_plot_disk(filename, k, b"genesis", plot_seed)

        prover = DiskProver(filename)

        qualities = prover.get_qualities_for_challenge(challenge_hash)

        if len(qualities) == 0:
            os.remove(filename)
            raise RuntimeError("No proofs for this challenge")

        proof_xs: bytes = prover.get_full_proof(challenge_hash, 0)
        proof_of_space: ProofOfSpace = ProofOfSpace(pool_pk, plot_pk, k, list(proof_xs))
    except KeyboardInterrupt:
        os.remove(filename)
        sys.exit(1)

    os.remove(filename)

    number_iters: uint64 = pot_iterations.calculate_iterations(proof_of_space, challenge_hash,
                                                               uint64(constants.DIFFICULTY_STARTING))

    disc: int = create_discriminant(challenge_hash, constants.DISCRIMINANT_SIZE_BITS)
    start_x: ClassGroup = ClassGroup.from_ab_discriminant(2, 1, disc)

    y, proof_bytes = create_proof_of_time_nwesolowski(disc, start_x, number_iters,
                                                      constants.DISCRIMINANT_SIZE_BITS, n_wesolowski)
    y_cl = ClassGroup.from_bytes(y, disc)
    print(y_cl)
    output = ProofOfTimeOutput(challenge_hash, number_iters,
                               ClassgroupElement(y_cl[0], y_cl[1]))

    proof_of_time = ProofOfTime(output, n_wesolowski, [uint8(b) for b in proof_bytes])

    coinbase: CoinbaseInfo = CoinbaseInfo(0, block_rewards.calculate_block_reward(uint32(0)),
                                          coinbase_target)
    coinbase_sig: PrependSignature = sk.sign_prepend(coinbase.serialize())
    fees_target: FeesTarget = FeesTarget(fee_target, 0)

    body: BlockBody = BlockBody(coinbase, coinbase_sig, fees_target, None, bytes([0]*32))

    timestamp = uint64(time.time())

    header_data: BlockHeaderData = BlockHeaderData(bytes([0]*32), timestamp, bytes([0]*32),
                                                   proof_of_space.get_hash(), body.get_hash(),
                                                   bytes([0]*32))

    header_sig: PrependSignature = sk.sign_prepend(header_data.serialize())
    header: BlockHeader = BlockHeader(header_data, header_sig)

    print(proof_of_space.get_hash(), proof_of_time.get_hash(), 0,
          uint64(constants.DIFFICULTY_STARTING))

    challenge = Challenge(proof_of_space.get_hash(), proof_of_time.get_hash(), 0,
                          uint64(constants.DIFFICULTY_STARTING))
    trunk_block = TrunkBlock(proof_of_space, proof_of_time, challenge, header)

    full_block: FullBlock = FullBlock(trunk_block, body)

    return full_block


block = create_genesis_block()
print(block.serialize())
