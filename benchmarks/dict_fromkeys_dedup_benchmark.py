"""
Performance benchmark for dict.fromkeys() as a list deduplication method.

Tests deduplication of a 1.5 million item list under varying duplicate conditions:
  - No duplicates (all unique)
  - All duplicates (single repeated value)
  - Low duplicates (~10%)
  - Medium duplicates (~50%)
  - High duplicates (~90%)
  - Random duplicate ratio (chosen per run)

Also compares dict.fromkeys() against set() for reference.
"""

import random
import statistics
import time
from typing import Callable

LIST_SIZE = 1_500_000
WARMUP_RUNS = 1
TIMED_RUNS = 5


# ---------------------------------------------------------------------------
# Data generators
# ---------------------------------------------------------------------------

def generate_no_duplicates() -> list[int]:
    """1.5M unique integers in shuffled order."""
    items = list(range(LIST_SIZE))
    random.shuffle(items)
    return items


def generate_all_duplicates() -> list[int]:
    """1.5M copies of a single value."""
    return [42] * LIST_SIZE


def generate_low_duplicates() -> list[int]:
    """~10% of the values are duplicates."""
    unique_count = int(LIST_SIZE * 0.9)
    items = list(range(unique_count))
    extras = random.choices(range(unique_count), k=LIST_SIZE - unique_count)
    items.extend(extras)
    random.shuffle(items)
    return items


def generate_medium_duplicates() -> list[int]:
    """~50% of the values are duplicates."""
    unique_count = LIST_SIZE // 2
    items = list(range(unique_count))
    extras = random.choices(range(unique_count), k=LIST_SIZE - unique_count)
    items.extend(extras)
    random.shuffle(items)
    return items


def generate_high_duplicates() -> list[int]:
    """~90% of the values are duplicates."""
    unique_count = LIST_SIZE // 10
    items = random.choices(range(unique_count), k=LIST_SIZE)
    return items


def generate_random_duplicates() -> list[int]:
    """Random duplicate ratio (between 5% and 95% unique values)."""
    unique_fraction = random.uniform(0.05, 0.95)
    unique_count = max(1, int(LIST_SIZE * unique_fraction))
    items = random.choices(range(unique_count), k=LIST_SIZE)
    return items


# ---------------------------------------------------------------------------
# Dedup strategies
# ---------------------------------------------------------------------------

def dedup_dict_fromkeys(data: list[int]) -> list[int]:
    return list(dict.fromkeys(data))


def dedup_set(data: list[int]) -> list[int]:
    return list(set(data))


def dedup_ordered_set(data: list[int]) -> list[int]:
    """Preserves order using a seen-set (manual approach)."""
    seen: set[int] = set()
    result: list[int] = []
    for item in data:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


# ---------------------------------------------------------------------------
# Benchmark harness
# ---------------------------------------------------------------------------

def benchmark(func: Callable[[list[int]], list[int]], data: list[int]) -> dict:
    """Run *func* on *data* multiple times and return timing stats."""
    for _ in range(WARMUP_RUNS):
        func(data)

    times: list[float] = []
    for _ in range(TIMED_RUNS):
        start = time.perf_counter()
        result = func(data)
        elapsed = time.perf_counter() - start
        times.append(elapsed)

    return {
        "unique_count": len(result),
        "min_s": min(times),
        "max_s": max(times),
        "mean_s": statistics.mean(times),
        "median_s": statistics.median(times),
        "stdev_s": statistics.stdev(times) if len(times) > 1 else 0.0,
    }


def run_scenario(name: str, data: list[int]) -> None:
    total = len(data)
    unique_actual = len(set(data))
    dup_pct = (1 - unique_actual / total) * 100

    print(f"\n{'=' * 72}")
    print(f"Scenario: {name}")
    print(f"  List size:       {total:>12,}")
    print(f"  Unique values:   {unique_actual:>12,}")
    print(f"  Duplicate %:     {dup_pct:>11.2f}%")
    print(f"{'=' * 72}")

    strategies = [
        ("dict.fromkeys()", dedup_dict_fromkeys),
        ("set()",           dedup_set),
        ("seen-set loop",   dedup_ordered_set),
    ]

    for label, func in strategies:
        stats = benchmark(func, data)
        print(
            f"  {label:<20s}  "
            f"mean={stats['mean_s']:.4f}s  "
            f"median={stats['median_s']:.4f}s  "
            f"min={stats['min_s']:.4f}s  "
            f"max={stats['max_s']:.4f}s  "
            f"stdev={stats['stdev_s']:.4f}s  "
            f"unique={stats['unique_count']:,}"
        )


def main() -> None:
    random.seed(12345)

    print("dict.fromkeys() deduplication benchmark")
    print(f"List size: {LIST_SIZE:,} items  |  {TIMED_RUNS} timed runs per strategy")

    scenarios = [
        ("No duplicates (all unique)", generate_no_duplicates),
        ("All duplicates (single value)", generate_all_duplicates),
        ("Low duplicates (~10%)", generate_low_duplicates),
        ("Medium duplicates (~50%)", generate_medium_duplicates),
        ("High duplicates (~90%)", generate_high_duplicates),
        ("Random duplicate ratio", generate_random_duplicates),
    ]

    for name, generator in scenarios:
        data = generator()
        run_scenario(name, data)

    print(f"\n{'=' * 72}")
    print("Benchmark complete.")


if __name__ == "__main__":
    main()
