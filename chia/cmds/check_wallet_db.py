from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from pathlib import Path
from sqlite3 import Row
from typing import Any, Dict, Iterable, List, Optional, Set

from chia.util.collection import find_duplicates
from chia.util.db_synchronous import db_synchronous_on
from chia.util.db_wrapper import DBWrapper2, execute_fetchone
from chia.util.pprint import print_compact_ranges
from chia.wallet.util.wallet_types import WalletType

# TODO: Check for missing paired wallets (eg. No DID wallet for an NFT)
# TODO: Check for missing DID Wallets

help_text = """
\b
    The purpose of this command is find potential issues in Chia wallet databases.
    The core chia client currently uses sqlite to store the wallet databases, one database per key.
\b
    Guide to warning diagnostics:
    ----------------------------
    "Missing Wallet IDs": A wallet was created and later deleted. By itself, this is okay because
                          the wallet does not reuse wallet IDs. However, this information may be useful
                          in conjunction with other information.
\b
    Guide to error diagnostics:
    --------------------------
    Diagnostics in the error section indicate an error in the database structure.
    In general, this does not indicate an error in on-chain data, nor does it mean that you have lost coins.
\b
    An example is "Missing DerivationPath indexes" - a derivation path is a sub-key of your master key. Missing
    derivation paths could cause your wallet to not "know" about transactions that happened on the blockchain.
\b
"""


def _validate_args_addresses_used(wallet_id: int, last_index: int, last_hardened: int, dp: DerivationPath) -> None:
    if last_hardened:
        if last_hardened != dp.hardened:
            raise ValueError(f"Invalid argument: Mix of hardened and unhardened columns wallet_id={wallet_id}")

    if last_index:
        if last_index != dp.derivation_index:
            raise ValueError(f"Invalid argument: noncontiguous derivation_index at {last_index} wallet_id={wallet_id}")


def check_addresses_used_contiguous(derivation_paths: List[DerivationPath]) -> List[str]:
    """
    The used column for addresses in the derivation_paths table should be a
    zero or greater run of 1's, followed by a zero or greater run of 0's.
    There should be no used derivations after seeing a used derivation.
    """
    errors: List[str] = []

    for wallet_id, dps in dp_by_wallet_id(derivation_paths).items():
        saw_unused = False
        bad_used_values: Set[int] = set()
        ordering_errors: List[str] = []
        # last_index = None
        # last_hardened = None
        for dp in dps:
            # _validate_args_addresses_used(wallet_id, last_index, last_hardened, dp)

            if saw_unused and dp.used == 1 and ordering_errors == []:
                ordering_errors.append(
                    f"Wallet {dp.wallet_id}: "
                    f"Used address after unused address at derivation index {dp.derivation_index}"
                )

            if dp.used == 1:
                pass
            elif dp.used == 0:
                saw_unused = True
            else:
                bad_used_values.add(dp.used)

            # last_hardened = dp.hardened
            # last_index = dp.derivation_index

        if len(bad_used_values) > 0:
            errors.append(f"Wallet {wallet_id}: Bad values in 'used' column: {bad_used_values}")
        if ordering_errors != []:
            errors.extend(ordering_errors)

    return errors


def check_for_gaps(array: List[int], start: int, end: int, *, data_type_plural: str = "Elements") -> List[str]:
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
        errors.append(f"Missing {data_type_plural}: {print_compact_ranges(list(missing))}")
    if len(extras) > 0:
        errors.append(f"Unexpected {data_type_plural}: {extras}")
    if len(duplicates) > 0:
        errors.append(f"Duplicate {data_type_plural}: {duplicates}")

    return errors


class FromDB:
    def __init__(self, row: Iterable[Any], fields: List[str]) -> None:
        self.fields = fields
        for field, value in zip(fields, row):
            setattr(self, field, value)

    def __repr__(self) -> str:
        s = ""
        for f in self.fields:
            s += f"{f}={getattr(self, f)} "
        return s


def wallet_type_name(
    wallet_type: int,
) -> str:
    if wallet_type in set(wt.value for wt in WalletType):
        return f"{WalletType(wallet_type).name} ({wallet_type})"
    else:
        return f"INVALID_WALLET_TYPE ({wallet_type})"


def _cwr(row: Row) -> List[Any]:
    r = []
    for i, v in enumerate(row):
        if i == 2:
            r.append(wallet_type_name(v))
        else:
            r.append(v)
    return r


# wallet_types_that_dont_need_derivations: See require_derivation_paths for each wallet type
wallet_types_that_dont_need_derivations = {WalletType.POOLING_WALLET, WalletType.NFT}


class DerivationPath(FromDB):
    derivation_index: int
    pubkey: str
    puzzle_hash: str
    wallet_type: WalletType
    wallet_id: int
    used: int  # 1 or 0
    hardened: int  # 1 or 0


class Wallet(FromDB):
    id: int  # id >= 1
    name: str
    wallet_type: WalletType
    data: str


def dp_by_wallet_id(derivation_paths: List[DerivationPath]) -> Dict[int, List[DerivationPath]]:
    d = defaultdict(list)
    for derivation_path in derivation_paths:
        d[derivation_path.wallet_id].append(derivation_path)
    for k, v in d.items():
        d[k] = sorted(v, key=lambda dp: dp.derivation_index)
    return d


def derivation_indices_by_wallet_id(derivation_paths: List[DerivationPath]) -> Dict[int, List[int]]:
    d = dp_by_wallet_id(derivation_paths)
    di = {}
    for k, v in d.items():
        di[k] = [dp.derivation_index for dp in v]
    return di


def print_min_max_derivation_for_wallets(derivation_paths: List[DerivationPath]) -> None:
    d = derivation_indices_by_wallet_id(derivation_paths)
    print("Min, Max, Count of derivations for each wallet:")
    for wallet_id, derivation_index_list in d.items():
        # TODO: Fix count by separating hardened and unhardened
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
            # TODO: if table doesn't exist
            cursor = await reader.execute(f"""SELECT {", ".join(wallet_fields)} FROM users_wallets""")
            rows = await cursor.fetchall()
            return [Wallet(r, wallet_fields) for r in rows]

    async def get_derivation_paths(self) -> List[DerivationPath]:
        fields = ["derivation_index", "pubkey", "puzzle_hash", "wallet_type", "wallet_id", "used", "hardened"]
        async with self.db_wrapper.reader_no_transaction() as reader:
            # TODO: if table doesn't exist
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
                main_wallet_type = WalletType.STANDARD_WALLET
                row = await execute_fetchone(reader, "SELECT * FROM users_wallets WHERE id=?", (main_wallet_id,))
                if row is None:
                    errors.append(f"There is no wallet with ID {main_wallet_id} in table users_wallets")
                elif row[2] != main_wallet_type:
                    errors.append(
                        f"We expect wallet {main_wallet_id} to have type {wallet_type_name(main_wallet_type)}, "
                        f"but it has {wallet_type_name(row[2])}"
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
            errors.extend(check_for_gaps([r[0] for r in rows], main_wallet_id, max_id, data_type_plural="Wallet IDs"))

            if self.verbose:
                print("\nWallets:")
                print(*[_cwr(r) for r in rows], sep=",\n")
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
        d = derivation_indices_by_wallet_id(derivation_paths)  # TODO: calc this once, pass in
        for w in wallets:
            if w.wallet_type not in wallet_types_that_dont_need_derivations and w.id not in d:
                p.append(w.id)
        if len(p) > 0:
            return [f"Wallet IDs with no derivations that require them: {p}"]
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
                    check_for_gaps(
                        dpi, 0, max_id, data_type_plural=f"DerivationPath indexes for {h} wallet_id={wallet_id}"
                    )
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
                f"""{["  ", "un"][int(k[0])]}hardened Wallet ID {k[1]} uses type {wallet_type_name(k[2])} in """
                f"derivation_paths, but type {wallet_type_name(k[3])} in wallet table at these derivation indices: {v}"
            )

        return errors

    async def scan(self, db_path: Path) -> int:
        """Returns number of lines of error output (not warnings)"""
        self.db_wrapper = await DBWrapper2.create(
            database=db_path,
            reader_count=self.config.get("db_readers", 4),
            log_path=self.sql_log_path,
            synchronous=db_synchronous_on("auto"),
        )
        # TODO: Pass down db_wrapper
        wallets = await self.get_all_wallets()
        derivation_paths = await self.get_derivation_paths()
        errors = []
        warnings = []
        try:
            if self.verbose:
                await self.show_tables()
                print_min_max_derivation_for_wallets(derivation_paths)

            warnings.extend(await self.check_wallets())

            errors.extend(self.check_wallets_missing_derivations(wallets, derivation_paths))
            errors.extend(self.check_unexpected_derivation_entries(wallets, derivation_paths))
            errors.extend(self.check_derivations_are_compact(wallets, derivation_paths))
            errors.extend(check_addresses_used_contiguous(derivation_paths))

            if len(warnings) > 0:
                print(f"    ---- Warnings Found for {db_path.name} ----")
                print("\n".join(warnings))
            if len(errors) > 0:
                print(f"    ---- Errors Found for {db_path.name}----")
                print("\n".join(errors))
        finally:
            await self.db_wrapper.close()
        return len(errors)


async def scan(root_path: str, db_path: Optional[str] = None, *, verbose: bool = False) -> None:
    if db_path is None:
        wallet_db_path = Path(root_path) / "wallet" / "db"
        wallet_db_paths = list(wallet_db_path.glob("blockchain_wallet_*.sqlite"))
    else:
        wallet_db_paths = [Path(db_path)]

    num_errors = 0
    for wallet_db_path in wallet_db_paths:
        w = WalletDBReader()
        w.verbose = verbose
        print(f"Reading {wallet_db_path}")
        num_errors += await w.scan(Path(wallet_db_path))

    if num_errors > 0:
        sys.exit(2)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(scan("", sys.argv[1]))
