from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional, Set, Tuple, cast

from chia_rs import AugSchemeMPL, G1Element, G2Element, PrivateKey
from typing_extensions import Unpack

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend, make_spend
from chia.types.signing_mode import CHIP_0002_SIGN_MESSAGE_PREFIX, SigningMode
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64, uint128
from chia.util.streamable import Streamable
from chia.wallet.coin_selection import select_coins
from chia.wallet.conditions import AssertCoinAnnouncement, Condition, CreateCoinAnnouncement, parse_timelock_info
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.derive_keys import (
    MAX_POOL_WALLETS,
    _derive_path,
    _derive_path_unhardened,
    master_sk_to_singleton_owner_sk,
)
from chia.wallet.payment import Payment
from chia.wallet.puzzles.clawback.metadata import ClawbackMetadata
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_offset,
    calculate_synthetic_secret_key,
    puzzle_for_pk,
    puzzle_hash_for_pk,
    puzzle_hash_for_synthetic_public_key,
    solution_for_conditions,
)
from chia.wallet.puzzles.puzzle_utils import make_create_coin_condition, make_reserve_fee_condition
from chia.wallet.signer_protocol import (
    PathHint,
    Signature,
    SignedTransaction,
    SigningInstructions,
    SigningResponse,
    Spend,
    SumHint,
    TransactionInfo,
)
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.puzzle_decorator import PuzzleDecoratorManager
from chia.wallet.util.transaction_type import CLAWBACK_INCOMING_TRANSACTION_TYPES, TransactionType
from chia.wallet.util.wallet_types import WalletIdentifier, WalletType
from chia.wallet.wallet_action_scope import WalletActionScope
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_protocol import GSTOptionalArgs, WalletProtocol
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

if TYPE_CHECKING:
    from chia.server.ws_connection import WSChiaConnection
    from chia.wallet.wallet_state_manager import WalletStateManager


class Wallet:
    if TYPE_CHECKING:
        _protocol_check: ClassVar[WalletProtocol[ClawbackMetadata]] = cast("Wallet", None)

    wallet_info: WalletInfo
    wallet_state_manager: WalletStateManager
    log: logging.Logger
    wallet_id: uint32

    @staticmethod
    async def create(
        wallet_state_manager: Any,
        info: WalletInfo,
        name: str = __name__,
    ) -> Wallet:
        self = Wallet()
        self.log = logging.getLogger(name)
        self.wallet_state_manager = wallet_state_manager
        self.wallet_id = info.id

        return self

    @property
    def cost_of_single_tx(self) -> int:
        return 11000000  # Estimate

    @property
    def max_send_quantity(self) -> int:
        # avoid full block TXs
        return int(self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM / 5 / self.cost_of_single_tx)

    async def get_max_spendable_coins(self, records: Optional[Set[WalletCoinRecord]] = None) -> Set[WalletCoinRecord]:
        spendable: List[WalletCoinRecord] = list(
            await self.wallet_state_manager.get_spendable_coins_for_wallet(self.id(), records)
        )
        spendable.sort(reverse=True, key=lambda record: record.coin.amount)
        return set(spendable[0 : min(len(spendable), self.max_send_quantity)])

    async def get_max_send_amount(self, records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        return uint128(sum(cr.coin.amount for cr in await self.get_max_spendable_coins()))

    @classmethod
    def type(cls) -> WalletType:
        return WalletType.STANDARD_WALLET

    def id(self) -> uint32:
        return self.wallet_id

    async def get_confirmed_balance(self, record_list: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        return await self.wallet_state_manager.get_confirmed_balance_for_wallet(self.id(), record_list)

    async def get_unconfirmed_balance(self, unspent_records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        return await self.wallet_state_manager.get_unconfirmed_balance(self.id(), unspent_records)

    async def get_spendable_balance(self, unspent_records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        spendable = await self.wallet_state_manager.get_confirmed_spendable_balance_for_wallet(
            self.id(), unspent_records
        )
        return spendable

    async def get_pending_change_balance(self) -> uint64:
        unconfirmed_tx: List[TransactionRecord] = await self.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(
            self.id()
        )
        addition_amount = 0

        for record in unconfirmed_tx:
            if record.type in CLAWBACK_INCOMING_TRANSACTION_TYPES:
                # We do not wish to consider clawback-able funds as pending change.
                # That is reserved for when the action to actually claw a tx back or forward is initiated.
                continue
            if not record.is_in_mempool():
                if record.spend_bundle is not None:
                    self.log.warning(
                        f"TransactionRecord SpendBundle ID: {record.spend_bundle.name()} not in mempool. "
                        f"(peer, included, error) list: {record.sent_to}"
                    )
                    continue
            our_spend = False
            for coin in record.removals:
                if await self.wallet_state_manager.does_coin_belong_to_wallet(coin, self.id()):
                    our_spend = True
                    break

            if our_spend is not True:
                continue

            for coin in record.additions:
                if await self.wallet_state_manager.does_coin_belong_to_wallet(coin, self.id()):
                    addition_amount += coin.amount

        return uint64(addition_amount)

    def require_derivation_paths(self) -> bool:
        return True

    def puzzle_for_pk(self, pubkey: G1Element) -> Program:
        return puzzle_for_pk(pubkey)

    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:
        return puzzle_hash_for_pk(pubkey)

    async def convert_puzzle_hash(self, puzzle_hash: bytes32) -> bytes32:
        return puzzle_hash  # Looks unimpressive, but it's more complicated in other wallets

    async def puzzle_for_puzzle_hash(self, puzzle_hash: bytes32) -> Program:
        public_key = await self.wallet_state_manager.get_public_key(puzzle_hash)
        return puzzle_for_pk(G1Element.from_bytes(public_key))

    async def get_new_puzzle(self) -> Program:
        dr = await self.wallet_state_manager.get_unused_derivation_record(self.id())
        puzzle = puzzle_for_pk(dr.pubkey)
        return puzzle

    async def get_puzzle(self, new: bool) -> Program:
        if new:
            return await self.get_new_puzzle()
        else:
            record: Optional[DerivationRecord] = (
                await self.wallet_state_manager.get_current_derivation_record_for_wallet(self.id())
            )
            if record is None:
                return await self.get_new_puzzle()  # pragma: no cover
            puzzle = puzzle_for_pk(record.pubkey)
            return puzzle

    async def get_puzzle_hash(self, new: bool) -> bytes32:
        if new:
            return await self.get_new_puzzlehash()
        else:
            record: Optional[DerivationRecord] = (
                await self.wallet_state_manager.get_current_derivation_record_for_wallet(self.id())
            )
            if record is None:
                return await self.get_new_puzzlehash()
            return record.puzzle_hash

    async def get_new_puzzlehash(self) -> bytes32:
        puzhash = (await self.wallet_state_manager.get_unused_derivation_record(self.id())).puzzle_hash
        return puzhash

    def make_solution(
        self,
        primaries: List[Payment],
        conditions: Tuple[Condition, ...] = tuple(),
        fee: uint64 = uint64(0),
    ) -> Program:
        assert fee >= 0
        condition_list: List[Any] = [condition.to_program() for condition in conditions]
        if len(primaries) > 0:
            for primary in primaries:
                condition_list.append(make_create_coin_condition(primary.puzzle_hash, primary.amount, primary.memos))
        if fee:
            condition_list.append(make_reserve_fee_condition(fee))

        return solution_for_conditions(condition_list)

    def add_condition_to_solution(self, condition: Program, solution: Program) -> Program:
        python_program = solution.as_python()
        python_program[1].append(condition)
        return Program.to(python_program)

    async def select_coins(
        self,
        amount: uint64,
        action_scope: WalletActionScope,
    ) -> Set[Coin]:
        """
        Returns a set of coins that can be used for generating a new transaction.
        Note: Must be called under wallet state manager lock
        """
        spendable_amount: uint128 = await self.get_spendable_balance()
        spendable_coins: List[WalletCoinRecord] = list(await self.get_max_spendable_coins())

        # Try to use coins from the store, if there isn't enough of "unused"
        # coins use change coins that are not confirmed yet
        unconfirmed_removals: Dict[bytes32, Coin] = await self.wallet_state_manager.unconfirmed_removals_for_wallet(
            self.id()
        )
        async with action_scope.use() as interface:
            coins = await select_coins(
                spendable_amount,
                action_scope.config.adjust_for_side_effects(interface.side_effects).tx_config.coin_selection_config,
                spendable_coins,
                unconfirmed_removals,
                self.log,
                uint128(amount),
            )
            interface.side_effects.selected_coins.extend([*coins])
        assert sum(c.amount for c in coins) >= amount
        return coins

    async def _generate_unsigned_transaction(
        self,
        amount: uint64,
        newpuzzlehash: bytes32,
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        origin_id: Optional[bytes32] = None,
        coins: Optional[Set[Coin]] = None,
        primaries_input: Optional[List[Payment]] = None,
        memos: Optional[List[bytes]] = None,
        negative_change_allowed: bool = False,
        puzzle_decorator_override: Optional[List[Dict[str, Any]]] = None,
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> List[CoinSpend]:
        """
        Generates a unsigned transaction in form of List(Puzzle, Solutions)
        Note: this must be called under a wallet state manager lock
        """
        decorator_manager: PuzzleDecoratorManager = self.wallet_state_manager.decorator_manager
        if puzzle_decorator_override is not None:
            decorator_manager = PuzzleDecoratorManager.create(puzzle_decorator_override)

        primaries = []
        if primaries_input is not None:
            primaries.extend(primaries_input)

        total_amount = amount + sum(primary.amount for primary in primaries) + fee
        total_balance = await self.get_spendable_balance()
        if coins is None:
            if total_amount > total_balance:
                raise ValueError(
                    f"Can't spend more than wallet balance: {total_balance} mojos, tried to spend: {total_amount} mojos"
                )
            coins = await self.select_coins(
                uint64(total_amount),
                action_scope,
            )

        assert len(coins) > 0
        self.log.info(f"coins is not None {coins}")
        spend_value = sum(coin.amount for coin in coins)
        self.log.info(f"spend_value is {spend_value} and total_amount is {total_amount}")
        change = spend_value - total_amount
        if negative_change_allowed:
            change = max(0, change)

        assert change >= 0

        spends: List[CoinSpend] = []
        primary_announcement: Optional[AssertCoinAnnouncement] = None

        # Check for duplicates
        all_primaries_list = [(p.puzzle_hash, p.amount) for p in primaries]
        if len(set(all_primaries_list)) != len(all_primaries_list):
            raise ValueError("Cannot create two identical coins")
        for coin in coins:
            # Only one coin creates outputs
            if origin_id in (None, coin.name()):
                origin_id = coin.name()
                inner_puzzle = await self.puzzle_for_puzzle_hash(coin.puzzle_hash)
                decorated_target_puzzle_hash = decorator_manager.decorate_target_puzzle_hash(
                    inner_puzzle, newpuzzlehash
                )
                target_primary: List[Payment] = []
                if memos is None:
                    memos = []
                memos = decorator_manager.decorate_memos(inner_puzzle, newpuzzlehash, memos)
                if (primaries_input is None and amount > 0) or primaries_input is not None:
                    primaries.append(Payment(decorated_target_puzzle_hash, amount, memos))
                    target_primary.append(Payment(newpuzzlehash, amount, memos))

                if change > 0:
                    if action_scope.config.tx_config.reuse_puzhash:
                        change_puzzle_hash: bytes32 = coin.puzzle_hash
                        for primary in primaries:
                            if change_puzzle_hash == primary.puzzle_hash and change == primary.amount:
                                # We cannot create two coins has same id, create a new puzhash for the change:
                                change_puzzle_hash = await self.get_new_puzzlehash()
                                break
                    else:
                        change_puzzle_hash = await self.get_new_puzzlehash()
                    primaries.append(Payment(change_puzzle_hash, uint64(change)))
                message_list: List[bytes32] = [c.name() for c in coins]
                for primary in primaries:
                    message_list.append(Coin(coin.name(), primary.puzzle_hash, primary.amount).name())
                message: bytes32 = std_hash(b"".join(message_list))
                puzzle: Program = await self.puzzle_for_puzzle_hash(coin.puzzle_hash)
                solution: Program = self.make_solution(
                    primaries=primaries,
                    fee=fee,
                    conditions=(*extra_conditions, CreateCoinAnnouncement(message)),
                )
                solution = decorator_manager.solve(inner_puzzle, target_primary, solution)
                primary_announcement = AssertCoinAnnouncement(asserted_id=coin.name(), asserted_msg=message)

                spends.append(
                    make_spend(
                        coin, SerializedProgram.from_bytes(bytes(puzzle)), SerializedProgram.from_bytes(bytes(solution))
                    )
                )
                break
        else:
            raise ValueError("origin_id is not in the set of selected coins")

        # Process the non-origin coins now that we have the primary announcement hash
        for coin in coins:
            if coin.name() == origin_id:
                continue
            puzzle = await self.puzzle_for_puzzle_hash(coin.puzzle_hash)
            solution = self.make_solution(primaries=[], conditions=(primary_announcement,))
            solution = decorator_manager.solve(puzzle, [], solution)
            spends.append(
                make_spend(
                    coin, SerializedProgram.from_bytes(bytes(puzzle)), SerializedProgram.from_bytes(bytes(solution))
                )
            )

        self.log.debug(f"Spends is {spends}")
        return spends

    async def sign_message(self, message: str, puzzle_hash: bytes32, mode: SigningMode) -> Tuple[G1Element, G2Element]:
        # CHIP-0002 message signing as documented at:
        # https://github.com/Chia-Network/chips/blob/80e4611fe52b174bf1a0382b9dff73805b18b8c6/CHIPs/chip-0002.md#signmessage
        private = await self.wallet_state_manager.get_private_key(puzzle_hash)
        synthetic_secret_key = calculate_synthetic_secret_key(private, DEFAULT_HIDDEN_PUZZLE_HASH)
        synthetic_pk = synthetic_secret_key.get_g1()
        if mode == SigningMode.CHIP_0002_HEX_INPUT:
            hex_message: bytes = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, bytes.fromhex(message))).get_tree_hash()
        elif mode == SigningMode.BLS_MESSAGE_AUGMENTATION_UTF8_INPUT:
            hex_message = bytes(message, "utf-8")
        elif mode == SigningMode.BLS_MESSAGE_AUGMENTATION_HEX_INPUT:
            hex_message = bytes.fromhex(message)
        else:
            hex_message = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, message)).get_tree_hash()
        return synthetic_pk, AugSchemeMPL.sign(synthetic_secret_key, hex_message)

    async def generate_signed_transaction(
        self,
        amount: uint64,
        puzzle_hash: bytes32,
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        coins: Optional[Set[Coin]] = None,
        primaries: Optional[List[Payment]] = None,
        memos: Optional[List[bytes]] = None,
        puzzle_decorator_override: Optional[List[Dict[str, Any]]] = None,
        extra_conditions: Tuple[Condition, ...] = tuple(),
        **kwargs: Unpack[GSTOptionalArgs],
    ) -> None:
        origin_id: Optional[bytes32] = kwargs.get("origin_id", None)
        negative_change_allowed: bool = kwargs.get("negative_change_allowed", False)
        """
        Use this to generate transaction.
        Note: this must be called under a wallet state manager lock
        The first output is (amount, puzzle_hash, memos), and the rest of the outputs are in primaries.
        """
        if primaries is None:
            non_change_amount = amount
        else:
            non_change_amount = uint64(amount + sum(p.amount for p in primaries))

        self.log.debug("Generating transaction for: %s %s %s", puzzle_hash, amount, repr(coins))
        transaction = await self._generate_unsigned_transaction(
            amount,
            puzzle_hash,
            action_scope,
            fee,
            origin_id,
            coins,
            primaries,
            memos,
            negative_change_allowed,
            puzzle_decorator_override=puzzle_decorator_override,
            extra_conditions=extra_conditions,
        )
        assert len(transaction) > 0
        spend_bundle = WalletSpendBundle(transaction, G2Element())

        now = uint64(int(time.time()))
        add_list: List[Coin] = list(spend_bundle.additions())
        rem_list: List[Coin] = list(spend_bundle.removals())

        output_amount = sum(a.amount for a in add_list) + fee
        input_amount = sum(r.amount for r in rem_list)
        if negative_change_allowed:
            assert output_amount >= input_amount
        else:
            assert output_amount == input_amount

        async with action_scope.use() as interface:
            interface.side_effects.transactions.append(
                TransactionRecord(
                    confirmed_at_height=uint32(0),
                    created_at_time=now,
                    to_puzzle_hash=puzzle_hash,
                    amount=uint64(non_change_amount),
                    fee_amount=uint64(fee),
                    confirmed=False,
                    sent=uint32(0),
                    spend_bundle=spend_bundle,
                    additions=add_list,
                    removals=rem_list,
                    wallet_id=self.id(),
                    sent_to=[],
                    trade_id=None,
                    type=uint32(TransactionType.OUTGOING_TX.value),
                    name=spend_bundle.name(),
                    memos=list(compute_memos(spend_bundle).items()),
                    valid_times=parse_timelock_info(extra_conditions),
                )
            )

    async def create_tandem_xch_tx(
        self,
        fee: uint64,
        action_scope: WalletActionScope,
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> None:
        chia_coins = await self.select_coins(fee, action_scope)
        await self.generate_signed_transaction(
            uint64(0),
            (await self.get_puzzle_hash(not action_scope.config.tx_config.reuse_puzhash)),
            action_scope,
            fee=fee,
            coins=chia_coins,
            extra_conditions=extra_conditions,
        )

    async def get_coins_to_offer(
        self,
        asset_id: Optional[bytes32],
        amount: uint64,
        action_scope: WalletActionScope,
    ) -> Set[Coin]:
        if asset_id is not None:
            raise ValueError(f"The standard wallet cannot offer coins with asset id {asset_id}")
        balance = await self.get_spendable_balance()
        if balance < amount:
            raise Exception(f"insufficient funds in wallet {self.id()}")
        # We need to sandbox this because this method isn't supposed to lock up the coins
        async with self.wallet_state_manager.new_action_scope(action_scope.config.tx_config) as sandbox:
            return await self.select_coins(amount, sandbox)

    # WSChiaConnection is only imported for type checking
    async def coin_added(
        self, coin: Coin, height: uint32, peer: WSChiaConnection, coin_data: Optional[Streamable]
    ) -> None:  # pylint: disable=used-before-assignment
        pass

    def get_name(self) -> str:
        return "Standard Wallet"

    async def match_hinted_coin(self, coin: Coin, hint: bytes32) -> bool:
        if hint == coin.puzzle_hash:
            wallet_identifier: Optional[WalletIdentifier] = (
                await self.wallet_state_manager.puzzle_store.get_wallet_identifier_for_puzzle_hash(coin.puzzle_hash)
            )
            if wallet_identifier is not None and wallet_identifier.id == self.id():
                return True
        return False

    async def sum_hint_for_pubkey(self, pk: bytes) -> Optional[SumHint]:
        pk_parsed: G1Element = G1Element.from_bytes(pk)
        dr: Optional[DerivationRecord] = await self.wallet_state_manager.puzzle_store.record_for_puzzle_hash(
            puzzle_hash_for_synthetic_public_key(pk_parsed)
        )
        if dr is None:
            return None
        return SumHint(
            [dr.pubkey.get_fingerprint().to_bytes(4, "big")],
            calculate_synthetic_offset(dr.pubkey, DEFAULT_HIDDEN_PUZZLE_HASH).to_bytes(32, "big"),
            pk,
        )

    async def path_hint_for_pubkey(self, pk: bytes) -> Optional[PathHint]:
        pk_parsed: G1Element = G1Element.from_bytes(pk)
        index: Optional[uint32] = await self.wallet_state_manager.puzzle_store.index_for_pubkey(pk_parsed)
        if index is None:
            index = await self.wallet_state_manager.puzzle_store.index_for_puzzle_hash(
                puzzle_hash_for_synthetic_public_key(pk_parsed)
            )
        root_pubkey: bytes = self.wallet_state_manager.root_pubkey.get_fingerprint().to_bytes(4, "big")
        if index is None:
            # Pool wallet may have a secret key here
            if self.wallet_state_manager.private_key is not None:
                for pool_wallet_index in range(MAX_POOL_WALLETS):
                    try_owner_sk = master_sk_to_singleton_owner_sk(
                        self.wallet_state_manager.private_key, uint32(pool_wallet_index)
                    )
                    if try_owner_sk.get_g1() == pk_parsed:
                        return PathHint(
                            root_pubkey,
                            [uint64(12381), uint64(8444), uint64(5), uint64(pool_wallet_index)],
                        )
            return None
        return PathHint(
            root_pubkey,
            [uint64(12381), uint64(8444), uint64(2), uint64(index)],
        )

    async def execute_signing_instructions(
        self, signing_instructions: SigningInstructions, partial_allowed: bool = False
    ) -> List[SigningResponse]:
        root_pubkey: G1Element = self.wallet_state_manager.root_pubkey
        pk_lookup: Dict[int, G1Element] = (
            {root_pubkey.get_fingerprint(): root_pubkey} if self.wallet_state_manager.private_key is not None else {}
        )
        sk_lookup: Dict[int, PrivateKey] = (
            {root_pubkey.get_fingerprint(): self.wallet_state_manager.get_master_private_key()}
            if self.wallet_state_manager.private_key is not None
            else {}
        )
        aggregate_responses_at_end: bool = True
        responses: List[SigningResponse] = []

        # TODO: expand path hints and sum hints recursively (a sum hint can give a new key to path hint)
        # Next, expand our pubkey set with path hints
        if self.wallet_state_manager.private_key is not None:
            for path_hint in signing_instructions.key_hints.path_hints:
                if int.from_bytes(path_hint.root_fingerprint, "big") != root_pubkey.get_fingerprint():
                    if not partial_allowed:
                        raise ValueError(f"No root pubkey for fingerprint {root_pubkey.get_fingerprint()}")
                    else:
                        continue
                else:
                    path = [int(step) for step in path_hint.path]
                    derive_child_sk = _derive_path(self.wallet_state_manager.get_master_private_key(), path)
                    derive_child_sk_unhardened = _derive_path_unhardened(
                        self.wallet_state_manager.get_master_private_key(), path
                    )
                    derive_child_pk = derive_child_sk.get_g1()
                    derive_child_pk_unhardened = derive_child_sk_unhardened.get_g1()
                    pk_lookup[derive_child_pk.get_fingerprint()] = derive_child_pk
                    pk_lookup[derive_child_pk_unhardened.get_fingerprint()] = derive_child_pk_unhardened
                    sk_lookup[derive_child_pk.get_fingerprint()] = derive_child_sk
                    sk_lookup[derive_child_pk_unhardened.get_fingerprint()] = derive_child_sk_unhardened

        # Next, expand our pubkey set with sum hints
        sum_hint_lookup: Dict[int, List[int]] = {}
        for sum_hint in signing_instructions.key_hints.sum_hints:
            fingerprints_we_have: List[int] = []
            for fingerprint in sum_hint.fingerprints:
                fingerprint_as_int = int.from_bytes(fingerprint, "big")
                if fingerprint_as_int not in pk_lookup:
                    if not partial_allowed:
                        raise ValueError(
                            "No pubkey found (or path hinted to) for "
                            f"fingerprint {int.from_bytes(fingerprint, 'big')}"
                        )
                    else:
                        aggregate_responses_at_end = False
                else:
                    fingerprints_we_have.append(fingerprint_as_int)

            # Add any synthetic offsets as keys we "have"
            offset_sk = PrivateKey.from_bytes(sum_hint.synthetic_offset)
            offset_pk = offset_sk.get_g1()
            pk_lookup[offset_pk.get_fingerprint()] = offset_pk
            sk_lookup[offset_pk.get_fingerprint()] = offset_sk
            final_pubkey: G1Element = G1Element.from_bytes(sum_hint.final_pubkey)
            final_fingerprint: int = final_pubkey.get_fingerprint()
            pk_lookup[final_fingerprint] = final_pubkey
            sum_hint_lookup[final_fingerprint] = [*fingerprints_we_have, offset_pk.get_fingerprint()]

        for target in signing_instructions.targets:
            pk_fingerprint: int = int.from_bytes(target.fingerprint, "big")
            if pk_fingerprint not in sk_lookup and pk_fingerprint not in sum_hint_lookup:
                if not partial_allowed:
                    raise ValueError(f"Pubkey {pk_fingerprint} not found (or path/sum hinted to)")
                else:
                    aggregate_responses_at_end = False
                    continue
            elif pk_fingerprint in sk_lookup:
                responses.append(
                    SigningResponse(
                        bytes(AugSchemeMPL.sign(sk_lookup[pk_fingerprint], target.message)),
                        target.hook,
                    )
                )
            else:  # Implicit if pk_fingerprint in sum_hint_lookup
                signatures: List[G2Element] = []
                for partial_fingerprint in sum_hint_lookup[pk_fingerprint]:
                    signatures.append(
                        AugSchemeMPL.sign(sk_lookup[partial_fingerprint], target.message, pk_lookup[pk_fingerprint])
                    )
                if partial_allowed:
                    # In multisig scenarios, we return everything as a component signature
                    for sig in signatures:
                        responses.append(
                            SigningResponse(
                                bytes(sig),
                                target.hook,
                            )
                        )
                else:
                    # In the scenario where we are the only signer, we can collapse many responses into one
                    responses.append(
                        SigningResponse(
                            bytes(AugSchemeMPL.aggregate(signatures)),
                            target.hook,
                        )
                    )

        # If we have the full set of signing responses for the instructions, aggregate them as much as possible
        if aggregate_responses_at_end:
            new_responses: List[SigningResponse] = []
            grouped_responses: Dict[bytes32, List[SigningResponse]] = {}
            for response in responses:
                grouped_responses.setdefault(response.hook, [])
                grouped_responses[response.hook].append(response)
            for hook, group in grouped_responses.items():
                new_responses.append(
                    SigningResponse(
                        bytes(AugSchemeMPL.aggregate([G2Element.from_bytes(res.signature) for res in group])),
                        hook,
                    )
                )
            responses = new_responses

        return responses

    async def apply_signatures(
        self, spends: List[Spend], signing_responses: List[SigningResponse]
    ) -> SignedTransaction:
        signing_responses_set = set(signing_responses)
        return SignedTransaction(
            TransactionInfo(spends),
            [
                Signature(
                    "bls_12381_aug_scheme",
                    bytes(
                        AugSchemeMPL.aggregate(
                            [
                                G2Element.from_bytes(signing_response.signature)
                                for signing_response in signing_responses_set
                            ]
                        )
                    ),
                )
            ],
        )
