from __future__ import annotations

import dataclasses
import logging
import time
import traceback
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple, Type, TypeVar, Union

from blspy import G1Element, G2Element
from clvm.casts import int_to_bytes
from typing_extensions import Unpack

from chia.protocols.wallet_protocol import CoinState
from chia.server.ws_connection import WSChiaConnection
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin, coin_as_list
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64, uint128
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.payment import Payment
from chia.wallet.puzzle_drivers import Solver
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import solution_for_conditions
from chia.wallet.trading.offer import Offer
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_sync_utils import fetch_coin_spend_for_coin_state
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.vc_wallet.cr_cat_drivers import CRCAT, CRCATSpend, ProofsChecker, construct_pending_approval_state
from chia.wallet.vc_wallet.vc_drivers import VerifiedCredential
from chia.wallet.vc_wallet.vc_store import VCProofs, VCRecord, VCStore
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_protocol import GSTOptionalArgs, WalletProtocol

if TYPE_CHECKING:
    from chia.wallet.wallet_state_manager import WalletStateManager  # pragma: no cover

_T_VCWallet = TypeVar("_T_VCWallet", bound="VCWallet")


class VCWallet:
    wallet_state_manager: WalletStateManager
    log: logging.Logger
    standard_wallet: Wallet
    wallet_info: WalletInfo
    store: VCStore

    @classmethod
    async def create_new_vc_wallet(
        cls: Type[_T_VCWallet],
        wallet_state_manager: WalletStateManager,
        wallet: Wallet,
        name: Optional[str] = None,
    ) -> _T_VCWallet:
        name = "VCWallet" if name is None else name
        new_wallet: _T_VCWallet = await cls.create(
            wallet_state_manager,
            wallet,
            await wallet_state_manager.user_store.create_wallet(name, uint32(WalletType.VC.value), ""),
            name,
        )
        await wallet_state_manager.add_new_wallet(new_wallet)
        return new_wallet

    @classmethod
    async def create(
        cls: Type[_T_VCWallet],
        wallet_state_manager: WalletStateManager,
        wallet: Wallet,
        wallet_info: WalletInfo,
        name: Optional[str] = None,
    ) -> _T_VCWallet:
        self = cls()
        self.wallet_state_manager = wallet_state_manager
        self.standard_wallet = wallet
        self.log = logging.getLogger(name if name else wallet_info.name)
        self.wallet_info = wallet_info
        self.store = wallet_state_manager.vc_store
        return self

    @classmethod
    def type(cls) -> WalletType:
        return WalletType.VC

    def id(self) -> uint32:
        return self.wallet_info.id

    async def coin_added(self, coin: Coin, height: uint32, peer: WSChiaConnection) -> None:
        """
        An unspent coin has arrived to our wallet. Get the parent spend to construct the current VerifiedCredential
        representation of the coin and add it to the DB if it's the newest version of the singleton.
        """
        wallet_node = self.wallet_state_manager.wallet_node
        coin_states: Optional[List[CoinState]] = await wallet_node.get_coin_state([coin.parent_coin_info], peer=peer)
        if coin_states is None:
            self.log.error(
                f"Cannot find parent coin of the verified credential coin: {coin.name().hex()}"
            )  # pragma: no cover
            return  # pragma: no cover
        parent_coin_state = coin_states[0]
        cs = await fetch_coin_spend_for_coin_state(parent_coin_state, peer)
        if cs is None:
            self.log.error(
                f"Cannot get verified credential coin: {coin.name().hex()} puzzle and solution"
            )  # pragma: no cover
            return  # pragma: no cover
        try:
            vc = VerifiedCredential.get_next_from_coin_spend(cs)
        except Exception as e:  # pragma: no cover
            self.log.debug(
                f"Syncing VC from coin spend failed (likely means it was revoked): {e}\n{traceback.format_exc()}"
            )
            return
        vc_record: VCRecord = VCRecord(vc, height)
        self.wallet_state_manager.state_changed(
            "vc_coin_added", self.id(), dict(launcher_id=vc_record.vc.launcher_id.hex())
        )
        await self.store.add_or_replace_vc_record(vc_record)

    async def remove_coin(self, coin: Coin, height: uint32) -> None:
        """
        remove the VC if it is transferred to another key
        :param coin:
        :param height:
        :return:
        """
        vc_record: Optional[VCRecord] = await self.store.get_vc_record_by_coin_id(coin.name())
        if vc_record is not None:
            await self.store.delete_vc_record(vc_record.vc.launcher_id)
            self.wallet_state_manager.state_changed(
                "vc_coin_removed", self.id(), dict(launcher_id=vc_record.vc.launcher_id.hex())
            )

    async def get_vc_record_for_launcher_id(self, launcher_id: bytes32) -> VCRecord:
        """
        Go into the store and get the VC Record representing the latest representation of the VC we have on chain.
        """
        vc_record = await self.store.get_vc_record(launcher_id)
        if vc_record is None:
            raise ValueError(f"Verified credential {launcher_id.hex()} doesn't exist.")  # pragma: no cover
        return vc_record

    async def launch_new_vc(
        self,
        provider_did: bytes32,
        inner_puzzle_hash: Optional[bytes32] = None,
        fee: uint64 = uint64(0),
    ) -> Tuple[VCRecord, List[TransactionRecord]]:
        """
        Given the DID ID of a proof provider, mint a brand new VC with an empty slot for proofs.

        Returns the tx records associated with the transaction as well as the expected unconfirmed VCRecord.
        """
        # Check if we own the DID
        found_did = False
        for _, wallet in self.wallet_state_manager.wallets.items():
            if wallet.type() == WalletType.DECENTRALIZED_ID:
                assert isinstance(wallet, DIDWallet)
                if bytes32.fromhex(wallet.get_my_DID()) == provider_did:
                    found_did = True
                    break
        if not found_did:
            raise ValueError(f"You don't own the DID {provider_did.hex()}")  # pragma: no cover
        # Mint VC
        coins = await self.standard_wallet.select_coins(uint64(1 + fee), min_coin_amount=uint64(1 + fee))
        if len(coins) == 0:
            raise ValueError("Cannot find a coin to mint the verified credential.")  # pragma: no cover
        if inner_puzzle_hash is None:
            inner_puzzle_hash = await self.standard_wallet.get_puzzle_hash(new=False)  # pragma: no cover
        original_coin = coins.pop()
        dpuz, coin_spends, vc = VerifiedCredential.launch(
            original_coin,
            provider_did,
            inner_puzzle_hash,
            [inner_puzzle_hash],
            fee=fee,
        )
        solution = solution_for_conditions(dpuz.rest())
        original_puzzle = await self.standard_wallet.puzzle_for_puzzle_hash(original_coin.puzzle_hash)
        coin_spends.append(CoinSpend(original_coin, original_puzzle, solution))
        spend_bundle = await self.wallet_state_manager.sign_transaction(coin_spends)
        now = uint64(int(time.time()))
        add_list: List[Coin] = list(spend_bundle.additions())
        rem_list: List[Coin] = list(spend_bundle.removals())
        vc_record: VCRecord = VCRecord(vc, uint32(0))
        tx = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=now,
            to_puzzle_hash=inner_puzzle_hash,
            amount=uint64(1),
            fee_amount=uint64(fee),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=add_list,
            removals=rem_list,
            wallet_id=uint32(1),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=spend_bundle.name(),
            memos=list(compute_memos(spend_bundle).items()),
        )

        return vc_record, [tx]

    async def generate_signed_transaction(
        self,
        vc_id: bytes32,
        fee: uint64 = uint64(0),
        new_inner_puzhash: Optional[bytes32] = None,
        coin_announcements: Optional[Set[bytes]] = None,
        puzzle_announcements: Optional[Set[bytes]] = None,
        coin_announcements_to_consume: Optional[Set[Announcement]] = None,
        puzzle_announcements_to_consume: Optional[Set[Announcement]] = None,
        reuse_puzhash: Optional[bool] = None,
        **kwargs: Unpack[GSTOptionalArgs],
    ) -> List[TransactionRecord]:
        new_proof_hash: Optional[bytes32] = kwargs.get(
            "new_proof_hash", None
        )  # Requires that this key posesses the DID to update the specified VC
        provider_inner_puzhash: Optional[bytes32] = kwargs.get("provider_inner_puzhash", None)
        """
        Entry point for two standard actions:
         - Cycle the singleton and make an announcement authorizing something
         - Update the hash of the proofs contained within the VC (new_proof_hash is not None)

        Returns a 1 - 3 TransactionRecord objects depending on whether or not there's a fee and whether or not there's
        a DID announcement involved.
        """
        # Find verified credential
        vc_record = await self.get_vc_record_for_launcher_id(vc_id)
        if vc_record.confirmed_at_height == 0:
            raise ValueError(
                f"Verified credential {vc_id.hex()} is not confirmed, please try again later."
            )  # pragma: no cover
        inner_puzhash: bytes32 = vc_record.vc.inner_puzzle_hash
        inner_puzzle: Program = await self.standard_wallet.puzzle_for_puzzle_hash(inner_puzhash)
        if new_inner_puzhash is None:
            new_inner_puzhash = inner_puzhash
        if coin_announcements_to_consume is not None:
            coin_announcements_bytes: Optional[Set[bytes32]] = {
                a.name() for a in coin_announcements_to_consume
            }  # pragma: no cover
        else:
            coin_announcements_bytes = None

        if puzzle_announcements_to_consume is not None:
            puzzle_announcements_bytes: Optional[Set[bytes32]] = {
                a.name() for a in puzzle_announcements_to_consume
            }  # pragma: no cover
        else:
            puzzle_announcements_bytes = None

        primaries: List[Payment] = [Payment(new_inner_puzhash, uint64(vc_record.vc.coin.amount), [new_inner_puzhash])]

        if fee > 0:
            announcement_to_make = vc_record.vc.coin.name()
            chia_tx = await self.wallet_state_manager.main_wallet.create_tandem_xch_tx(
                fee, Announcement(vc_record.vc.coin.name(), announcement_to_make), reuse_puzhash=reuse_puzhash
            )
            if coin_announcements is None:
                coin_announcements = set((announcement_to_make,))
            else:
                coin_announcements.add(announcement_to_make)  # pragma: no cover
        else:
            chia_tx = None
        if new_proof_hash is not None:
            if provider_inner_puzhash is None:
                for _, wallet in self.wallet_state_manager.wallets.items():
                    if wallet.type() == WalletType.DECENTRALIZED_ID:
                        assert isinstance(wallet, DIDWallet)
                        if wallet.did_info.current_inner is not None and wallet.did_info.origin_coin is not None:
                            if vc_record.vc.proof_provider == wallet.did_info.origin_coin.name():
                                provider_inner_puzhash = wallet.did_info.current_inner.get_tree_hash()
                                break
                            else:
                                continue  # pragma: no cover
                else:
                    raise ValueError("VC could not be updated with specified DID info")  # pragma: no cover
            magic_condition = vc_record.vc.magic_condition_for_new_proofs(new_proof_hash, provider_inner_puzhash)
        else:
            magic_condition = vc_record.vc.standard_magic_condition()
        innersol: Program = self.standard_wallet.make_solution(
            primaries=primaries,
            coin_announcements=coin_announcements,
            puzzle_announcements=puzzle_announcements,
            coin_announcements_to_assert=coin_announcements_bytes,
            puzzle_announcements_to_assert=puzzle_announcements_bytes,
            magic_conditions=[magic_condition],
        )
        did_announcement, coin_spend, vc = vc_record.vc.do_spend(inner_puzzle, innersol, new_proof_hash)
        spend_bundles = [await self.wallet_state_manager.sign_transaction([coin_spend])]
        if did_announcement is not None:
            # Need to spend DID
            for _, wallet in self.wallet_state_manager.wallets.items():
                if wallet.type() == WalletType.DECENTRALIZED_ID:
                    assert isinstance(wallet, DIDWallet)
                    if bytes32.fromhex(wallet.get_my_DID()) == vc_record.vc.proof_provider:
                        self.log.debug("Creating announcement from DID for vc: %s", vc_id.hex())
                        did_bundle = await wallet.create_message_spend(puzzle_announcements={bytes(did_announcement)})
                        spend_bundles.append(did_bundle)
                        break
            else:
                raise ValueError(
                    f"Cannot find the required DID {vc_record.vc.proof_provider.hex()}."
                )  # pragma: no cover
        tx_list: List[TransactionRecord] = []
        if chia_tx is not None and chia_tx.spend_bundle is not None:
            spend_bundles.append(chia_tx.spend_bundle)
            tx_list.append(dataclasses.replace(chia_tx, spend_bundle=None))
        spend_bundle = SpendBundle.aggregate(spend_bundles)
        now = uint64(int(time.time()))
        add_list: List[Coin] = list(spend_bundle.additions())
        rem_list: List[Coin] = list(spend_bundle.removals())
        tx_list.append(
            TransactionRecord(
                confirmed_at_height=uint32(0),
                created_at_time=now,
                to_puzzle_hash=new_inner_puzhash,
                amount=uint64(1),
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
            )
        )
        return tx_list

    async def revoke_vc(
        self, parent_id: bytes32, peer: WSChiaConnection, fee: uint64 = uint64(0), reuse_puzhash: Optional[bool] = None
    ) -> List[TransactionRecord]:
        vc_coin_states: List[CoinState] = await self.wallet_state_manager.wallet_node.get_coin_state(
            [parent_id], peer=peer
        )
        if vc_coin_states is None:
            raise ValueError(f"Cannot find verified credential coin: {parent_id.hex()}")  # pragma: no cover
        vc_coin_state = vc_coin_states[0]
        cs: CoinSpend = await fetch_coin_spend_for_coin_state(vc_coin_state, peer)
        vc: VerifiedCredential = VerifiedCredential.get_next_from_coin_spend(cs)

        # Check if we own the DID
        did_wallet: DIDWallet
        for _, wallet in self.wallet_state_manager.wallets.items():
            if wallet.type() == WalletType.DECENTRALIZED_ID:
                assert isinstance(wallet, DIDWallet)
                if bytes32.fromhex(wallet.get_my_DID()) == vc.proof_provider:
                    did_wallet = wallet
                    break
        else:
            raise ValueError(f"You don't own the DID {vc.proof_provider.hex()}")  # pragma: no cover

        recovery_info: Optional[Tuple[bytes32, bytes32, uint64]] = await did_wallet.get_info_for_recovery()
        if recovery_info is None:
            raise RuntimeError("DID could not currently be accessed while trying to revoke VC")  # pragma: no cover
        _, provider_inner_puzhash, _ = recovery_info

        # Generate spend specific nonce
        coins = {await did_wallet.get_coin()}
        coins.add(vc.coin)
        if fee > 0:
            coins.update(await self.standard_wallet.select_coins(fee))
        sorted_coins: List[Coin] = sorted(coins, key=Coin.name)
        sorted_coin_list: List[List[Union[bytes32, uint64]]] = [coin_as_list(c) for c in sorted_coins]
        nonce: bytes32 = Program.to(sorted_coin_list).get_tree_hash()
        vc_announcement: Announcement = Announcement(vc.coin.name(), nonce)

        # Assemble final bundle
        expected_did_announcement, vc_spend = vc.activate_backdoor(provider_inner_puzhash, announcement_nonce=nonce)
        did_spend: SpendBundle = await did_wallet.create_message_spend(
            puzzle_announcements={expected_did_announcement},
            coin_announcements_to_assert={vc_announcement},
        )
        final_bundle: SpendBundle = SpendBundle.aggregate([SpendBundle([vc_spend], G2Element()), did_spend])
        tx: TransactionRecord = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=vc.inner_puzzle_hash,
            amount=uint64(1),
            fee_amount=uint64(fee),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=final_bundle,
            additions=list(final_bundle.additions()),
            removals=list(final_bundle.removals()),
            wallet_id=self.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=final_bundle.name(),
            memos=list(compute_memos(final_bundle).items()),
        )
        if fee > 0:
            chia_tx: TransactionRecord = await self.wallet_state_manager.main_wallet.create_tandem_xch_tx(
                fee, vc_announcement, reuse_puzhash
            )
            assert tx.spend_bundle is not None
            assert chia_tx.spend_bundle is not None
            tx = dataclasses.replace(tx, spend_bundle=SpendBundle.aggregate([chia_tx.spend_bundle, tx.spend_bundle]))
            chia_tx = dataclasses.replace(chia_tx, spend_bundle=None)
            return [tx, chia_tx]
        else:
            return [tx]  # pragma: no cover

    async def add_vc_authorization(
        self, offer: Offer, solver: Solver, reuse_puzhash: Optional[bool] = None
    ) -> Tuple[Offer, Solver]:
        if reuse_puzhash is None:
            reuse_puzhash_config = self.wallet_state_manager.config.get("reuse_public_key_for_change", None)
            if reuse_puzhash_config is None:
                reuse_puzhash = False  # pragma: no cover
            else:
                reuse_puzhash = reuse_puzhash_config.get(
                    str(self.wallet_state_manager.wallet_node.logged_in_fingerprint), False
                )
        # Gather all of the CRCATs being spent and the CRCATs that each creates
        crcat_spends: List[CRCATSpend] = []
        other_spends: List[CoinSpend] = []
        spends_to_fix: Dict[bytes32, CoinSpend] = {}
        for spend in offer.to_valid_spend().coin_spends:
            if CRCAT.is_cr_cat(uncurry_puzzle(spend.puzzle_reveal.to_program()))[0]:
                crcat_spend: CRCATSpend = CRCATSpend.from_coin_spend(spend)
                if crcat_spend.incomplete:
                    crcat_spends.append(crcat_spend)
                    if spend in offer._bundle.coin_spends:
                        spends_to_fix[spend.coin.name()] = spend
                else:
                    if spend in offer._bundle.coin_spends:  # pragma: no cover
                        other_spends.append(spend)
            else:
                if spend in offer._bundle.coin_spends:
                    other_spends.append(spend)

        # Figure out what VC announcements are needed
        announcements_to_make: Dict[bytes32, List[bytes32]] = {}
        announcements_to_assert: Dict[bytes32, List[Announcement]] = {}
        vcs: Dict[bytes32, VerifiedCredential] = {}
        coin_args: Dict[str, List[str]] = {}
        for crcat_spend in crcat_spends:
            # Check first whether we can approve...
            available_vcs: List[VCRecord] = [
                vc_rec
                for vc_rec in await self.store.get_vc_records_by_providers(crcat_spend.crcat.authorized_providers)
                if vc_rec.confirmed_at_height != 0
            ]
            if len(available_vcs) == 0:  # pragma: no cover
                raise ValueError(f"No VC available with provider in {crcat_spend.crcat.authorized_providers}")
            vc: VerifiedCredential = available_vcs[0].vc
            vc_to_use: bytes32 = vc.launcher_id
            vcs[vc_to_use] = vc
            # ...then whether or not we should
            our_crcat: bool = (
                await self.wallet_state_manager.get_wallet_identifier_for_puzzle_hash(
                    crcat_spend.crcat.inner_puzzle_hash
                )
                is not None
            )
            outputs_ok: bool = True
            for cc in [c for c in crcat_spend.inner_conditions if c.at("f") == 51]:
                if not (
                    (  # it's coming to us
                        await self.wallet_state_manager.get_wallet_identifier_for_puzzle_hash(bytes32(cc.at("rf").atom))
                        is not None
                    )
                    or (  # it's going back where it came from
                        bytes32(cc.at("rf").atom) == crcat_spend.crcat.inner_puzzle_hash
                    )
                    or (  # it's going to the pending state
                        cc.at("rrr") != Program.to(None)
                        and cc.at("rrrf").atom is None
                        and bytes32(cc.at("rf").atom)
                        == construct_pending_approval_state(
                            bytes32(cc.at("rrrff").atom), uint64(cc.at("rrf").as_int())
                        ).get_tree_hash()
                    )
                    or bytes32(cc.at("rf").atom) == Offer.ph()  # it's going to the offer mod
                ):
                    outputs_ok = False  # pragma: no cover
            if our_crcat or outputs_ok:
                announcements_to_make.setdefault(vc_to_use, [])
                announcements_to_assert.setdefault(vc_to_use, [])
                announcements_to_make[vc_to_use].append(crcat_spend.crcat.expected_announcement())
                announcements_to_assert[vc_to_use].extend(
                    [
                        Announcement(
                            crcat_spend.crcat.coin.name(),
                            b"\xcd" + std_hash(crc.inner_puzzle_hash + int_to_bytes(crc.coin.amount)),
                        )
                        for crc in crcat_spend.children
                    ]
                )

                coin_name: str = crcat_spend.crcat.coin.name().hex()
                coin_args[coin_name] = [
                    await self.proof_of_inclusions_for_root_and_keys(
                        # It's on my TODO list to fix the below line -Quex
                        vc.proof_hash,  # type: ignore
                        ProofsChecker.from_program(uncurry_puzzle(crcat_spend.crcat.proofs_checker)).flags,
                    ),
                    "()",  # not general
                    "0x" + vc.proof_provider.hex(),
                    "0x" + vc.launcher_id.hex(),
                    "0x" + vc.wrap_inner_with_backdoor().get_tree_hash().hex(),
                ]
                if crcat_spend.crcat.coin.name() in spends_to_fix:
                    spend_to_fix: CoinSpend = spends_to_fix[crcat_spend.crcat.coin.name()]
                    other_spends.append(
                        dataclasses.replace(
                            spend_to_fix,
                            solution=spend_to_fix.solution.to_program().replace(
                                ff=coin_args[coin_name][0],
                                frf=Program.to(None),  # not general
                                frrf=bytes32.from_hexstr(coin_args[coin_name][2]),
                                frrrf=bytes32.from_hexstr(coin_args[coin_name][3]),
                                frrrrf=bytes32.from_hexstr(coin_args[coin_name][4]),
                            ),
                        )
                    )
            else:
                raise ValueError("Wallet cannot verify all spends in specified offer")  # pragma: no cover

        vc_spends: List[SpendBundle] = []
        for launcher_id, vc in vcs.items():
            vc_spends.append(
                SpendBundle.aggregate(
                    [
                        tx.spend_bundle
                        for tx in (
                            await self.generate_signed_transaction(
                                launcher_id,
                                puzzle_announcements=set(announcements_to_make[launcher_id]),
                                coin_announcements_to_consume=set(announcements_to_assert[launcher_id]),
                                reuse_puzhash=reuse_puzhash,
                            )
                        )
                        if tx.spend_bundle is not None
                    ]
                )
            )

        return Offer.from_spend_bundle(
            SpendBundle.aggregate(
                [
                    SpendBundle(
                        [
                            *(
                                spend
                                for spend in offer.to_spend_bundle().coin_spends
                                if spend.coin.parent_coin_info == bytes32([0] * 32)
                            ),
                            *other_spends,
                        ],
                        offer._bundle.aggregated_signature,
                    ),
                    *vc_spends,
                ]
            )
        ), Solver({"vc_authorizations": coin_args})

    async def get_vc_with_provider_in_and_proofs(
        self, authorized_providers: List[bytes32], proofs: List[str]
    ) -> VerifiedCredential:
        vc_records: List[VCRecord] = await self.store.get_vc_records_by_providers(authorized_providers)
        if len(vc_records) == 0:  # pragma: no cover
            raise ValueError(f"VCWallet has no VCs with providers in the following list: {authorized_providers}")
        else:
            for rec in vc_records:
                if rec.vc.proof_hash is None:
                    continue  # pragma: no cover
                vc_proofs: Optional[VCProofs] = await self.store.get_proofs_for_root(rec.vc.proof_hash)
                if vc_proofs is None:
                    continue  # pragma: no cover
                if all(proof in vc_proofs.key_value_pairs for proof in proofs):
                    return rec.vc
        raise ValueError(f"No authorized VC has the correct proofs: {proofs}")  # pragma: no cover

    async def proof_of_inclusions_for_root_and_keys(self, root: bytes32, keys: List[str]) -> Program:
        vc_proofs: Optional[VCProofs] = await self.store.get_proofs_for_root(root)
        if vc_proofs is None:
            raise RuntimeError(f"No proofs exist for VC root: {root.hex()}")  # pragma: no cover
        else:
            return vc_proofs.prove_keys(keys)

    async def select_coins(
        self,
        amount: uint64,
        exclude: Optional[List[Coin]] = None,
        min_coin_amount: Optional[uint64] = None,
        max_coin_amount: Optional[uint64] = None,
        excluded_coin_amounts: Optional[List[uint64]] = None,
    ) -> Set[Coin]:
        raise RuntimeError("VCWallet does not support select_coins()")  # pragma: no cover

    async def get_confirmed_balance(self, record_list: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        """The VC wallet doesn't really have a balance."""
        return uint128(0)  # pragma: no cover

    async def get_unconfirmed_balance(self, record_list: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        """The VC wallet doesn't really have a balance."""
        return uint128(0)  # pragma: no cover

    async def get_spendable_balance(self, unspent_records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        """The VC wallet doesn't really have a balance."""
        return uint128(0)  # pragma: no cover

    async def get_pending_change_balance(self) -> uint64:
        return uint64(0)  # pragma: no cover

    async def get_max_send_amount(self, records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        """This is the confirmed balance, which we set to 0 as the VC wallet doesn't have one."""
        return uint128(0)  # pragma: no cover

    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:
        raise RuntimeError("VCWallet does not support puzzle_hash_for_pk")  # pragma: no cover

    def require_derivation_paths(self) -> bool:
        return False

    def get_name(self) -> str:
        return self.wallet_info.name  # pragma: no cover

    async def match_hinted_coin(self, coin: Coin, hint: bytes32) -> bool:
        return False


if TYPE_CHECKING:
    _dummy: WalletProtocol = VCWallet()  # pragma: no cover
