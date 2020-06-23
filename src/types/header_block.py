from dataclasses import dataclass

from src.types.challenge import Challenge
from src.types.header import Header
from src.types.proof_of_space import ProofOfSpace
from src.types.proof_of_time import ProofOfTime
from src.util.streamable import Streamable, streamable
from src.consensus.coinbase import create_coinbase_coin, create_fees_coin
from src.consensus.block_rewards import calculate_block_reward
from src.types.coin import Coin


@dataclass(frozen=True)
@streamable
class HeaderBlock(Streamable):
    proof_of_space: ProofOfSpace
    proof_of_time: ProofOfTime
    challenge: Challenge
    header: Header

    @property
    def prev_header_hash(self):
        return self.header.data.prev_header_hash

    @property
    def height(self):
        return self.header.height

    @property
    def weight(self):
        return self.header.weight

    @property
    def header_hash(self):
        return self.header.header_hash

    def get_coinbase(self) -> Coin:
        br = calculate_block_reward(self.height)
        return create_coinbase_coin(
            self.height, self.proof_of_space.pool_puzzle_hash, br
        )

    def get_fees_coin(self) -> Coin:
        return create_fees_coin(
            self.height,
            self.proof_of_space.pool_puzzle_hash,
            self.header.data.transaction_fees,
        )