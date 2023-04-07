from __future__ import annotations

import enum
import os
import random
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Generic, Optional, Tuple, Type, TypeVar, Union

import aiosqlite
import click
from blspy import AugSchemeMPL, G1Element, G2Element

from chia.consensus.coinbase import create_farmer_coin, create_pool_coin
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.foliage import Foliage, FoliageBlockData, FoliageTransactionBlock, TransactionsInfo
from chia.types.blockchain_format.pool_target import PoolTarget
from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.reward_chain_block import RewardChainBlock
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32, bytes100
from chia.types.blockchain_format.vdf import VDFInfo, VDFProof
from chia.types.full_block import FullBlock
from chia.util.db_wrapper import DBWrapper2
from chia.util.ints import uint8, uint32, uint64, uint128

# farmer puzzle hash
ph = bytes32(b"a" * 32)

with open(Path(os.path.realpath(__file__)).parent / "clvm_generator.bin", "rb") as f:
    clvm_generator = f.read()


_T_Enum = TypeVar("_T_Enum", bound=enum.Enum)


# Workaround to allow `Enum` with click.Choice: https://github.com/pallets/click/issues/605#issuecomment-901099036
class EnumType(click.Choice, Generic[_T_Enum]):
    def __init__(self, enum: Type[_T_Enum], case_sensitive: bool = False) -> None:
        self.__enum = enum
        super().__init__(choices=[item.value for item in enum], case_sensitive=case_sensitive)

    def convert(self, value: Any, param: Optional[click.Parameter], ctx: Optional[click.Context]) -> _T_Enum:
        converted_str = super().convert(value, param, ctx)
        return self.__enum(converted_str)


def rewards(height: uint32) -> Tuple[Coin, Coin]:
    farmer_coin = create_farmer_coin(height, ph, uint64(250000000), DEFAULT_CONSTANTS.GENESIS_CHALLENGE)
    pool_coin = create_pool_coin(height, ph, uint64(1750000000), DEFAULT_CONSTANTS.GENESIS_CHALLENGE)
    return farmer_coin, pool_coin


def rand_bytes(num: int) -> bytes:
    ret = bytearray(num)
    for i in range(num):
        ret[i] = random.getrandbits(8)
    return bytes(ret)


def rand_hash() -> bytes32:
    return bytes32(rand_bytes(32))


def rand_g1() -> G1Element:
    sk = AugSchemeMPL.key_gen(rand_bytes(96))
    return sk.get_g1()


def rand_g2() -> G2Element:
    sk = AugSchemeMPL.key_gen(rand_bytes(96))
    return AugSchemeMPL.sign(sk, b"foobar")


def rand_class_group_element() -> ClassgroupElement:
    return ClassgroupElement(bytes100(rand_bytes(100)))


def rand_vdf() -> VDFInfo:
    return VDFInfo(rand_hash(), uint64(random.randint(100000, 1000000000)), rand_class_group_element())


def rand_vdf_proof() -> VDFProof:
    return VDFProof(
        uint8(1),  # witness_type
        rand_hash(),  # witness
        bool(random.randint(0, 1)),  # normalized_to_identity
    )


def rand_full_block() -> FullBlock:
    proof_of_space = ProofOfSpace(
        rand_hash(),
        rand_g1(),
        None,
        rand_g1(),
        uint8(0),
        rand_bytes(8 * 32),
    )

    reward_chain_block = RewardChainBlock(
        uint128(1),
        uint32(2),
        uint128(3),
        uint8(4),
        rand_hash(),
        proof_of_space,
        None,
        rand_g2(),
        rand_vdf(),
        None,
        rand_g2(),
        rand_vdf(),
        rand_vdf(),
        True,
    )

    pool_target = PoolTarget(
        rand_hash(),
        uint32(0),
    )

    foliage_block_data = FoliageBlockData(
        rand_hash(),
        pool_target,
        rand_g2(),
        rand_hash(),
        rand_hash(),
    )

    foliage = Foliage(
        rand_hash(),
        rand_hash(),
        foliage_block_data,
        rand_g2(),
        rand_hash(),
        rand_g2(),
    )

    foliage_transaction_block = FoliageTransactionBlock(
        rand_hash(),
        uint64(0),
        rand_hash(),
        rand_hash(),
        rand_hash(),
        rand_hash(),
    )

    farmer_coin, pool_coin = rewards(uint32(0))

    transactions_info = TransactionsInfo(
        rand_hash(),
        rand_hash(),
        rand_g2(),
        uint64(0),
        uint64(1),
        [farmer_coin, pool_coin],
    )

    full_block = FullBlock(
        [],
        reward_chain_block,
        rand_vdf_proof(),
        rand_vdf_proof(),
        rand_vdf_proof(),
        rand_vdf_proof(),
        rand_vdf_proof(),
        foliage,
        foliage_transaction_block,
        transactions_info,
        SerializedProgram.from_bytes(clvm_generator),
        [],
    )

    return full_block


async def setup_db(name: Union[str, os.PathLike[str]], db_version: int) -> DBWrapper2:
    db_filename = Path(name)
    try:
        os.unlink(db_filename)
    except FileNotFoundError:
        pass
    connection = await aiosqlite.connect(db_filename)

    def sql_trace_callback(req: str) -> None:
        sql_log_path = "sql.log"
        timestamp = datetime.now().strftime("%H:%M:%S.%f")
        log = open(sql_log_path, "a")
        log.write(timestamp + " " + req + "\n")
        log.close()

    if "--sql-logging" in sys.argv:
        await connection.set_trace_callback(sql_trace_callback)

    await connection.execute("pragma journal_mode=wal")
    await connection.execute("pragma synchronous=full")

    ret = DBWrapper2(connection, db_version)
    await ret.add_connection(await aiosqlite.connect(db_filename))
    return ret


def get_commit_hash() -> str:
    try:
        os.chdir(Path(os.path.realpath(__file__)).parent)
        commit_hash = (
            subprocess.run(["git", "rev-parse", "--short", "HEAD"], check=True, stdout=subprocess.PIPE)
            .stdout.decode("utf-8")
            .strip()
        )
    except Exception:
        sys.exit("Failed to get the commit hash")
    try:
        if len(subprocess.run(["git", "status", "-s"], check=True, stdout=subprocess.PIPE).stdout) > 0:
            raise Exception()
    except Exception:
        commit_hash += "-dirty"
    return commit_hash
