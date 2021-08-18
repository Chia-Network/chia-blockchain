import logging
import time
import json
import unittest
from secrets import token_bytes
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import asyncio
import aiosqlite
import sqlite3

from blspy import AugSchemeMPL, G1Element, G2Element
from hashlib import sha256

from chives.consensus.constants import ConsensusConstants
from chives.consensus.coinbase import create_puzzlehash_for_pk
from chives.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chives.util.config import load_config
from chives.util.default_root import DEFAULT_ROOT_PATH
from chives.util.ints import uint32, uint64
from chives.util.hash import std_hash
from chives.util.db_wrapper import DBWrapper
from chives.util.keychain import Keychain, bytes_from_mnemonic, bytes_to_mnemonic, generate_mnemonic, mnemonic_to_seed
from chives.wallet.derive_keys import master_sk_to_farmer_sk, master_sk_to_pool_sk, master_sk_to_wallet_sk
from chives.wallet.wallet_coin_store import WalletCoinStore
from chives.types.blockchain_format.coin import Coin
from chives.types.blockchain_format.program import Program, SerializedProgram
from chives.types.blockchain_format.sized_bytes import bytes32

from chives.wallet.util.wallet_types import WalletType
from chives.wallet.wallet_coin_record import WalletCoinRecord

from chives.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
    puzzle_for_pk,
    solution_for_conditions,
)
from chives.wallet.puzzles.puzzle_utils import (
    make_assert_coin_announcement,
    make_assert_puzzle_announcement,
    make_assert_my_coin_id_condition,
    make_assert_absolute_seconds_exceeds_condition,
    make_create_coin_announcement,
    make_create_puzzle_announcement,
    make_create_coin_condition,
    make_reserve_fee_condition,
)

import redis
r = redis.Redis(host='localhost', port=6379, decode_responses=True)

class TesKeychain():
    
    async def puzzle_for_puzzle_hash(puzzle_hash: bytes32) -> Program:
        public_key = await TesKeychain.hack_populate_secret_key_for_puzzle_hash(puzzle_hash)
        return puzzle_for_pk(bytes(public_key))
    
    def make_solution(
        primaries: Optional[List[Dict[str, Any]]] = None,
        min_time=0,
        me=None,
        coin_announcements: Optional[List[bytes32]] = None,
        coin_announcements_to_assert: Optional[List[bytes32]] = None,
        puzzle_announcements=None,
        puzzle_announcements_to_assert=None,
        fee=0,
    ) -> Program:
        assert fee >= 0
        condition_list = []
        if primaries:
            for primary in primaries:
                condition_list.append(make_create_coin_condition(primary["puzzlehash"], primary["amount"]))
        if min_time > 0:
            condition_list.append(make_assert_absolute_seconds_exceeds_condition(min_time))
        if me:
            condition_list.append(make_assert_my_coin_id_condition(me["id"]))
        if fee:
            condition_list.append(make_reserve_fee_condition(fee))
        if coin_announcements:
            for announcement in coin_announcements:
                condition_list.append(make_create_coin_announcement(announcement))
        if coin_announcements_to_assert:
            for announcement_hash in coin_announcements_to_assert:
                condition_list.append(make_assert_coin_announcement(announcement_hash))
        if puzzle_announcements:
            for announcement in puzzle_announcements:
                condition_list.append(make_create_puzzle_announcement(announcement))
        if puzzle_announcements_to_assert:
            for announcement_hash in puzzle_announcements_to_assert:
                condition_list.append(make_assert_puzzle_announcement(announcement_hash))
        return solution_for_conditions(condition_list)
        
    async def TestTransaction():
        root_path = DEFAULT_ROOT_PATH
        config = load_config(root_path, "config.yaml")
        selected = config["selected_network"]
        prefix = config["network_overrides"]["config"][selected]["address_prefix"]
        log = logging.Logger
        db_connection = await aiosqlite.connect("/home/wang/.chives/mainnet/db/blockchain_v1_mainnet.sqlite")
        mnemonic = generate_mnemonic()
        mnemonic = "hen battle gauge crouch dose weasel blind noble ugly pull cruel mutual slight tragic bean rule once garage valley ritual still couple charge rich"
        entropy = bytes_from_mnemonic(mnemonic)
        seed = mnemonic_to_seed(mnemonic, "")
        seed_key = AugSchemeMPL.key_gen(seed)
        masterPublicKey = seed_key.get_g1()
        fingerprint = masterPublicKey.get_fingerprint()
        
        MapKeys = {}
        for i in range(10):
            primary_key = master_sk_to_wallet_sk(seed_key, uint32(i))
            public_key = primary_key.get_g1()
            puzzle_hash = create_puzzlehash_for_pk(public_key)
            address = encode_puzzle_hash(puzzle_hash, prefix)
            MapKeys[puzzle_hash] = public_key
            MapKeys[i] = puzzle_hash
            print(puzzle_hash)
        print(MapKeys)        
        
        # Get coin infor
        coin_name = "9d1cbc9cf8a5ad3883933fd05367562bb771ab5ef4cb6200b6b9acdb4b2c8117";
        newpuzzlehash = MapKeys[2]
        SendAmount = 0.01*100000000
        fee = 0
        cursor = await db_connection.execute("SELECT * from coin_record WHERE coin_name=?", (coin_name,))
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        # parent_coin_info puzzle_hash amount
        coin = Coin(bytes32(bytes.fromhex(row[6])), bytes32(bytes.fromhex(row[5])), uint64.from_bytes(row[7]))
        # print(coin)
        WallTypeValue = 0
        WallTypeId = 1
        WalletCoinRecord(
            coin, uint32(row[1]), uint32(row[2]), bool(row[3]), bool(row[4]), WalletType(WallTypeValue), WallTypeId
        )
        # select_coins
        select_coins: Set = set()
        select_coins.add(coin)
        
        spends: List[CoinSolution] = []
        primary_announcement_hash: Optional[bytes32] = None
        
        origin_id = None
        primaries: Optional[List[Dict]] = None
        for coin in select_coins:
            # log.info(f"coin from coins {coin}")
            # print(coin)
            print(coin)
            #puzzle: Program = await TesKeychain.puzzle_for_puzzle_hash(coin.puzzle_hash)
            public_key = MapKeys[puzzle_hash]
            assert public_key is not None
            puzzle: Program =  puzzle_for_pk(bytes(public_key))
            #print(public_key)
            #print(puzzle)
            
            change = coin.amount - SendAmount
            # Only one coin creates outputs
            if primary_announcement_hash is None and origin_id in (None, coin.name()):
                if primaries is None:
                    primaries = [{"puzzlehash": newpuzzlehash, "amount": SendAmount}]
                else:
                    primaries.append({"puzzlehash": newpuzzlehash, "amount": SendAmount})
                if change > 0:
                    # CHANGE 地址为第二个地址
                    change_puzzle_hash: bytes32 = MapKeys[1]
                    primaries.append({"puzzlehash": change_puzzle_hash, "amount": change})
                message_list: List[bytes32] = [c.name() for c in select_coins]
                print(message_list)
                print('#############################')
                for primary in primaries:
                    print(coin.name())
                    coinNew = Coin(coin.name(), primary["puzzlehash"], uint32(primary["amount"])).name()
                    message_list.append(coinNew)
                print('#############################')
                
                message: bytes32 = std_hash(b"".join(message_list))
                solution: Program = TesKeychain.make_solution(primaries=primaries, fee=fee, coin_announcements=[message])
                primary_announcement_hash = Announcement(coin.name(), message).name()
            else:
                solution = TesKeychain.make_solution(coin_announcements_to_assert=[primary_announcement_hash])

            spends.append(
                CoinSolution(
                    coin, SerializedProgram.from_bytes(bytes(puzzle)), SerializedProgram.from_bytes(bytes(solution))
                )
            )
            
        #coin_record: WalletCoinRecord = WalletCoinRecord(
        #    coin, height, uint32(0), False, farm_reward, wallet_type, wallet_id
        #)
        
        
        
# xcc1dr0leqc48k0k3ul7386ulxppf8ru5rmqx6gjffdsdff0tgxj4wqssewhcj
# 68dffc83153d9f68f3fe89f5cf982149c7ca0f60369124a5b06a52f5a0d2ab81
# COIN_NAME 7541233a21d81a443c5809680aca026029547108c091869ee8fb1ad3b09850e5
# COIN_NAME 6a5d959896271bbf01cb29c255cc9dfd33125a940676ec97b2da7decd56f5374
# COIN_NAME 7badb9975ec2b4634093a4e74ecd840c527b0fdc81a42d5758b48c770f428cd9
if __name__ == "__main__":    
    loop = asyncio.get_event_loop()
    loop.run_until_complete(TesKeychain.TestTransaction())
