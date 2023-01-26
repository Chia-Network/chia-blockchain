from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from pathlib import Path
from sqlite3 import Row
from typing import Dict, List, Optional, Set

import pytest

from chia.util.db_synchronous import db_synchronous_on
from chia.util.db_wrapper import DBWrapper2, execute_fetchone
from chia.util.pprint import print_compact_ranges
from chia.wallet.util.wallet_types import WalletType

# TODO: Add verbose: print start and end derivation index per wallet
# TODO: Check for missing paired wallets (eg. No DID wallet for an NFT)
# TODO: Print name and ID of WalletType
# TODO: Use fancy command line library
# TODO: Check used contiguous
# TODO: Check for missing DID Wallets
# TODO: Use require_derivation_paths() to see whcih Wallets need derivations


def find_duplicates(array: List[int]) -> Set[int]:
    seen = set()
    duplicates = set()

    for i in array[1:]:
        if i in seen:
            duplicates.add(i)
        seen.add(i)

    return duplicates


def check_for_gaps(array: List[int], start: int, end: int, *, data_type: str = "Element") -> List[str]:
    """
    Check for compact sequence:
    Check that every value from start to end is present in array, and no more.
    start and end are values, not indexes
    start and end should be included in array
    array can be unsorted
    """

    if start > end:
        raise ValueError(f"{__name__} called with incorrect arguments: start={start} end={end} (start > end)")
    errors: List[str] = []

    if start == end and len(array) == 1:
        return errors

    expected_set = set(range(start, end + 1))
    actual_set = set(array)

    missing = expected_set.difference(actual_set)
    extras = actual_set.difference(expected_set)
    duplicates = find_duplicates(array)

    if len(missing) > 0:
        errors.append(f"Missing {data_type}: {print_compact_ranges(list(missing))}")
    if len(extras) > 0:
        errors.append(f"Unexpected {data_type}: {extras}")
    if len(duplicates) > 0:
        errors.append(f"Duplicates {data_type}: {duplicates}")

    return errors


class FromDB:
    def __init__(self, row: Row, fields: List[str]) -> None:
        self.fields = fields
        for field, value in zip(fields, row):
            setattr(self, field, value)

    def __repr__(self) -> str:
        s = ""
        for f in self.fields:
            s += f"{f}={getattr(self, f)} "
        return s


class DerivationPath(FromDB):
    derivation_index: int
    pubkey: str
    puzzle_hash: str
    wallet_type: int
    wallet_id: int
    used: int
    hardened: int


class Wallet(FromDB):
    id: int
    name: str
    wallet_type: int
    data: str


def dp_by_wallet_id(derivation_paths: List[DerivationPath]) -> Dict[int, List[int]]:
    d = defaultdict(list)
    for dp in derivation_paths:
        d[dp.wallet_id].append(dp.derivation_index)
    for k, v in d.items():
        d[k] = sorted(v)
    return d


def print_min_max_derivation_for_wallets(derivation_paths: List[DerivationPath]) -> None:
    d = dp_by_wallet_id(derivation_paths)
    print("Min, Max, Count of derivations for each wallet:")
    for wallet_id, derivation_index_list in d.items():
        print(
            f"Wallet ID {wallet_id:2} derivation index min: {derivation_index_list[0]} "
            f"max: {derivation_index_list[-1]} count: {len(derivation_index_list)}"
        )


class WalletDBReader:
    db_wrapper: DBWrapper2  # TODO: Remove db_wrapper member
    config = {"db_readers": 1}
    sql_log_path = None
    verbose = False

    async def get_all_wallets(self) -> List[Wallet]:
        wallet_fields = ["id", "name", "wallet_type", "data"]
        async with self.db_wrapper.reader_no_transaction() as reader:
            cursor = await reader.execute(f"""SELECT {", ".join(wallet_fields)} FROM users_wallets""")
            rows = await cursor.fetchall()
            return [Wallet(r, wallet_fields) for r in rows]

    async def get_derivation_paths(self) -> List[DerivationPath]:
        fields = ["derivation_index", "pubkey", "puzzle_hash", "wallet_type", "wallet_id", "used", "hardened"]
        async with self.db_wrapper.reader_no_transaction() as reader:
            cursor = await reader.execute(f"""SELECT {", ".join(fields)} FROM derivation_paths;""")
            rows = await cursor.fetchall()
            return [DerivationPath(row, fields) for row in rows]

    async def show_tables(self) -> List[str]:
        async with self.db_wrapper.reader_no_transaction() as reader:
            cursor = await reader.execute("""SELECT name FROM sqlite_master WHERE type='table';""")
            print("\nWallet DB Tables:")
            print(*([r[0] for r in await cursor.fetchall()]), sep=",\n")
            print("\nWallet Schema:")
            print(*(await (await cursor.execute("PRAGMA table_info('users_wallets')")).fetchall()), sep=",\n")
            print("\nDerivationPath Schema:")
            print(*(await (await cursor.execute("PRAGMA table_info('derivation_paths')")).fetchall()), sep=",\n")
            print()
            return []

    async def check_wallets(self) -> List[str]:
        # id, name, wallet_type, data
        # TODO: Move this SQL up a level
        async with self.db_wrapper.reader_no_transaction() as reader:
            errors = []
            try:
                main_wallet_id = 1
                main_wallet_type = 0
                row = await execute_fetchone(reader, "SELECT * FROM users_wallets WHERE id=?", (main_wallet_id,))
                if row is None:
                    errors.append(f"There is no wallet with ID {main_wallet_id} in table users_wallets")
                elif row[2] != main_wallet_type:
                    errors.append(
                        f"We expect wallet {main_wallet_id} to have type {main_wallet_type}, but it has {row[2]}"
                    )
            except Exception as e:
                errors.append(f"Exception while trying to access wallet {main_wallet_id} from users_wallets: {e}")

            max_id_row = await execute_fetchone(reader, "SELECT MAX(id) FROM users_wallets")
            if max_id_row is None:
                errors.append("Error fetching max wallet ID from table users_wallets. No wallets ?!?")
            else:
                cursor = await reader.execute("""SELECT * FROM users_wallets""")
                rows = await cursor.fetchall()
                max_id = max_id_row[0]
            errors.extend(check_for_gaps([r[0] for r in rows], main_wallet_id, max_id, data_type="Wallet IDs"))

            if self.verbose:
                print("\nWallets:")
                print(*rows, sep=",\n")
            # Check for invalid wallet types in users_wallets
            invalid_wallet_types = set()
            for row in rows:
                if row[2] not in set(wt.value for wt in WalletType):
                    invalid_wallet_types.add(row[2])
            if len(invalid_wallet_types) > 0:
                errors.append(f"Invalid Wallet Types found in table users_wallets: {invalid_wallet_types}")
            return errors

    def check_wallets_missing_derivations(
        self, wallets: List[Wallet], derivation_paths: List[DerivationPath]
    ) -> List[str]:
        p = []
        d = dp_by_wallet_id(derivation_paths)  # TODO: calc this once, pass in
        for wid in [w.id for w in wallets]:
            if wid not in d:
                p.append(wid)
        if len(p) > 0:
            return [f"Wallet IDs with no derivations: {p}"]
        return []

    def check_derivations_are_compact(self, wallets: List[Wallet], derivation_paths: List[DerivationPath]) -> List[str]:
        errors = []
        """
        Gaps in derivation index
        Missing hardened or unhardened derivations
        TODO: Gaps in used derivations
        """

        for wallet_id in [w.id for w in wallets]:
            for hardened in [0, 1]:
                dps = list(filter(lambda x: x.wallet_id == wallet_id and x.hardened == hardened, derivation_paths))
                if len(dps) < 1:
                    continue
                dpi = [x.derivation_index for x in dps]
                dpi.sort()
                max_id = dpi[-1]
                h = ["  hardened", "unhardened"][hardened]
                errors.extend(
                    check_for_gaps(dpi, 0, max_id, data_type=f"DerivationPath indexes for {h} wallet_id={wallet_id}")
                )
        return errors

    def check_unexpected_derivation_entries(
        self, wallets: List[Wallet], derivation_paths: List[DerivationPath]
    ) -> List[str]:
        """
        Check for unexpected derivation path entries

        Invalid Wallet Type
        Wallet IDs not in table 'users_wallets'
        Wallet ID with different wallet_type
        """

        errors = []
        wallet_id_to_type = {w.id: w.wallet_type for w in wallets}
        invalid_wallet_types = []
        missing_wallet_ids = []
        wrong_type = defaultdict(list)

        for d in derivation_paths:
            if d.wallet_type not in set(wt.value for wt in WalletType):
                invalid_wallet_types.append(d.wallet_type)
            if d.wallet_id not in wallet_id_to_type:
                missing_wallet_ids.append(d.wallet_id)
            elif d.wallet_type != wallet_id_to_type[d.wallet_id]:
                wrong_type[(d.hardened, d.wallet_id, d.wallet_type, wallet_id_to_type[d.wallet_id])].append(
                    d.derivation_index
                )

        if len(invalid_wallet_types) > 0:
            errors.append(f"Invalid wallet_types in derivation_paths table: {invalid_wallet_types}")

        if len(missing_wallet_ids) > 0:
            errors.append(
                f"Wallet IDs found in derivation_paths table, but not in users_wallets table: {missing_wallet_ids}"
            )

        for k, v in wrong_type.items():
            errors.append(
                f"""{["  ", "un"][int(k[0])]}hardened Wallet ID {k[1]} uses type {k[2]} in derivation_paths, """
                f"""but type {k[3]} in wallet table at these derivation indices: {v}"""
            )

        return errors

    async def scan(self, db_path: Path) -> None:
        self.db_wrapper = await DBWrapper2.create(
            database=db_path,
            reader_count=self.config.get("db_readers", 4),
            log_path=self.sql_log_path,
            synchronous=db_synchronous_on("auto"),
        )
        # TODO: Pass down db_wrapper
        wallets = await self.get_all_wallets()
        derivation_paths = await self.get_derivation_paths()
        try:
            errors = []

            if self.verbose:
                await self.show_tables()
                print_min_max_derivation_for_wallets(derivation_paths)

            errors.extend(await self.check_wallets())
            errors.extend(self.check_wallets_missing_derivations(wallets, derivation_paths))
            errors.extend(self.check_unexpected_derivation_entries(wallets, derivation_paths))
            errors.extend(self.check_derivations_are_compact(wallets, derivation_paths))
            if len(errors) > 0:
                print("\n    ---- Errors Found ----")
                print("\n".join(errors))
                sys.exit(2)
            else:
                print("No errors found.\n")
        finally:
            await self.db_wrapper.close()


async def scan(root_path: str, db_path: Optional[str] = None, *, verbose: bool = False) -> None:

    if db_path is None:
        wallet_db_path = Path(root_path) / "wallet" / "db"
        wallet_db_paths = list(wallet_db_path.glob("blockchain_wallet_*.sqlite"))
    else:
        wallet_db_paths = [Path(db_path)]

    for wallet_db_path in wallet_db_paths:
        w = WalletDBReader()
        w.verbose = verbose
        print(f"Reading {wallet_db_path}")
        await w.scan(Path(wallet_db_path))


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(scan("", sys.argv[1]))


def test_check_for_gaps_end_lt_start() -> None:
    with pytest.raises(ValueError):
        _ = check_for_gaps([], 2, 0)


def test_check_for_gaps_empty_array() -> None:
    with pytest.raises(ValueError):
        _ = check_for_gaps([], 1, 2)


def test_check_for_gaps_wrong_first() -> None:
    e = check_for_gaps([1, 1], 0, 1)
    assert "expected=0 actual=1" in e


def test_check_for_gaps_duplicates() -> None:
    e = check_for_gaps([1, 1], 1, 2)
    assert "Duplicate: 1" in e


def test_check_for_gaps_start_equal_end_ok() -> None:
    assert [] == check_for_gaps([0], 0, 0)
