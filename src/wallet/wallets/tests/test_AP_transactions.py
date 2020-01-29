import asyncio
import pathlib
import tempfile
from aiter import map_aiter
from standard_wallet.wallet import Wallet
from authorised_payees.ap_wallet import APWallet
from authorised_payees import ap_wallet_a_functions
from chiasim.utils.log import init_logging
from chiasim.remote.api_server import api_server
from chiasim.remote.client import request_response_proxy
from chiasim.clients import ledger_sim
from chiasim.ledger import ledger_api
from chiasim.hashable import Coin
from chiasim.storage import RAM_DB
from chiasim.utils.server import start_unix_server_aiter
from chiasim.wallet.deltas import additions_for_body, removals_for_body


async def proxy_for_unix_connection(path):
    reader, writer = await asyncio.open_unix_connection(path)
    return request_response_proxy(reader, writer, ledger_sim.REMOTE_SIGNATURES)


def make_client_server():
    init_logging()
    run = asyncio.get_event_loop().run_until_complete
    path = pathlib.Path(tempfile.mkdtemp(), "port")
    server, aiter = run(start_unix_server_aiter(path))
    rws_aiter = map_aiter(lambda rw: dict(
        reader=rw[0], writer=rw[1], server=server), aiter)
    initial_block_hash = bytes(([0] * 31) + [1])
    ledger = ledger_api.LedgerAPI(initial_block_hash, RAM_DB())
    server_task = asyncio.ensure_future(api_server(rws_aiter, ledger))
    remote = run(proxy_for_unix_connection(path))
    # make sure server_task isn't garbage collected
    remote.server_task = server_task
    return remote


def commit_and_notify(remote, wallets, reward_recipient):
    run = asyncio.get_event_loop().run_until_complete
    coinbase_puzzle_hash = reward_recipient.get_new_puzzlehash()
    fees_puzzle_hash = reward_recipient.get_new_puzzlehash()
    r = run(remote.next_block(coinbase_puzzle_hash=coinbase_puzzle_hash,
                                fees_puzzle_hash=fees_puzzle_hash))
    body = r.get("body")

    additions = list(additions_for_body(body))
    removals = removals_for_body(body)
    removals = [Coin.from_bytes(run(remote.hash_preimage(hash=x)))
                              for x in removals]

    for wallet in wallets:
        spend_bundle = wallet.notify(additions, removals)
        if spend_bundle is not None:
            for bun in spend_bundle:
                _ = run(remote.push_tx(tx=bun))


def test_AP_spend():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete
    # A gives B some money, but B can only send that money to C (and generate change for itself)
    wallet_a = Wallet()
    wallet_b = APWallet()
    wallet_c = Wallet()
    wallet_d = Wallet()

    wallets = [wallet_a, wallet_b, wallet_c, wallet_d]

    a_pubkey = wallet_a.get_next_public_key().serialize()
    b_pubkey = wallet_b.get_next_public_key().serialize()
    APpuzzlehash = ap_wallet_a_functions.ap_get_new_puzzlehash(
        a_pubkey, b_pubkey)
    wallet_b.set_sender_values(APpuzzlehash, a_pubkey)
    wallet_b.set_approved_change_signature(ap_wallet_a_functions.ap_sign_output_newpuzzlehash(
        APpuzzlehash, wallet_a, a_pubkey))

    commit_and_notify(remote, wallets, wallet_a)

    assert wallet_a.current_balance == 1000000000
    assert len(wallet_a.my_utxos) == 2
    assert wallet_b.current_balance == 0
    assert len(wallet_b.my_utxos) == 0

    # Wallet A locks up the puzzle with information regarding B's pubkey
    amount = 5000
    spend_bundle = wallet_a.generate_signed_transaction(amount, APpuzzlehash)
    _ = run(remote.push_tx(tx=spend_bundle))

    commit_and_notify(remote, wallets, wallet_d)

    assert wallet_a.current_balance == 999995000
    assert wallet_b.current_balance == 5000
    assert len(wallet_b.my_utxos) == 1

    # Wallet A sends more money into Wallet B using the aggregation coin
    aggregation_puzzlehash = ap_wallet_a_functions.ap_get_aggregation_puzzlehash(
        APpuzzlehash)
    # amount = 80
    spend_bundle = wallet_a.generate_signed_transaction(
        5000, aggregation_puzzlehash)
    _ = run(remote.push_tx(tx=spend_bundle))
    spend_bundle = wallet_d.generate_signed_transaction(
        3000, aggregation_puzzlehash)
    _ = run(remote.push_tx(tx=spend_bundle))

    commit_and_notify(remote, wallets, Wallet())

    assert wallet_a.current_balance == 999990000
    assert wallet_b.temp_coin.amount == 13000
    assert wallet_c.current_balance == 0
    assert wallet_d.current_balance == 999997000
    assert len(wallet_b.my_utxos) == 1

    commit_and_notify(remote, wallets, Wallet())

    assert wallet_b.current_balance == 13000

    approved_puzhashes = [
        wallet_c.get_new_puzzlehash()]

    signatures = [ap_wallet_a_functions.ap_sign_output_newpuzzlehash(
        approved_puzhashes[0], wallet_a, a_pubkey)]
    ap_output = [(approved_puzhashes[0], 4000)]
    spend_bundle = wallet_b.ap_generate_signed_transaction(
        ap_output, signatures)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_a.current_balance == 999990000
    assert wallet_b.temp_coin.amount == 9000
    assert wallet_c.current_balance == 4000
    assert len(wallet_c.my_utxos) == 1
    assert wallet_d.current_balance == 999997000
    assert len(wallet_b.my_utxos) == 1

    # Spend from wallet_c freely

    puzzlehash = wallet_a.get_new_puzzlehash()
    spend_bundle = wallet_c.generate_signed_transaction(2000, puzzlehash)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_c.current_balance == 2000
    assert len(wallet_c.my_utxos) == 1
    assert wallet_a.current_balance == 999992000

    # Test spend more money than AP wallet's amount

    ap_output = [(approved_puzhashes[0], 10000)]
    spend_bundle = wallet_b.ap_generate_signed_transaction(
        ap_output, signatures)
    assert spend_bundle is None

    ap_output = [(approved_puzhashes[0], 6000)]
    spend_bundle = wallet_b.ap_generate_signed_transaction(
        ap_output, signatures)
    _ = run(remote.push_tx(tx=spend_bundle))

    # Try and over spend temp amount, but legal actual amount

    assert wallet_b.temp_coin.amount == 3000
    assert wallet_b.current_balance == 9000

    ap_output = [(approved_puzhashes[0], 6000)]
    spend_bundle = wallet_b.ap_generate_signed_transaction(
        ap_output, signatures)

    assert spend_bundle is None
    assert wallet_b.temp_coin.amount == 3000
    assert wallet_b.current_balance == 9000


def test_invalid_payee():
    # Only Wallet C is approved - now lets try to spend to Wallet D
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete
    # A gives B some money, but B can only send that money to C (and generate change for itself)
    wallet_a = Wallet()
    wallet_b = APWallet()
    wallet_c = Wallet()
    wallet_d = Wallet()
    wallets = [wallet_a, wallet_b, wallet_c, wallet_d]

    a_pubkey = wallet_a.get_next_public_key().serialize()
    b_pubkey = wallet_b.get_next_public_key().serialize()
    APpuzzlehash = ap_wallet_a_functions.ap_get_new_puzzlehash(
        a_pubkey, b_pubkey)
    wallet_b.set_sender_values(APpuzzlehash, a_pubkey)
    wallet_b.set_approved_change_signature(ap_wallet_a_functions.ap_sign_output_newpuzzlehash(
        APpuzzlehash, wallet_a, a_pubkey))

    commit_and_notify(remote, wallets, wallet_a)

    assert wallet_a.current_balance == 1000000000
    assert len(wallet_a.my_utxos) == 2
    assert wallet_b.current_balance == 0
    assert len(wallet_b.my_utxos) == 0

    # Wallet A locks up the puzzle with information regarding B's pubkey
    amount = 5000
    spend_bundle = wallet_a.generate_signed_transaction(amount, APpuzzlehash)
    _ = run(remote.push_tx(tx=spend_bundle))

    commit_and_notify(remote, wallets, wallet_d)

    assert wallet_a.current_balance == 999995000
    assert wallet_b.current_balance == 5000
    assert len(wallet_b.my_utxos) == 1

    approved_puzhashes = [
        wallet_c.get_new_puzzlehash()]
    signatures = [ap_wallet_a_functions.ap_sign_output_newpuzzlehash(
        approved_puzhashes[0], wallet_a, a_pubkey)]

    ap_output = [(wallet_d.get_new_puzzlehash(), 2000)]

    spend_bundle = wallet_b.ap_generate_signed_transaction(
        ap_output, signatures)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())
    assert wallet_a.current_balance == 999995000
    assert wallet_b.current_balance == 5000
    assert wallet_b.temp_coin.amount == 5000
    assert len(wallet_b.my_utxos) == 1


"""
Copyright 2018 Chia Network Inc
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at
   http://www.apache.org/licenses/LICENSE-2.0
Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
