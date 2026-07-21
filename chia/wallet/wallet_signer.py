from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

from chia_rs import AugSchemeMPL, CoinSpend, G1Element, G2Element, PrivateKey
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia.consensus.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
from chia.util.hash import std_hash
from chia.wallet.derive_keys import (
    MAX_POOL_WALLETS,
    _derive_path,
    _derive_path_unhardened,
    master_sk_to_singleton_owner_sk,
)
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_offset,
    puzzle_hash_for_synthetic_public_key,
)
from chia.wallet.signer_protocol import (
    KeyHints,
    PathHint,
    Signature,
    SignedTransaction,
    SigningInstructions,
    SigningResponse,
    SigningTarget,
    Spend,
    SumHint,
    TransactionInfo,
    UnsignedTransaction,
)
from chia.wallet.trading.offer import Offer
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.wallet_puzzle_store import WalletPuzzleStore
from chia.wallet.wallet_spend_bundle import WalletSpendBundle


@dataclass(frozen=True, kw_only=True)
class WalletSigner:
    root_pubkey: G1Element
    root_private_key: PrivateKey | None
    puzzle_store: WalletPuzzleStore
    max_block_cost_clvm: int
    agg_sig_me_additional_data: bytes32
    spend_bundle_push: Callable[[WalletSpendBundle], Awaitable[None]]

    def __post_init__(self) -> None:
        if self.root_private_key is not None and self.root_private_key.get_g1() != self.root_pubkey:
            raise ValueError("root_private_key does not match self.root_pubkey")

    async def sum_hint_for_pubkey(self, pk: bytes) -> SumHint | None:
        pk_parsed: G1Element = G1Element.from_bytes(pk)
        dr = await self.puzzle_store.record_for_puzzle_hash(puzzle_hash_for_synthetic_public_key(pk_parsed))
        if dr is None:
            return None
        return SumHint(
            [dr.pubkey.get_fingerprint().to_bytes(4, "big")],
            calculate_synthetic_offset(dr.pubkey, DEFAULT_HIDDEN_PUZZLE_HASH).to_bytes(32, "big"),
            pk,
        )

    async def path_hint_for_pubkey(self, pk: bytes) -> PathHint | None:
        pk_parsed = G1Element.from_bytes(pk)
        index = await self.puzzle_store.index_for_pubkey(pk_parsed)
        if index is None:
            index = await self.puzzle_store.index_for_puzzle_hash(puzzle_hash_for_synthetic_public_key(pk_parsed))
        root_pubkey: bytes = self.root_pubkey.get_fingerprint().to_bytes(4, "big")
        if index is None:
            # Pool wallet may have a secret key here
            if self.root_private_key is not None:
                for pool_wallet_index in range(MAX_POOL_WALLETS):
                    try_owner_sk = master_sk_to_singleton_owner_sk(self.root_private_key, uint32(pool_wallet_index))
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

    async def key_hints_for_pubkeys(self, pks: list[bytes]) -> KeyHints:
        return KeyHints(
            [sum_hint for pk in pks if (sum_hint := await self.sum_hint_for_pubkey(pk)) is not None],
            [path_hint for pk in pks if (path_hint := await self.path_hint_for_pubkey(pk)) is not None],
        )

    async def gather_signing_info(self, spends: list[Spend]) -> SigningInstructions:
        pks: list[bytes] = []
        signing_targets: list[SigningTarget] = []
        for spend in spends:
            coin_spend = spend.as_coin_spend()
            # Get AGG_SIG conditions
            conditions_dict = conditions_dict_for_solution(
                coin_spend.puzzle_reveal,
                coin_spend.solution,
                self.max_block_cost_clvm,
            )
            # Create signature
            for pk, msg in pkm_pairs_for_conditions_dict(
                conditions_dict, coin_spend.coin, self.agg_sig_me_additional_data
            ):
                pk_bytes = bytes(pk)
                pks.append(pk_bytes)
                fingerprint: bytes = pk.get_fingerprint().to_bytes(4, "big")
                signing_targets.append(SigningTarget(fingerprint, msg, std_hash(pk_bytes + msg)))

        return SigningInstructions(
            await self.key_hints_for_pubkeys(pks),
            signing_targets,
        )

    async def gather_signing_info_for_bundles(self, bundles: list[WalletSpendBundle]) -> list[UnsignedTransaction]:
        utxs: list[UnsignedTransaction] = []
        for bundle in bundles:
            signer_protocol_spends: list[Spend] = [Spend.from_coin_spend(spend) for spend in bundle.coin_spends]
            utxs.append(
                UnsignedTransaction(
                    TransactionInfo(signer_protocol_spends),
                    await self.gather_signing_info(signer_protocol_spends),
                )
            )

        return utxs

    async def gather_signing_info_for_txs(self, txs: list[TransactionRecord]) -> list[UnsignedTransaction]:
        return await self.gather_signing_info_for_bundles(
            [tx.spend_bundle for tx in txs if tx.spend_bundle is not None]
        )

    async def gather_signing_info_for_trades(self, offers: list[Offer]) -> list[UnsignedTransaction]:
        return await self.gather_signing_info_for_bundles([offer._bundle for offer in offers])

    async def execute_signing_instructions(
        self, signing_instructions: SigningInstructions, partial_allowed: bool = False
    ) -> list[SigningResponse]:
        pk_lookup: dict[int, G1Element] = (
            {self.root_pubkey.get_fingerprint(): self.root_pubkey} if self.root_private_key is not None else {}
        )
        sk_lookup: dict[int, PrivateKey] = (
            {self.root_pubkey.get_fingerprint(): self.root_private_key} if self.root_private_key is not None else {}
        )
        aggregate_responses_at_end: bool = True
        responses: list[SigningResponse] = []

        # TODO: expand path hints and sum hints recursively (a sum hint can give a new key to path hint)
        # Next, expand our pubkey set with path hints
        if self.root_private_key is not None:
            for path_hint in signing_instructions.key_hints.path_hints:
                if int.from_bytes(path_hint.root_fingerprint, "big") != self.root_pubkey.get_fingerprint():
                    if not partial_allowed:
                        raise ValueError(f"No root pubkey for fingerprint {self.root_pubkey.get_fingerprint()}")
                    else:
                        continue
                else:
                    path = [int(step) for step in path_hint.path]
                    derive_child_sk = _derive_path(self.root_private_key, path)
                    derive_child_sk_unhardened = _derive_path_unhardened(self.root_private_key, path)
                    derive_child_pk = derive_child_sk.get_g1()
                    derive_child_pk_unhardened = derive_child_sk_unhardened.get_g1()
                    pk_lookup[derive_child_pk.get_fingerprint()] = derive_child_pk
                    pk_lookup[derive_child_pk_unhardened.get_fingerprint()] = derive_child_pk_unhardened
                    sk_lookup[derive_child_pk.get_fingerprint()] = derive_child_sk
                    sk_lookup[derive_child_pk_unhardened.get_fingerprint()] = derive_child_sk_unhardened

        # Next, expand our pubkey set with sum hints
        sum_hint_lookup: dict[int, list[int]] = {}
        for sum_hint in signing_instructions.key_hints.sum_hints:
            fingerprints_we_have: list[int] = []
            for fingerprint in sum_hint.fingerprints:
                fingerprint_as_int = int.from_bytes(fingerprint, "big")
                if fingerprint_as_int not in pk_lookup:
                    if not partial_allowed:
                        raise ValueError(
                            f"No pubkey found (or path hinted to) for fingerprint {int.from_bytes(fingerprint, 'big')}"
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
                signatures: list[G2Element] = []
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
            new_responses: list[SigningResponse] = []
            grouped_responses: dict[bytes32, list[SigningResponse]] = {}
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
        self, spends: list[Spend], signing_responses: list[SigningResponse]
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

    def signed_tx_to_spendbundle(self, signed_tx: SignedTransaction) -> WalletSpendBundle:
        if len([_ for _ in signed_tx.signatures if _.type != "bls_12381_aug_scheme"]) > 0:
            raise ValueError("Unable to handle signatures that are not bls_12381_aug_scheme")  # pragma: no cover
        return WalletSpendBundle(
            [spend.as_coin_spend() for spend in signed_tx.transaction_info.spends],
            AugSchemeMPL.aggregate([G2Element.from_bytes(sig.signature) for sig in signed_tx.signatures]),
        )

    async def sign_transactions(
        self,
        tx_records: list[TransactionRecord],
        additional_signing_responses: list[SigningResponse] = [],
        partial_allowed: bool = False,
    ) -> tuple[list[TransactionRecord], list[SigningResponse]]:
        unsigned_txs: list[UnsignedTransaction] = await self.gather_signing_info_for_txs(tx_records)
        new_txs: list[TransactionRecord] = []
        all_signing_responses = additional_signing_responses.copy()
        for unsigned_tx, tx in zip(
            unsigned_txs, [tx_record for tx_record in tx_records if tx_record.spend_bundle is not None]
        ):
            signing_responses: list[SigningResponse] = await self.execute_signing_instructions(
                unsigned_tx.signing_instructions, partial_allowed=partial_allowed
            )
            all_signing_responses.extend(signing_responses)
            new_bundle = self.signed_tx_to_spendbundle(
                await self.apply_signatures(
                    unsigned_tx.transaction_info.spends,
                    [*additional_signing_responses, *signing_responses],
                )
            )
            new_txs.append(replace(tx, spend_bundle=new_bundle, name=new_bundle.name()))
        new_txs.extend([tx_record for tx_record in tx_records if tx_record.spend_bundle is None])
        return new_txs, all_signing_responses

    async def sign_offers(
        self,
        offers: list[Offer],
        additional_signing_responses: list[SigningResponse] = [],
        partial_allowed: bool = False,
    ) -> tuple[list[Offer], list[SigningResponse]]:
        unsigned_txs: list[UnsignedTransaction] = await self.gather_signing_info_for_trades(offers)
        new_offers: list[Offer] = []
        all_signing_responses = additional_signing_responses.copy()
        for unsigned_tx, offer in zip(unsigned_txs, [offer for offer in offers]):
            signing_responses: list[SigningResponse] = await self.execute_signing_instructions(
                unsigned_tx.signing_instructions, partial_allowed=partial_allowed
            )
            all_signing_responses.extend(signing_responses)
            new_bundle = self.signed_tx_to_spendbundle(
                await self.apply_signatures(
                    unsigned_tx.transaction_info.spends,
                    [*additional_signing_responses, *signing_responses],
                )
            )
            new_offers.append(Offer(offer.requested_payments, new_bundle, offer.driver_dict))
        return new_offers, all_signing_responses

    async def sign_bundle(
        self,
        coin_spends: list[CoinSpend],
        additional_signing_responses: list[SigningResponse] = [],
        partial_allowed: bool = False,
    ) -> tuple[WalletSpendBundle, list[SigningResponse]]:
        [unsigned_tx] = await self.gather_signing_info_for_bundles([WalletSpendBundle(coin_spends, G2Element())])
        signing_responses: list[SigningResponse] = await self.execute_signing_instructions(
            unsigned_tx.signing_instructions, partial_allowed=partial_allowed
        )
        return (
            self.signed_tx_to_spendbundle(
                await self.apply_signatures(
                    unsigned_tx.transaction_info.spends,
                    [*additional_signing_responses, *signing_responses],
                )
            ),
            signing_responses,
        )

    async def submit_transactions(self, signed_txs: list[SignedTransaction]) -> list[bytes32]:
        bundles: list[WalletSpendBundle] = [self.signed_tx_to_spendbundle(tx) for tx in signed_txs]
        for bundle in bundles:
            await self.spend_bundle_push(bundle)
        return [bundle.name() for bundle in bundles]
