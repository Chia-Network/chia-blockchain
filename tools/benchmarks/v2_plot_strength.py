from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from collections import Counter
from collections.abc import Iterable
from typing import Any

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32, uint64, uint128

from chia.consensus.pot_iterations import calculate_iterations_quality, calculate_sp_interval_iters
from chia.simulator.block_tools import BlockTools, test_constants
from chia.simulator.keyring import TempKeyring
from chia.types.blockchain_format.proof_of_space import (
    calculate_plot_filter_bits,
    calculate_pos_challenge,
    compute_plot_group_id,
    passes_plot_filter_v2,
)
from chia.util.hash import std_hash
from chia.util.keyring_wrapper import KeyringWrapper


def parse_strengths(value: str) -> list[int]:
    strengths = [int(part) for part in value.split(",") if part]
    if len(strengths) == 0:
        raise argparse.ArgumentTypeError("at least one strength is required")
    return strengths


def challenge_bytes(label: str, index: int) -> bytes32:
    return std_hash(label.encode() + index.to_bytes(8, "big"))


def log(message: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {message}", flush=True)


async def run_strength(
    *,
    strength: int,
    challenges: int,
    plots_per_strength: int,
    progress_every: int,
) -> dict[str, Any]:
    constants = test_constants.replace(
        HARD_FORK2_HEIGHT=uint32(0),
        SOFT_FORK9_HEIGHT=uint32(0),
        MIN_PLOT_STRENGTH=uint8(2),
        MAX_PLOT_STRENGTH=uint8(17),
        NUMBER_ZERO_BITS_PLOT_FILTER_V2=uint8(0),
        DIFFICULTY_STARTING=uint64(2**10),
        DIFFICULTY_CONSTANT_FACTOR=uint128(33554432),
    )
    sp_interval_iters = calculate_sp_interval_iters(constants, constants.SUB_SLOT_ITERS_STARTING)

    log(f"start strength={strength} challenges={challenges}")
    with TempKeyring(populate=True) as keychain:
        plot_dir = f"v2-strength-bench-{strength}-{uuid.uuid4().hex}"
        with BlockTools(constants=constants, keychain=keychain, plot_dir=plot_dir) as bt:
            await bt.setup_keys()
            bt.add_plot_directory(bt.plot_dir)

            for _ in range(plots_per_strength):
                await bt.new_plot2(plot_size=int(constants.PLOT_SIZE_V2), strength=strength)
            await bt.refresh_plots()

            plots = list(bt.plot_manager.plots.values())
            loaded_strengths = Counter(plot.prover.get_strength() for plot in plots)
            group_strength = calculate_plot_filter_bits(uint32(0), constants, strength)

            started = time.monotonic()
            filter_passes = 0
            qualities = 0
            eligible_qualities = 0
            per_plot_filter_passes: Counter[int] = Counter()

            for challenge_index in range(challenges):
                if challenge_index > 0 and challenge_index % progress_every == 0:
                    log(
                        f"strength={strength} scanned={challenge_index} "
                        f"filter_passes={filter_passes} eligible={eligible_qualities}"
                    )

                challenge_hash = challenge_bytes("challenge", challenge_index)
                signage_point = challenge_bytes("sp", challenge_index)
                filter_challenge = challenge_bytes("filter", challenge_index)
                signage_point_index = challenge_index % int(constants.NUM_SPS_SUB_SLOT)

                for plot_index, plot_info in enumerate(plots):
                    pool_info = plot_info.pool_contract_puzzle_hash or plot_info.pool_public_key
                    assert pool_info is not None

                    plot_group_id = compute_plot_group_id(strength, plot_info.plot_public_key, pool_info)
                    if not passes_plot_filter_v2(
                        plot_group_id,
                        plot_info.prover.get_param().meta_group,
                        group_strength,
                        filter_challenge,
                        signage_point_index,
                    ):
                        continue

                    filter_passes += 1
                    per_plot_filter_passes[plot_index] += 1

                    new_challenge = calculate_pos_challenge(plot_info.prover.get_id(), challenge_hash, signage_point)
                    plot_qualities = plot_info.prover.get_qualities_for_challenge(new_challenge)
                    qualities += len(plot_qualities)

                    for quality in plot_qualities:
                        required_iters = calculate_iterations_quality(
                            constants,
                            quality.get_string(),
                            plot_info.prover.get_param(),
                            constants.DIFFICULTY_STARTING,
                            signage_point,
                        )
                        if required_iters < sp_interval_iters:
                            eligible_qualities += 1

            KeyringWrapper.cleanup_shared_instance()

            result = {
                "strength": strength,
                "challenges": challenges,
                "plots": len(plots),
                "loaded_strengths": dict(loaded_strengths),
                "plot_checks": challenges * len(plots),
                "effective_filter_bits": group_strength,
                "expected_filter_passes": round(challenges * len(plots) / (2**group_strength), 3),
                "filter_passes": filter_passes,
                "qualities": qualities,
                "eligible_qualities": eligible_qualities,
                "filter_pass_rate": filter_passes / (challenges * len(plots)),
                "eligible_per_challenge": eligible_qualities / challenges,
                "qualities_per_filter_pass": qualities / filter_passes if filter_passes > 0 else None,
                "eligible_per_quality": eligible_qualities / qualities if qualities > 0 else None,
                "eligible_per_filter_pass": eligible_qualities / filter_passes if filter_passes > 0 else None,
                "per_plot_filter_passes": dict(per_plot_filter_passes),
                "elapsed_s": round(time.monotonic() - started, 3),
            }
            log(f"result {json.dumps(result, sort_keys=True)}")
            return result


async def run_benchmark(args: argparse.Namespace) -> None:
    constants = test_constants.replace(
        HARD_FORK2_HEIGHT=uint32(0),
        SOFT_FORK9_HEIGHT=uint32(0),
        MIN_PLOT_STRENGTH=uint8(2),
        MAX_PLOT_STRENGTH=uint8(17),
        NUMBER_ZERO_BITS_PLOT_FILTER_V2=uint8(0),
        DIFFICULTY_STARTING=uint64(2**10),
        DIFFICULTY_CONSTANT_FACTOR=uint128(33554432),
    )
    sp_interval_iters = calculate_sp_interval_iters(constants, constants.SUB_SLOT_ITERS_STARTING)
    config = {
        "plots_per_strength": args.plots,
        "num_sps_sub_slot": int(constants.NUM_SPS_SUB_SLOT),
        "base_filter_bits": int(constants.NUMBER_ZERO_BITS_PLOT_FILTER_V2),
        "sp_interval_iters": int(sp_interval_iters),
    }
    print(json.dumps({"config": config}, sort_keys=True), flush=True)

    results = []
    for strength in args.strengths:
        results.append(
            await run_strength(
                strength=strength,
                challenges=args.challenges,
                plots_per_strength=args.plots,
                progress_every=args.progress_every,
            )
        )

    print(json.dumps({"final_results": results}, sort_keys=True), flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Measure V2 plot-strength filter and quality rates.")
    parser.add_argument("--strengths", type=parse_strengths, default=[2, 8], help="Comma-separated strengths to test.")
    parser.add_argument("--challenges", type=int, default=100_000, help="Challenge count per strength.")
    parser.add_argument("--plots", type=int, default=4, help="V2 plots to create per strength.")
    parser.add_argument("--progress-every", type=int, default=10_000, help="Challenge progress interval.")
    return parser


def main(argv: Iterable[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    asyncio.run(run_benchmark(args))


if __name__ == "__main__":
    main()
