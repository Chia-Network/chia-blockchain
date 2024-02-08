from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from chia_rs import G1Element, G2Element
from typing_extensions import Unpack

from chia.protocols.wallet_protocol import CoinState
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.signing_mode import SigningMode
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint32, uint64, uint128
from chia.wallet.coin_selection import select_coins
from chia.wallet.conditions import Condition, CreateCoin, CreatePuzzleAnnouncement, parse_timelock_info
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.payment import Payment
from chia.wallet.puzzles.p2_conditions import puzzle_for_conditions, solution_for_conditions
from chia.wallet.signer_protocol import (
    PathHint,
    SignedTransaction,
    SigningInstructions,
    SigningResponse,
    Spend,
    SumHint,
)
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.compute_hints import compute_spend_hints_and_additions
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.tx_config import CoinSelectionConfig, TXConfig
from chia.wallet.util.wallet_sync_utils import fetch_coin_spend
from chia.wallet.vault.vault_drivers import (
    construct_p2_delegated_secp,
    construct_secp_message,
    construct_vault_merkle_tree,
    get_p2_singleton_puzzle,
    get_p2_singleton_puzzle_hash,
    get_recovery_finish_puzzle,
    get_recovery_inner_puzzle,
    get_recovery_puzzle,
    get_recovery_solution,
    get_vault_full_puzzle,
    get_vault_full_solution,
    get_vault_hidden_puzzle_with_index,
    get_vault_inner_puzzle,
    get_vault_inner_puzzle_hash,
    get_vault_inner_solution,
    get_vault_proof,
)
from chia.wallet.vault.vault_info import RecoveryInfo, VaultInfo
from chia.wallet.vault.vault_root import VaultRoot
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_protocol import GSTOptionalArgs


class Vault(Wallet):
    @staticmethod
    async def create(
        wallet_state_manager: Any,
        info: WalletInfo,
        name: str = __name__,
    ) -> Vault:
        self = Vault()
        self.wallet_state_manager = wallet_state_manager
        self.wallet_info = info
        self.wallet_id = info.id
        self.log = logging.getLogger(name)
        return self

    async def get_new_puzzle(self) -> Program:
        dr = await self.wallet_state_manager.get_unused_derivation_record(self.id())
        hidden_puzzle_hash = get_vault_hidden_puzzle_with_index(dr.index).get_tree_hash()
        puzzle = get_vault_inner_puzzle(
            self.vault_info.pubkey,
            self.wallet_state_manager.constants.GENESIS_CHALLENGE,
            hidden_puzzle_hash,
            self.recovery_info.bls_pk if self.vault_info.is_recoverable else None,
            self.recovery_info.timelock if self.vault_info.is_recoverable else None,
        )
        return puzzle

    async def get_new_puzzlehash(self) -> bytes32:
        puzzle = await self.get_new_puzzle()
        return puzzle.get_tree_hash()

    async def generate_signed_transaction(
        self,
        amount: uint64,
        puzzle_hash: bytes32,
        tx_config: TXConfig,
        fee: uint64 = uint64(0),
        coins: Optional[Set[Coin]] = None,
        primaries: Optional[List[Payment]] = None,
        memos: Optional[List[bytes]] = None,
        puzzle_decorator_override: Optional[List[Dict[str, Any]]] = None,
        extra_conditions: Tuple[Condition, ...] = tuple(),
        **kwargs: Unpack[GSTOptionalArgs],
    ) -> List[TransactionRecord]:
        raise NotImplementedError("vault wallet")

    async def generate_p2_singleton_spends(
        self,
        primaries: List[Payment],
        tx_config: TXConfig,
        fee: uint64 = uint64(0),
        coins: Optional[Set[Coin]] = None,
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> List[CoinSpend]:
        total_amount = (
            sum(primary.amount for primary in primaries)
            + fee
            + sum(c.amount for c in extra_conditions if isinstance(c, CreateCoin))
        )
        total_balance = await self.get_spendable_balance()
        if coins is None:
            if total_amount > total_balance:
                raise ValueError(
                    f"Can't spend more than wallet balance: {total_balance} mojos, tried to spend: {total_amount} mojos"
                )
            coins = await self.select_coins(
                uint64(total_amount),
                tx_config.coin_selection_config,
            )
        assert len(coins) > 0
        spend_value = sum([coin.amount for coin in coins])
        change = spend_value - total_amount
        assert change >= 0
        if change > 0:
            change_puzzle_hash: bytes32 = next(iter(coins)).puzzle_hash
            primaries.append(Payment(change_puzzle_hash, uint64(change)))

        spends: List[CoinSpend] = []

        # Check for duplicates
        all_primaries_list = [(p.puzzle_hash, p.amount) for p in primaries]
        if len(set(all_primaries_list)) != len(all_primaries_list):
            raise ValueError("Cannot create two identical coins")

        p2_singleton_puzzle: Program = get_p2_singleton_puzzle(self.vault_info.launcher_coin_id)
        serialized_puzzle: SerializedProgram = SerializedProgram.from_bytes(bytes(p2_singleton_puzzle))

        for coin in coins:
            p2_singleton_solution: Program = Program.to([self.vault_info.inner_puzzle_hash, coin.name()])
            spends.append(
                CoinSpend(coin, serialized_puzzle, SerializedProgram.from_bytes(bytes(p2_singleton_solution)))
            )

        return spends

    async def generate_unsigned_vault_spend(
        self,
        primaries: List[Payment],
        p2_spends: List[CoinSpend],
        memos: Optional[List[bytes]] = None,
        fee: uint64 = uint64(0),
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> Tuple[bytes, Program, Program]:
        total_amount = (
            sum(primary.amount for primary in primaries)
            + fee
            + sum(c.amount for c in extra_conditions if isinstance(c, CreateCoin))
        )
        coins = [spend.coin for spend in p2_spends]
        spend_value = sum([coin.amount for coin in coins])
        change = spend_value - total_amount
        assert change >= 0
        if change > 0:
            change_puzzle_hash: bytes32 = get_p2_singleton_puzzle_hash(self.vault_info.launcher_coin_id)
            primaries.append(Payment(change_puzzle_hash, uint64(change)))

        conditions = [primary.as_condition() for primary in primaries]
        next_puzzle_hash = await self.get_new_puzzlehash()
        # TODO: should the vault inner puz create this condition?
        recreate_vault_condition = CreateCoin(
            next_puzzle_hash, uint64(self.vault_info.coin.amount), memos=[next_puzzle_hash]
        ).to_program()
        conditions.append(recreate_vault_condition)
        announcements = [CreatePuzzleAnnouncement(spend.coin.name()).to_program() for spend in p2_spends]
        conditions.extend(announcements)

        delegated_puzzle = puzzle_for_conditions(conditions)
        delegated_solution = solution_for_conditions(conditions)

        message_to_sign = construct_secp_message(
            delegated_puzzle.get_tree_hash(),
            self.vault_info.coin.name(),
            self.wallet_state_manager.constants.GENESIS_CHALLENGE,
            self.vault_info.hidden_puzzle_hash,
        )

        return message_to_sign, delegated_puzzle, delegated_solution

    async def generate_signed_vault_spend(
        self,
        signed_message: bytes,
        delegated_puzzle: Program,
        delegated_solution: Program,
        p2_spends: List[CoinSpend],
        primaries: List[Payment],
        fee: uint64 = uint64(0),
    ) -> List[TransactionRecord]:
        secp_puzzle = construct_p2_delegated_secp(
            self.vault_info.pubkey,
            self.wallet_state_manager.constants.GENESIS_CHALLENGE,
            self.vault_info.hidden_puzzle_hash,
        )
        vault_inner_puzzle = get_vault_inner_puzzle(
            self.vault_info.pubkey,
            self.wallet_state_manager.constants.GENESIS_CHALLENGE,
            self.vault_info.hidden_puzzle_hash,
            self.recovery_info.bls_pk if self.vault_info.is_recoverable else None,
            self.recovery_info.timelock if self.vault_info.is_recoverable else None,
        )
        secp_solution = Program.to(
            [
                delegated_puzzle,
                delegated_solution,
                signed_message,
                self.vault_info.coin.name(),
            ]
        )
        if self.vault_info.is_recoverable:
            recovery_puzzle_hash = get_recovery_puzzle(
                secp_puzzle.get_tree_hash(),
                self.recovery_info.bls_pk if self.vault_info.is_recoverable else None,
                self.recovery_info.timelock if self.vault_info.is_recoverable else None,
            ).get_tree_hash()
            merkle_tree = construct_vault_merkle_tree(secp_puzzle.get_tree_hash(), recovery_puzzle_hash)
        else:
            merkle_tree = construct_vault_merkle_tree(secp_puzzle.get_tree_hash())
        proof = get_vault_proof(merkle_tree, secp_puzzle.get_tree_hash())
        vault_inner_solution = get_vault_inner_solution(secp_puzzle, secp_solution, proof)

        full_puzzle = get_vault_full_puzzle(self.vault_info.launcher_coin_id, vault_inner_puzzle)
        full_solution = get_vault_full_solution(
            self.vault_info.lineage_proof,
            uint64(self.vault_info.coin.amount),
            vault_inner_solution,
        )

        vault_spend = CoinSpend(self.vault_info.coin, full_puzzle, full_solution)
        all_spends = [*p2_spends, vault_spend]
        spend_bundle = SpendBundle(all_spends, G2Element())

        amount = uint64(sum([payment.amount for payment in primaries]))
        target_puzzle_hash = primaries[0].puzzle_hash

        tx_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=target_puzzle_hash,
            amount=amount,
            fee_amount=fee,
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.id(),
            sent_to=[],
            memos=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=spend_bundle.name(),
            valid_times=parse_timelock_info(tuple()),
        )
        await self.wallet_state_manager.add_pending_transactions([tx_record], sign=False)
        return [tx_record]

    def puzzle_for_pk(self, pubkey: G1Element) -> Program:
        raise NotImplementedError("vault wallet")

    async def puzzle_for_puzzle_hash(self, puzzle_hash: bytes32) -> Program:
        raise NotImplementedError("vault wallet")

    async def sign_message(self, message: str, puzzle_hash: bytes32, mode: SigningMode) -> Tuple[G1Element, G2Element]:
        raise NotImplementedError("vault wallet")

    async def get_puzzle_hash(self, new: bool) -> bytes32:
        if new:
            return await self.get_new_puzzlehash()
        else:
            record: Optional[
                DerivationRecord
            ] = await self.wallet_state_manager.get_current_derivation_record_for_wallet(self.id())
            if record is None:
                return await self.get_new_puzzlehash()
            return record.puzzle_hash

    async def apply_signatures(
        self, spends: List[Spend], signing_responses: List[SigningResponse]
    ) -> SignedTransaction:
        raise NotImplementedError("vault wallet")

    async def execute_signing_instructions(
        self, signing_instructions: SigningInstructions, partial_allowed: bool = False
    ) -> List[SigningResponse]:
        raise NotImplementedError("vault wallet")

    async def path_hint_for_pubkey(self, pk: bytes) -> Optional[PathHint]:
        raise NotImplementedError("vault wallet")

    async def sum_hint_for_pubkey(self, pk: bytes) -> Optional[SumHint]:
        raise NotImplementedError("vault wallet")

    def make_solution(
        self,
        primaries: List[Payment],
        conditions: Tuple[Condition, ...] = tuple(),
        fee: uint64 = uint64(0),
    ) -> Program:
        raise NotImplementedError("vault wallet")

    async def get_puzzle(self, new: bool) -> Program:
        if new:
            return await self.get_new_puzzle()
        else:
            record: Optional[
                DerivationRecord
            ] = await self.wallet_state_manager.get_current_derivation_record_for_wallet(self.id())
            if record is None:
                return await self.get_new_puzzle()
            puzzle = construct_p2_delegated_secp(
                record.pubkey, self.wallet_state_manager.constants.GENESIS_CHALLENGE, record.puzzle_hash
            )
            return puzzle

    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:
        raise ValueError("This won't work")

    def require_derivation_paths(self) -> bool:
        if getattr(self, "vault_info", None):
            return True
        return False

    async def match_hinted_coin(self, coin: Coin, hint: bytes32) -> bool:
        raise NotImplementedError("vault wallet")

    def handle_own_derivation(self) -> bool:
        return True

    def get_recovery_info(self) -> Tuple[Optional[G1Element], Optional[uint64]]:
        if self.vault_info.is_recoverable:
            return self.recovery_info.bls_pk, self.recovery_info.timelock
        return None, None

    def get_p2_singleton_puzzle_hash(self) -> bytes32:
        return get_p2_singleton_puzzle_hash(self.vault_info.launcher_coin_id)

    async def select_coins(self, amount: uint64, coin_selection_config: CoinSelectionConfig) -> Set[Coin]:
        unconfirmed_removals: Dict[bytes32, Coin] = await self.wallet_state_manager.unconfirmed_removals_for_wallet(
            self.id()
        )
        puzhash = self.get_p2_singleton_puzzle_hash()
        records = await self.wallet_state_manager.coin_store.get_coin_records_by_puzzle_hash(puzhash)
        assert records is not None
        spendable_amount = uint128(sum([rec.coin.amount for rec in records]))
        coins = await select_coins(
            spendable_amount,
            coin_selection_config,
            records,
            unconfirmed_removals,
            self.log,
            uint128(amount),
        )
        return coins

    def derivation_for_index(self, index: int) -> List[DerivationRecord]:
        hidden_puzzle = get_vault_hidden_puzzle_with_index(uint32(index))
        hidden_puzzle_hash = hidden_puzzle.get_tree_hash()
        bls_pk, timelock = self.get_recovery_info()
        inner_puzzle_hash = get_vault_inner_puzzle_hash(
            self.vault_info.pubkey,
            self.wallet_state_manager.constants.GENESIS_CHALLENGE,
            hidden_puzzle_hash,
            bls_pk,
            timelock,
        )
        record = DerivationRecord(
            uint32(index), inner_puzzle_hash, self.vault_info.pubkey, self.type(), self.id(), False
        )
        return [record]

    async def create_recovery_spends(self) -> List[TransactionRecord]:
        """
        Returns two spendbundles
        1. The spend recovering the vault which can be taken to the appropriate BLS wallet for signing
        2. The spend that completes the recovery after the timelock has elapsed
        """
        assert self.vault_info.is_recoverable
        wallet_node: Any = self.wallet_state_manager.wallet_node
        peer = wallet_node.get_full_node_peer()
        assert peer is not None
        # 1. Generate the recovery spend
        # Get the current vault coin, ensure it's unspent
        vault_coin = self.vault_info.coin
        amount = uint64(self.vault_info.coin.amount)
        vault_coin_state = (await wallet_node.get_coin_state([vault_coin.name()], peer))[0]
        assert vault_coin_state.spent_height is None
        # Generate the current inner puzzle
        inner_puzzle = get_vault_inner_puzzle(
            self.vault_info.pubkey,
            self.wallet_state_manager.constants.GENESIS_CHALLENGE,
            self.vault_info.hidden_puzzle_hash,
            self.recovery_info.bls_pk,
            self.recovery_info.timelock,
        )
        assert inner_puzzle.get_tree_hash() == self.vault_info.inner_puzzle_hash

        secp_puzzle_hash = construct_p2_delegated_secp(
            self.vault_info.pubkey,
            self.wallet_state_manager.constants.GENESIS_CHALLENGE,
            self.vault_info.hidden_puzzle_hash,
        ).get_tree_hash()

        recovery_puzzle = get_recovery_puzzle(secp_puzzle_hash, self.recovery_info.bls_pk, self.recovery_info.timelock)
        recovery_puzzle_hash = recovery_puzzle.get_tree_hash()

        recovery_solution = get_recovery_solution(amount, self.recovery_info.bls_pk)

        merkle_tree = construct_vault_merkle_tree(secp_puzzle_hash, recovery_puzzle_hash)
        proof = get_vault_proof(merkle_tree, recovery_puzzle_hash)
        inner_solution = get_vault_inner_solution(recovery_puzzle, recovery_solution, proof)

        full_puzzle = get_vault_full_puzzle(self.vault_info.launcher_coin_id, inner_puzzle)
        assert full_puzzle.get_tree_hash() == vault_coin.puzzle_hash

        full_solution = get_vault_full_solution(self.vault_info.lineage_proof, amount, inner_solution)
        recovery_spend = SpendBundle([CoinSpend(vault_coin, full_puzzle, full_solution)], G2Element())

        # 2. Generate the Finish Recovery Spend
        recovery_finish_puzzle = get_recovery_finish_puzzle(
            self.recovery_info.bls_pk, self.recovery_info.timelock, amount
        )
        recovery_finish_solution = Program.to([])
        recovery_inner_puzzle = get_recovery_inner_puzzle(secp_puzzle_hash, recovery_finish_puzzle.get_tree_hash())
        full_recovery_puzzle = get_vault_full_puzzle(self.vault_info.launcher_coin_id, recovery_inner_puzzle)
        recovery_coin = Coin(self.vault_info.coin.name(), full_recovery_puzzle.get_tree_hash(), amount)
        recovery_solution = get_vault_inner_solution(recovery_finish_puzzle, recovery_finish_solution, proof)
        lineage = LineageProof(self.vault_info.coin.name(), inner_puzzle.get_tree_hash(), amount)
        full_recovery_solution = get_vault_full_solution(lineage, amount, recovery_solution)
        finish_spend = SpendBundle(
            [CoinSpend(recovery_coin, full_recovery_puzzle, full_recovery_solution)], G2Element()
        )

        # make the tx records
        recovery_tx = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=full_puzzle.get_tree_hash(),
            amount=amount,
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=recovery_spend,
            additions=recovery_spend.additions(),
            removals=recovery_spend.removals(),
            wallet_id=self.id(),
            sent_to=[],
            memos=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=recovery_spend.name(),
            valid_times=parse_timelock_info(tuple()),
        )

        finish_tx = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=full_puzzle.get_tree_hash(),
            amount=amount,
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=finish_spend,
            additions=finish_spend.additions(),
            removals=finish_spend.removals(),
            wallet_id=self.id(),
            sent_to=[],
            memos=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=finish_spend.name(),
            valid_times=parse_timelock_info(tuple()),
        )

        return [recovery_tx, finish_tx]

    async def sync_vault_launcher(self) -> None:
        wallet_node: Any = self.wallet_state_manager.wallet_node
        peer = wallet_node.get_full_node_peer()
        assert peer is not None

        assert isinstance(self.wallet_state_manager.observation_root, VaultRoot)
        launcher_id = bytes32(self.wallet_state_manager.observation_root.launcher_id)

        coin_states = await wallet_node.get_coin_state([launcher_id], peer)
        if not coin_states:
            raise ValueError(f"No coin found for launcher id: {launcher_id}.")
        coin_state: CoinState = coin_states[0]
        parent_state: CoinState = (await wallet_node.get_coin_state([coin_state.coin.parent_coin_info], peer))[0]

        assert parent_state.spent_height is not None
        launcher_spend = await fetch_coin_spend(uint32(parent_state.spent_height), parent_state.coin, peer)
        launcher_solution = launcher_spend.solution.to_program()

        is_recoverable = False
        bls_pk = None
        timelock = None
        memos = launcher_solution.at("rrf")
        secp_pk = memos.at("f").as_atom()
        hidden_puzzle_hash = bytes32(memos.at("rf").as_atom())
        if memos.list_len() == 4:
            is_recoverable = True
            bls_pk = G1Element.from_bytes(memos.at("rrf").as_atom())
            timelock = uint64(memos.at("rrrf").as_int())
            self.recovery_info = RecoveryInfo(bls_pk, timelock)
        inner_puzzle_hash = get_vault_inner_puzzle_hash(
            secp_pk, self.wallet_state_manager.constants.GENESIS_CHALLENGE, hidden_puzzle_hash, bls_pk, timelock
        )
        lineage_proof = LineageProof(parent_state.coin.parent_coin_info, None, uint64(parent_state.coin.amount))
        vault_info = VaultInfo(
            coin_state.coin,
            launcher_id,
            secp_pk,
            hidden_puzzle_hash,
            inner_puzzle_hash,
            is_recoverable,
            parent_state.coin.name(),
            lineage_proof,
        )
        await self.save_info(vault_info)
        await self.wallet_state_manager.create_more_puzzle_hashes()

        # subscribe to p2_singleton puzzle hash
        p2_puzzle_hash = self.get_p2_singleton_puzzle_hash()
        await self.wallet_state_manager.add_interested_puzzle_hashes([p2_puzzle_hash], [self.id()])

        # add the singleton record to store
        await self.wallet_state_manager.singleton_store.add_eve_record(
            self.id(),
            coin_state.coin,
            launcher_spend,
            inner_puzzle_hash,
            lineage_proof,
            uint32(coin_state.spent_height) if coin_state.spent_height else uint32(0),
            pending=False,
            custom_data=bytes(json.dumps(vault_info.to_json_dict()), "utf-8"),
        )

    async def update_vault_singleton(
        self, next_inner_puzzle: Program, coin_spend: CoinSpend, coin_state: CoinState
    ) -> None:
        hints, _ = compute_spend_hints_and_additions(coin_spend)
        inner_puzzle_hash = hints[coin_state.coin.name()].hint
        assert inner_puzzle_hash
        dr = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(inner_puzzle_hash)
        assert dr is not None
        hidden_puzzle_hash = get_vault_hidden_puzzle_with_index(dr.index).get_tree_hash()
        next_inner_puzzle = get_vault_inner_puzzle(
            self.vault_info.pubkey,
            self.wallet_state_manager.constants.GENESIS_CHALLENGE,
            hidden_puzzle_hash,
            self.recovery_info.bls_pk if self.vault_info.is_recoverable else None,
            self.recovery_info.timelock if self.vault_info.is_recoverable else None,
        )

        # get the parent state to create lineage proof
        wallet_node: Any = self.wallet_state_manager.wallet_node
        peer = wallet_node.get_full_node_peer()
        assert peer is not None
        parent_state = (await wallet_node.get_coin_state([coin_state.coin.parent_coin_info], peer))[0]
        parent_spend = await fetch_coin_spend(uint32(parent_state.spent_height), parent_state.coin, peer)
        parent_puzzle = parent_spend.puzzle_reveal.to_program()
        parent_inner_puzzle_hash = parent_puzzle.uncurry()[1].at("rf").get_tree_hash()
        lineage_proof = LineageProof(
            parent_state.coin.parent_coin_info, parent_inner_puzzle_hash, parent_state.coin.amount
        )
        new_vault_info = VaultInfo(
            coin_state.coin,
            self.vault_info.launcher_id,
            self.vault_info.pubkey,
            hidden_puzzle_hash,
            next_inner_puzzle.get_tree_hash(),
            self.vault_info.is_recoverable,
            self.vault_info.launcher_coin_id,
            lineage_proof,
        )

        await self.wallet_state_manager.singleton_store.add_spend(self.id(), coin_spend)
        await self.save_info(new_vault_info)

    async def save_info(self, vault_info: VaultInfo) -> None:
        self.vault_info = vault_info
        current_info = self.wallet_info
        data_str = json.dumps(vault_info.to_json_dict())
        wallet_info = WalletInfo(current_info.id, current_info.name, current_info.type, data_str)
        self.wallet_info = wallet_info
