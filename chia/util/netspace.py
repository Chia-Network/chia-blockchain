from chia.consensus.block_record import BlockRecord
from chia.consensus.constants import ConsensusConstants
from chia.consensus.pos_quality import UI_ACTUAL_SPACE_CONSTANT_FACTOR


def estimate_network_space_bytes(newer_block: BlockRecord, older_block: BlockRecord, constants: ConsensusConstants):
    delta_weight = newer_block.weight - older_block.weight

    delta_iters = newer_block.total_iters - older_block.total_iters
    weight_div_iters = delta_weight / delta_iters
    additional_difficulty_constant = constants.DIFFICULTY_CONSTANT_FACTOR
    eligible_plots_filter_multiplier = 2 ** constants.NUMBER_ZERO_BITS_PLOT_FILTER
    network_space_bytes_estimate = (
            UI_ACTUAL_SPACE_CONSTANT_FACTOR
            * weight_div_iters
            * additional_difficulty_constant
            * eligible_plots_filter_multiplier
    )

    return network_space_bytes_estimate
