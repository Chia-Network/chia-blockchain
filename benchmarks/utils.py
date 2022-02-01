from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.util.ints import uint64, uint32
from chia.consensus.coinbase import create_farmer_coin, create_pool_coin
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper
from typing import Tuple
from pathlib import Path
from datetime import datetime
import aiosqlite
import os
import sys
import random
from blspy import G2Element, G1Element, AugSchemeMPL

# farmer puzzle hash
ph = bytes32(b"a" * 32)


def rewards(height: uint32) -> Tuple[Coin, Coin]:
    farmer_coin = create_farmer_coin(height, ph, uint64(250000000), DEFAULT_CONSTANTS.GENESIS_CHALLENGE)
    pool_coin = create_pool_coin(height, ph, uint64(1750000000), DEFAULT_CONSTANTS.GENESIS_CHALLENGE)
    return farmer_coin, pool_coin


def rand_bytes(num) -> bytes:
    ret = bytearray(num)
    for i in range(num):
        ret[i] = random.getrandbits(8)
    return bytes(ret)


def rand_hash() -> bytes32:
    # TODO: address hint errors and remove ignores
    #       error: Incompatible return value type (got "bytes", expected "bytes32")  [return-value]
    return rand_bytes(32)  # type: ignore[return-value]


def rand_g1() -> G1Element:
    sk = AugSchemeMPL.key_gen(rand_bytes(96))
    return sk.get_g1()


def rand_g2() -> G2Element:
    sk = AugSchemeMPL.key_gen(rand_bytes(96))
    return AugSchemeMPL.sign(sk, b"foobar")


async def setup_db(name: str, db_version: int) -> DBWrapper:
    db_filename = Path(name)
    try:
        os.unlink(db_filename)
    except FileNotFoundError:
        pass
    connection = await aiosqlite.connect(db_filename)

    def sql_trace_callback(req: str):
        sql_log_path = "sql.log"
        timestamp = datetime.now().strftime("%H:%M:%S.%f")
        log = open(sql_log_path, "a")
        log.write(timestamp + " " + req + "\n")
        log.close()

    if "--sql-logging" in sys.argv:
        await connection.set_trace_callback(sql_trace_callback)

    await connection.execute("pragma journal_mode=wal")
    await connection.execute("pragma synchronous=full")

    return DBWrapper(connection, db_version)
