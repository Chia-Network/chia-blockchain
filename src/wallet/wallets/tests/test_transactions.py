import asyncio
import pathlib
import tempfile
import clvm
from aiter import map_aiter
from standard_wallet.wallet import Wallet
from chiasim.utils.log import init_logging
from chiasim.remote.api_server import api_server
from chiasim.remote.client import request_response_proxy
from chiasim.clients import ledger_sim
from chiasim.ledger import ledger_api
from chiasim.hashable import Coin
from chiasim.storage import RAM_DB
from chiasim.utils.server import start_unix_server_aiter
from chiasim.wallet.deltas import additions_for_body, removals_for_body
from chiasim.hashable import Program, ProgramHash
from clvm_tools import binutils
from binascii import hexlify


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


def test_standard_spend():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete
    wallet_a = Wallet()
    wallet_b = Wallet()
    wallets = [wallet_a, wallet_b]
    commit_and_notify(remote, wallets, wallet_a)

    assert wallet_a.current_balance == 1000000000
    assert len(wallet_a.my_utxos) == 2
    assert wallet_b.current_balance == 0
    assert len(wallet_b.my_utxos) == 0
    # wallet a send to wallet b
    program = wallet_b.get_new_puzzle()
    puzzlehash = ProgramHash(program)

    amount = 5000
    spend_bundle = wallet_a.generate_signed_transaction(amount, puzzlehash)
    _ = run(remote.push_tx(tx=spend_bundle))
    # give new wallet the reward to not complicate the one's we're tracking
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_a.current_balance == 999995000
    assert wallet_b.current_balance == 5000
    assert len(wallet_b.my_utxos) == 1

    # wallet b sends back to wallet a
    puzzlehash = wallet_a.get_new_puzzlehash()

    amount = 5000
    spend_bundle = wallet_b.generate_signed_transaction(amount, puzzlehash)
    _ = run(remote.push_tx(tx=spend_bundle))
    # give new wallet the reward to not complicate the one's we're tracking
    commit_and_notify(remote, wallets, Wallet())
    assert wallet_a.current_balance == 1000000000
    assert wallet_b.current_balance == 0


def test_future_utxos():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete
    wallet_a = Wallet()
    wallet_b = Wallet()
    wallets = [wallet_a, wallet_b]
    commit_and_notify(remote, wallets, wallet_a)

    assert wallet_a.current_balance == 1000000000
    assert len(wallet_a.my_utxos) == 2
    assert wallet_b.current_balance == 0
    assert len(wallet_b.my_utxos) == 0

    amount = 5000
    puzzlehash = wallet_b.get_new_puzzlehash()
    spend_bundle = wallet_a.generate_signed_transaction(amount, puzzlehash)
    _ = run(remote.push_tx(tx=spend_bundle))
    puzzlehash = wallet_b.get_new_puzzlehash()
    spend_bundle = wallet_a.generate_signed_transaction(amount, puzzlehash)
    _ = run(remote.push_tx(tx=spend_bundle))
    puzzlehash = wallet_b.get_new_puzzlehash()
    spend_bundle = wallet_a.generate_signed_transaction(amount, puzzlehash)
    _ = run(remote.push_tx(tx=spend_bundle))

    assert wallet_a.current_balance == 1000000000
    assert wallet_a.temp_balance == 999985000

    commit_and_notify(remote, wallets, Wallet())
    assert wallet_a.current_balance == 999985000
    assert wallet_b.current_balance == 15000
    assert len(wallet_b.my_utxos) == 3
    assert wallet_b.my_utxos.copy().pop().amount == 5000

    # test wallet spend multiple coins in one spendbundle
    puzzlehash = wallet_a.get_new_puzzlehash()
    spend_bundle = wallet_b.generate_signed_transaction(15000, puzzlehash)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())
    assert wallet_a.current_balance == 1000000000
    assert wallet_b.current_balance == 0


def test_spend_failure():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete
    wallet_a = Wallet()
    wallet_b = Wallet()
    wallets = [wallet_a, wallet_b]
    amount = 5000
    # wallet a send to wallet b
    program = wallet_b.get_new_puzzle()
    puzzlehash = ProgramHash(program)
    spend_bundle = wallet_a.generate_signed_transaction(amount, puzzlehash)
    assert spend_bundle is None

    commit_and_notify(remote, wallets, wallet_a)
    amount = 50000000000000
    puzzlehash = wallet_b.get_new_puzzlehash()
    spend_bundle = wallet_a.generate_signed_transaction(amount, puzzlehash)
    assert spend_bundle is None
    amount = 999995000
    puzzlehash = wallet_b.get_new_puzzlehash()
    spend_bundle = wallet_a.generate_signed_transaction(amount, puzzlehash)
    _ = run(remote.push_tx(tx=spend_bundle))
    assert wallet_a.temp_balance == 5000

    amount = 6000
    puzzlehash = wallet_b.get_new_puzzlehash()
    spend_bundle = wallet_a.generate_signed_transaction(amount, puzzlehash)
    assert spend_bundle is None

    amount = 4000
    puzzlehash = wallet_b.get_new_puzzlehash()
    spend_bundle = wallet_a.generate_signed_transaction(amount, puzzlehash)
    _ = run(remote.push_tx(tx=spend_bundle))
    assert wallet_a.temp_balance == 1000
    commit_and_notify(remote, wallets, Wallet())
    assert wallet_a.current_balance == 1000
    assert wallet_a.temp_balance == 1000


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
