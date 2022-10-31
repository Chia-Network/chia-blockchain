import logging
from typing import Dict, Optional, Tuple
from chia_rs import MEMPOOL_MODE, NO_NEG_DIV, get_puzzle_and_solution_for_coin as get_puzzle_and_solution_for_coin_rust
from chia.types.blockchain_format.coin import Coin

from chia.consensus.cost_calculator import NPCResult
from chia.types.spend_bundle_conditions import SpendBundleConditions
from chia.full_node.generator import setup_generator_args
from chia.types.coin_record import CoinRecord
from chia.types.generator_types import BlockGenerator
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.errors import Err
from chia.util.ints import uint32, uint64, uint16
from chia.wallet.puzzles.rom_bootstrap_generator import get_generator
from chia.types.blockchain_format.program import SerializedProgram
from chia.wallet.puzzles.load_clvm import load_serialized_clvm_maybe_recompile
from chia.consensus.default_constants import DEFAULT_CONSTANTS

from chia.types.blockchain_format.program import Program

GENERATOR_MOD = get_generator()

DESERIALIZE_MOD = load_serialized_clvm_maybe_recompile(
    "chialisp_deserialisation.clvm", package_or_requirement="chia.wallet.puzzles"
)

log = logging.getLogger(__name__)


def unwrap(x: Optional[uint32]) -> uint32:
    assert x is not None
    return x


def get_name_puzzle_conditions(
    generator: BlockGenerator, max_cost: int, *, cost_per_byte: int, mempool_mode: bool
) -> NPCResult:
    block_program, block_program_args = setup_generator_args(generator)
    size_cost = len(bytes(generator.program)) * cost_per_byte
    max_cost -= size_cost
    if max_cost < 0:
        return NPCResult(uint16(Err.INVALID_BLOCK_COST.value), None, uint64(0))

    # mempool mode also has these rules apply
    assert (MEMPOOL_MODE & NO_NEG_DIV) != 0

    if mempool_mode:
        flags = MEMPOOL_MODE
    else:
        # conditions must use integers in canonical encoding (i.e. no redundant
        # leading zeros)
        # the division operator may not be used with negative operands
        flags = NO_NEG_DIV

    try:
        err, result = GENERATOR_MOD.run_as_generator(max_cost, flags, block_program, block_program_args)
        assert (err is None) != (result is None)
        if err is not None:
            return NPCResult(uint16(err), None, uint64(0))
        else:
            assert result is not None
            return NPCResult(None, result, uint64(result.cost + size_cost))
    except BaseException:
        log.exception("get_name_puzzle_condition failed")
        return NPCResult(uint16(Err.GENERATOR_RUNTIME_ERROR.value), None, uint64(0))


def get_puzzle_and_solution_for_coin(
    generator: BlockGenerator, coin: Coin
) -> Tuple[Optional[Exception], Optional[SerializedProgram], Optional[SerializedProgram]]:
    try:
        args = bytearray(b"\xff")
        args += bytes(DESERIALIZE_MOD)
        args += b"\xff"
        args += bytes(Program.to([bytes(a) for a in generator.generator_refs]))
        args += b"\x80\x80"

        puzzle, solution = get_puzzle_and_solution_for_coin_rust(
            bytes(generator.program),
            bytes(args),
            DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
            coin.parent_coin_info,
            coin.amount,
            coin.puzzle_hash,
        )

        return None, SerializedProgram.from_bytes(puzzle), SerializedProgram.from_bytes(solution)
    except Exception as e:
        return e, None, None


def mempool_check_time_locks(
    removal_coin_records: Dict[bytes32, CoinRecord],
    bundle_conds: SpendBundleConditions,
    prev_transaction_block_height: uint32,
    timestamp: uint64,
) -> Optional[Err]:
    """
    Check all time and height conditions against current state.
    """

    if prev_transaction_block_height < bundle_conds.height_absolute:
        return Err.ASSERT_HEIGHT_ABSOLUTE_FAILED
    if timestamp < bundle_conds.seconds_absolute:
        return Err.ASSERT_SECONDS_ABSOLUTE_FAILED

    for spend in bundle_conds.spends:
        unspent = removal_coin_records[bytes32(spend.coin_id)]
        if spend.height_relative is not None:
            if prev_transaction_block_height < unspent.confirmed_block_index + spend.height_relative:
                return Err.ASSERT_HEIGHT_RELATIVE_FAILED
        if timestamp < unspent.timestamp + spend.seconds_relative:
            return Err.ASSERT_SECONDS_RELATIVE_FAILED
    return None
