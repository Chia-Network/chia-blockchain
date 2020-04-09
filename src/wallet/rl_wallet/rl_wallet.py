import logging

# RLWallet is subclass of Wallet
from binascii import hexlify
from dataclasses import dataclass
from secrets import token_bytes
from typing import Dict, Optional, List, Tuple, Any

import clvm
import json
from blspy import ExtendedPrivateKey
from clvm_tools import binutils

from src.server.server import ChiaServer
from src.types.BLSSignature import BLSSignature
from src.types.coin import Coin
from src.types.coin_solution import CoinSolution
from src.types.program import Program
from src.types.spend_bundle import SpendBundle
from src.types.sized_bytes import bytes32
from src.util.ints import uint64, uint32
from src.util.streamable import streamable, Streamable
from src.wallet.rl_wallet.rl_wallet_puzzles import (
    rl_puzzle_for_pk,
    rl_make_aggregation_puzzle,
    rl_make_aggregation_solution,
    rl_make_solution_mode_2,
    make_clawback_solution,
    solution_for_rl,
)
from src.wallet.util.wallet_types import WalletType
from src.wallet.wallet import Wallet
from src.wallet.wallet_coin_record import WalletCoinRecord
from src.wallet.wallet_info import WalletInfo
from src.wallet.derivation_record import DerivationRecord


@dataclass(frozen=True)
@streamable
class RLInfo(Streamable):
    type: str
    admin_pubkey: Optional[bytes]
    user_pubkey: Optional[bytes]
    limit: Optional[uint64]
    interval: Optional[uint64]
    rl_origin: Optional[Coin]
    rl_origin_id: Optional[bytes32]
    rl_puzzle_hash: Optional[bytes32]


class RLWallet:
    private_key: ExtendedPrivateKey
    key_config: Dict
    config: Dict
    server: Optional[ChiaServer]
    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    rl_coin_record: WalletCoinRecord
    rl_info: RLInfo
    standard_wallet: Wallet

    @staticmethod
    async def create_rl_admin(
        config: Dict,
        key_config: Dict,
        wallet_state_manager: Any,
        wallet: Wallet,
        name: str = None,
    ):
        unused: Optional[
            uint32
        ] = await wallet_state_manager.puzzle_store.get_unused_derivation_path()
        if unused is None:
            await wallet_state_manager.create_more_puzzle_hashes()
        unused = await wallet_state_manager.puzzle_store.get_unused_derivation_path()
        assert unused is not None

        sk_hex = key_config["wallet_sk"]
        private_key = ExtendedPrivateKey.from_bytes(bytes.fromhex(sk_hex))
        pubkey_bytes: bytes = bytes(private_key.public_child(unused).get_public_key())

        rl_info = RLInfo("admin", pubkey_bytes, None, None, None, None, None, None)
        info_as_string = json.dumps(rl_info.to_json_dict())
        await wallet_state_manager.user_store.create_wallet(
            "RL Admin", WalletType.RATE_LIMITED, info_as_string
        )
        wallet_info = await wallet_state_manager.user_store.get_last_wallet()
        if wallet_info is None:
            raise

        await wallet_state_manager.puzzle_store.add_derivation_paths(
            [
                DerivationRecord(
                    unused,
                    token_bytes(),
                    pubkey_bytes,
                    WalletType.RATE_LIMITED,
                    wallet_info.id,
                )
            ]
        )
        await wallet_state_manager.puzzle_store.set_used_up_to(unused)

        self = await RLWallet.create(
            config, key_config, wallet_state_manager, wallet_info, wallet, name
        )
        return self

    @staticmethod
    async def create_rl_user(
        config: Dict,
        key_config: Dict,
        wallet_state_manager: Any,
        wallet: Wallet,
        name: str = None,
    ):
        async with wallet_state_manager.puzzle_store.lock:
            unused: Optional[
                uint32
            ] = await wallet_state_manager.puzzle_store.get_unused_derivation_path()
            if unused is None:
                await wallet_state_manager.create_more_puzzle_hashes()
            unused = (
                await wallet_state_manager.puzzle_store.get_unused_derivation_path()
            )
            assert unused is not None

            sk_hex = key_config["wallet_sk"]
            private_key = ExtendedPrivateKey.from_bytes(bytes.fromhex(sk_hex))
            pubkey_bytes: bytes = bytes(
                private_key.public_child(unused).get_public_key()
            )

            rl_info = RLInfo("user", None, pubkey_bytes, None, None, None, None, None)
            info_as_string = json.dumps(rl_info.to_json_dict())
            await wallet_state_manager.user_store.create_wallet(
                "RL User", WalletType.RATE_LIMITED, info_as_string
            )
            wallet_info = await wallet_state_manager.user_store.get_last_wallet()
            if wallet_info is None:
                raise

            self = await RLWallet.create(
                config, key_config, wallet_state_manager, wallet_info, wallet, name
            )

            await wallet_state_manager.puzzle_store.add_derivation_paths(
                [
                    DerivationRecord(
                        unused,
                        token_bytes(),
                        pubkey_bytes,
                        WalletType.RATE_LIMITED,
                        wallet_info.id,
                    )
                ]
            )
            await wallet_state_manager.puzzle_store.set_used_up_to(unused)

        return self

    @staticmethod
    async def create(
        config: Dict,
        key_config: Dict,
        wallet_state_manager: Any,
        info: WalletInfo,
        wallet: Wallet,
        name: str = None,
    ):
        self = RLWallet()
        self.config = config
        self.key_config = key_config
        sk_hex = self.key_config["wallet_sk"]
        self.private_key = ExtendedPrivateKey.from_bytes(bytes.fromhex(sk_hex))
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager

        self.server = None

        self.wallet_info = info
        self.standard_wallet = wallet
        self.rl_info = RLInfo.from_json_dict(json.loads(info.data))
        return self

    async def admin_create_coin(
        self, interval: uint64, limit: uint64, user_pubkey: str, amount: uint64
    ) -> bool:
        coins = await self.standard_wallet.select_coins(amount)
        if coins is None:
            return False

        origin = coins.copy().pop()
        origin_id = origin.name()
        if user_pubkey.startswith("0x"):
            user_pubkey = user_pubkey[2:]

        user_pubkey_bytes = bytes.fromhex(user_pubkey)

        assert self.rl_info.admin_pubkey is not None

        rl_puzzle = rl_puzzle_for_pk(
            pubkey=user_pubkey_bytes,
            rate_amount=limit,
            interval_time=interval,
            origin_id=origin_id,
            clawback_pk=self.rl_info.admin_pubkey,
        )

        rl_puzzle_hash = rl_puzzle.get_hash()
        index = await self.wallet_state_manager.puzzle_store.index_for_pubkey(
            self.rl_info.admin_pubkey.hex()
        )

        assert index is not None
        record = DerivationRecord(
            index,
            rl_puzzle_hash,
            self.rl_info.admin_pubkey,
            WalletType.RATE_LIMITED,
            self.wallet_info.id,
        )
        await self.wallet_state_manager.puzzle_store.add_derivation_paths([record])

        spend_bundle = await self.standard_wallet.generate_signed_transaction(
            amount, rl_puzzle_hash, uint64(0), origin_id, coins
        )
        if spend_bundle is None:
            return False

        await self.standard_wallet.push_transaction(spend_bundle)
        new_rl_info = RLInfo(
            "admin",
            self.rl_info.admin_pubkey,
            user_pubkey_bytes,
            limit,
            interval,
            origin,
            origin.name(),
            rl_puzzle_hash,
        )

        data_str = json.dumps(new_rl_info.to_json_dict())
        new_wallet_info = WalletInfo(
            self.wallet_info.id, self.wallet_info.name, self.wallet_info.type, data_str
        )
        await self.wallet_state_manager.user_store.update_wallet(new_wallet_info)
        self.wallet_info = new_wallet_info
        self.rl_info = new_rl_info
        return True

    async def set_user_info(
        self, interval: uint64, limit: uint64, origin_id: str, admin_pubkey: str
    ):

        if admin_pubkey.startswith("0x"):
            admin_pubkey = admin_pubkey[2:]
        admin_pubkey_bytes = bytes.fromhex(admin_pubkey)

        assert self.rl_info.user_pubkey is not None

        rl_puzzle = rl_puzzle_for_pk(
            pubkey=self.rl_info.user_pubkey,
            rate_amount=limit,
            interval_time=interval,
            origin_id=bytes.fromhex(origin_id),
            clawback_pk=admin_pubkey_bytes,
        )

        rl_puzzle_hash = rl_puzzle.get_hash()
        new_rl_info = RLInfo(
            "admin",
            admin_pubkey_bytes,
            self.rl_info.user_pubkey,
            limit,
            interval,
            None,
            origin_id,
            rl_puzzle_hash,
        )
        rl_puzzle_hash = rl_puzzle.get_hash()

        index = await self.wallet_state_manager.puzzle_store.index_for_pubkey(
            self.rl_info.user_pubkey.hex()
        )
        assert index is not None
        record = DerivationRecord(
            index,
            rl_puzzle_hash,
            self.rl_info.user_pubkey,
            WalletType.RATE_LIMITED,
            self.wallet_info.id,
        )
        await self.wallet_state_manager.puzzle_store.add_derivation_paths([record])

        data_str = json.dumps(new_rl_info.to_json_dict())
        new_wallet_info = WalletInfo(
            self.wallet_info.id, self.wallet_info.name, self.wallet_info.type, data_str
        )
        await self.wallet_state_manager.user_store.update_wallet(new_wallet_info)
        self.wallet_info = new_wallet_info
        self.rl_info = new_rl_info

    def rl_available_balance(self):
        if self.rl_coin_record is None:
            return 0
        lca_header_hash = self.wallet_state_manager.lca
        lca = self.wallet_state_manager.block_records[lca_header_hash]
        height = lca.height
        unlocked = int(
            (
                (height - self.rl_coin_record.confirmed_block_index)
                / self.rl_info.interval
            )
            * int(self.rl_info.limit)
        )
        total_amount = self.rl_coin_record.amount
        available_amount = min(unlocked, total_amount)
        return available_amount

    async def get_confirmed_balance(self) -> uint64:
        self.log.info(f"wallet_id balance {self.wallet_info.id}")
        return await self.wallet_state_manager.get_confirmed_balance_for_wallet(
            self.wallet_info.id
        )

    async def get_unconfirmed_balance(self) -> uint64:
        return await self.wallet_state_manager.get_unconfirmed_balance(
            self.wallet_info.id
        )

    async def can_generate_rl_puzzle_hash(self, hash):
        return await self.wallet_state_manager.puzzle_store.puzzle_hash_exists(hash)

    async def get_keys(self, puzzle_hash: bytes32):
        """
        Returns keys for puzzle_hash.
        """
        index_for_puzzlehash = await self.wallet_state_manager.puzzle_store.index_for_puzzle_hash(
            puzzle_hash
        )
        if index_for_puzzlehash == -1:
            raise
        pubkey = self.private_key.public_child(index_for_puzzlehash).get_public_key()
        private = self.private_key.private_child(index_for_puzzlehash).get_private_key()
        return pubkey, private

    async def get_keys_pk(self, clawback_pubkey: bytes):
        """
        Return keys for pubkey
        """
        index_for_pubkey = await self.wallet_state_manager.puzzle_store.index_for_pubkey(
            clawback_pubkey.hex()
        )
        if index_for_pubkey == -1:
            raise
        pubkey = self.private_key.public_child(index_for_pubkey).get_public_key()
        private = self.private_key.private_child(index_for_pubkey).get_private_key()
        return pubkey, private

    async def get_rl_coin(self) -> Optional[Coin]:
        rl_coins = await self.wallet_state_manager.wallet_store.get_coin_records_by_puzzle_hash(
            self.rl_info.rl_puzzle_hash
        )
        for coin_record in rl_coins:
            if coin_record.spent is False:
                return coin_record.coin

        return None

    async def get_rl_parent(self) -> Optional[Coin]:
        rl_parent_id = self.rl_coin_record.coin.parent_coin_info
        rl_parent = await self.wallet_state_manager.wallet_store.get_coin_record_by_coin_id(
            rl_parent_id
        )
        if rl_parent is None:
            return None

        return rl_parent.coin

    async def rl_generate_unsigned_transaction(self, to_puzzlehash, amount):
        spends = []
        coin = self.rl_coin_record.coin
        puzzle_hash = coin.puzzle_hash
        pubkey, secretkey = await self.get_keys(puzzle_hash)
        rl_parent: Coin = await self.get_rl_parent()

        puzzle = rl_puzzle_for_pk(
            bytes(pubkey),
            self.rl_info.interval,
            self.rl_info.limit,
            self.rl_info.rl_origin.name(),
            self.rl_info.rl_clawback_pk,
        )

        solution = solution_for_rl(
            coin.parent_coin_info,
            puzzle_hash,
            coin.amount,
            to_puzzlehash,
            amount,
            rl_parent.parent_coin_info,
            rl_parent.amount,
            None,
            None,
        )

        spends.append((puzzle, CoinSolution(coin, solution)))
        return spends

    def rl_generate_signed_transaction(self, amount, to_puzzle_hash):
        if amount > self.rl_coin_record.coin.amount:
            return None
        transaction = self.rl_generate_unsigned_transaction(to_puzzle_hash, amount)
        return self.rl_sign_transaction(transaction)

    async def rl_sign_transaction(self, spends: List[Tuple[Program, CoinSolution]]):
        sigs = []
        for puzzle, solution in spends:
            pubkey, secretkey = await self.get_keys(solution.coin.puzzle_hash)
            signature = secretkey.sign(Program(solution.solution).get_hash())
            sigs.append(signature)

        aggsig = BLSSignature.aggregate(sigs)

        solution_list: List[CoinSolution] = []
        for puzzle, coin_solution in spends:
            solution_list.append(
                CoinSolution(
                    coin_solution.coin, clvm.to_sexp_f([puzzle, coin_solution.solution])
                )
            )

        spend_bundle = SpendBundle(solution_list, aggsig)
        return spend_bundle

    def generate_unsigned_clawback_transaction(
        self, clawback_coin: Coin, clawback_puzzle_hash: bytes32
    ):
        if (
            self.rl_info.limit is None
            or self.rl_info.interval is None
            or self.rl_info.user_pubkey is None
            or self.rl_info.admin_pubkey is None
        ):
            raise
        spends = []
        coin = clawback_coin
        puzzle = rl_puzzle_for_pk(
            self.rl_info.user_pubkey,
            self.rl_info.limit,
            self.rl_info.interval,
            self.rl_info.rl_origin,
            self.rl_info.admin_pubkey,
        )
        solution = make_clawback_solution(clawback_puzzle_hash, clawback_coin.amount)
        spends.append((puzzle, CoinSolution(coin, solution)))
        return spends

    async def sign_clawback_transaction(
        self, spends: List[Tuple[Program, CoinSolution]], clawback_pubkey
    ):
        sigs = []
        for puzzle, solution in spends:
            pubkey, secretkey = await self.get_keys_pk(clawback_pubkey)
            signature = secretkey.sign(Program(solution.solution).get_hash())
            sigs.append(signature)
        aggsig = BLSSignature.aggregate(sigs)
        solution_list = []
        for puzzle, coin_solution in spends:
            solution_list.append(
                CoinSolution(
                    coin_solution.coin, clvm.to_sexp_f([puzzle, coin_solution.solution])
                )
            )

        spend_bundle = SpendBundle(solution_list, aggsig)
        return spend_bundle

    async def clawback_rl_coin(self, clawback_puzzle_hash: bytes32):
        rl_coin = await self.get_rl_coin()
        if rl_coin is None:
            raise
        transaction = self.generate_unsigned_clawback_transaction(
            rl_coin, clawback_puzzle_hash
        )
        if transaction is None:
            return None
        return self.sign_clawback_transaction(transaction, self.rl_info.admin_pubkey)

    # This is for using the AC locked coin and aggregating it into wallet - must happen in same block as RL Mode 2
    async def rl_generate_signed_aggregation_transaction(
        self, rl_info: RLInfo, consolidating_coin: Coin, rl_parent: Coin, rl_coin: Coin
    ):
        if (
            rl_info.limit is None
            or rl_info.interval is None
            or rl_info.limit is None
            or rl_info.interval is None
            or rl_info.user_pubkey is None
            or rl_info.admin_pubkey is None
        ):
            raise

        list_of_coinsolutions = []

        pubkey, secretkey = await self.get_keys(self.rl_coin_record.coin.puzzle_hash)
        # Spend wallet coin
        puzzle = rl_puzzle_for_pk(
            rl_info.user_pubkey,
            rl_info.limit,
            rl_info.interval,
            rl_info.rl_origin,
            rl_info.admin_pubkey,
        )

        solution = rl_make_solution_mode_2(
            rl_coin.puzzle_hash,
            consolidating_coin.parent_coin_info,
            consolidating_coin.puzzle_hash,
            consolidating_coin.amount,
            rl_coin.parent_coin_info,
            rl_coin.amount,
            rl_parent.amount,
            rl_parent.parent_coin_info,
        )

        signature = secretkey.sign(solution.get_hash())
        list_of_coinsolutions.append(
            CoinSolution(self.rl_coin_record.coin, clvm.to_sexp_f([puzzle, solution]))
        )

        # Spend consolidating coin
        puzzle = rl_make_aggregation_puzzle(self.rl_coin_record.coin.puzzle_hash)
        solution = rl_make_aggregation_solution(
            consolidating_coin.name(),
            self.rl_coin_record.coin.parent_coin_info,
            self.rl_coin_record.coin.amount,
        )
        list_of_coinsolutions.append(
            CoinSolution(consolidating_coin, clvm.to_sexp_f([puzzle, solution]))
        )
        # Spend lock
        puzstring = (
            "(r (c (q 0x"
            + hexlify(consolidating_coin.name()).decode("ascii")
            + ") (q ())))"
        )

        puzzle = Program(binutils.assemble(puzstring))
        solution = Program(binutils.assemble("()"))
        list_of_coinsolutions.append(
            CoinSolution(
                Coin(self.rl_coin_record.coin, puzzle.get_hash(), uint64(0)),
                clvm.to_sexp_f([puzzle, solution]),
            )
        )

        aggsig = BLSSignature.aggregate([signature])

        return SpendBundle(list_of_coinsolutions, aggsig)

    def rl_get_aggregation_puzzlehash(self, wallet_puzzle):
        puzzle_hash = rl_make_aggregation_puzzle(wallet_puzzle).get_hash()

        return puzzle_hash
