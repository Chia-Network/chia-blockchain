import asyncio
import pathlib
import tempfile
from aiter import map_aiter
from standard_wallet.wallet import Wallet
from rate_limit.rl_wallet import RLWallet
from chiasim.utils.log import init_logging
from chiasim.remote.api_server import api_server
from chiasim.remote.client import request_response_proxy
from chiasim.clients import ledger_sim
from chiasim.ledger import ledger_api
from chiasim.hashable import Coin, ProgramHash
from chiasim.storage import RAM_DB
from chiasim.utils.server import start_unix_server_aiter
from chiasim.wallet.deltas import additions_for_body, removals_for_body
from chiasim.atoms import hexbytes


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
    tip = run(remote.get_tip())
    index = int(tip["tip_index"])

    for wallet in wallets:
        if isinstance(wallet, RLWallet):
            spend_bundle = wallet.notify(additions, removals, index)
        else:
            spend_bundle = wallet.notify(additions, removals)
        if spend_bundle is not None:
            for bun in spend_bundle:
                _ = run(remote.push_tx(tx=bun))


def test_rl_spend():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete
    # A gives B some money, but B can only send that money to C (and generate change for itself)
    wallet_a = RLWallet()
    wallet_b = RLWallet()
    wallet_c = RLWallet()
    wallets = [wallet_a, wallet_b, wallet_c]

    limit = 10
    interval = 1
    commit_and_notify(remote, wallets, wallet_a)

    origin_coin = wallet_a.my_utxos.copy().pop()
    wallet_b_pk = wallet_b.get_next_public_key().serialize()
    wallet_b.set_origin(origin_coin)
    wallet_b.limit = limit
    wallet_b.interval = interval
    clawback_pk = wallet_a.get_next_public_key().serialize()
    clawback_pk = hexbytes(clawback_pk)
    wallet_b.rl_clawback_pk = clawback_pk
    rl_puzzle = wallet_b.rl_puzzle_for_pk(wallet_b_pk, limit, interval, origin_coin.name(), clawback_pk)
    rl_puzzlehash = ProgramHash(rl_puzzle)
    wallet_a.clawback_puzzlehash = rl_puzzlehash
    wallet_a.rl_receiver_pk = wallet_b_pk
    wallet_a.clawback_pk = clawback_pk
    wallet_a.clawback_interval = interval
    wallet_a.clawback_limit = limit
    wallet_a.clawback_origin = origin_coin.name()

    # wallet A is normal wallet, it sends coin that's rate limited to wallet B
    amount = 5000
    spend_bundle = wallet_a.generate_signed_transaction_with_origin(amount, rl_puzzlehash, origin_coin.name())
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_a.current_balance == 999995000
    assert wallet_b.current_rl_balance == 5000
    assert wallet_c.current_balance == 0

    # Now send some coins from b to c
    commit_and_notify(remote, wallets, Wallet())
    assert wallet_b.rl_available_balance() == 10
    commit_and_notify(remote, wallets, Wallet())
    assert wallet_b.rl_available_balance() == 20

    amount = 20
    spend_bundle = wallet_b.rl_generate_signed_transaction(amount, wallet_c.get_new_puzzlehash())
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_a.current_balance == 999995000
    assert wallet_b.current_rl_balance == 4980
    assert wallet_c.current_balance == 20


    spend_bundle = wallet_a.clawback_rl_coin()
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())
    assert wallet_a.current_balance == 999999980
    assert wallet_b.current_rl_balance == 0
    assert wallet_c.current_balance == 20

def test_rl_interval():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete
    # A gives B some money, but B can only send that money to C (and generate change for itself)
    wallet_a = RLWallet()
    wallet_b = RLWallet()
    wallet_c = RLWallet()
    wallets = [wallet_a, wallet_b, wallet_c]

    limit = 10
    interval = 5
    commit_and_notify(remote, wallets, wallet_a)

    origin_coin = wallet_a.my_utxos.copy().pop()
    wallet_b_pk = wallet_b.get_next_public_key().serialize()
    wallet_b.set_origin(origin_coin)
    wallet_b.limit = limit
    wallet_b.interval = interval
    clawback_pk = wallet_a.get_next_public_key().serialize()
    clawback_pk = hexbytes(clawback_pk)
    wallet_b.rl_clawback_pk = clawback_pk
    rl_puzzle = wallet_b.rl_puzzle_for_pk(wallet_b_pk, limit, interval, origin_coin.name(), clawback_pk)
    rl_puzzlehash = ProgramHash(rl_puzzle)
    wallet_a.clawback_puzzlehash = rl_puzzlehash
    wallet_a.rl_receiver_pk = wallet_b_pk
    wallet_a.clawback_pk = clawback_pk
    wallet_a.clawback_interval = interval
    wallet_a.clawback_limit = limit
    wallet_a.clawback_origin = origin_coin.name()

    # wallet A is normal wallet, it sends coin that's rate limited to wallet B
    amount = 5000
    spend_bundle = wallet_a.generate_signed_transaction_with_origin(amount, rl_puzzlehash, origin_coin.name())
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_a.current_balance == 999995000
    assert wallet_b.current_rl_balance == 5000
    assert wallet_c.current_balance == 0
    assert wallet_b.rl_available_balance() == 0

    commit_and_notify(remote, wallets, Wallet())
    assert wallet_b.rl_available_balance() == 0
    commit_and_notify(remote, wallets, Wallet())
    assert wallet_b.rl_available_balance() == 0
    commit_and_notify(remote, wallets, Wallet())
    assert wallet_b.rl_available_balance() == 0
    commit_and_notify(remote, wallets, Wallet())
    assert wallet_b.rl_available_balance() == 0
    commit_and_notify(remote, wallets, Wallet())
    assert wallet_b.rl_available_balance() == 10


    spend_bundle = wallet_b.rl_generate_signed_transaction(10, wallet_c.get_new_puzzlehash())
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_b.current_rl_balance == 4990
    assert wallet_c.current_balance == 10


def test_rl_interval_more_funds():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete
    # A gives B some money, but B can only send that money to C (and generate change for itself)
    wallet_a = RLWallet()
    wallet_b = RLWallet()
    wallet_c = RLWallet()
    wallets = [wallet_a, wallet_b, wallet_c]

    limit = 100
    interval = 2
    commit_and_notify(remote, wallets, wallet_a)

    origin_coin = wallet_a.my_utxos.copy().pop()
    wallet_b_pk = wallet_b.get_next_public_key().serialize()
    wallet_b.set_origin(origin_coin)
    wallet_b.limit = limit
    wallet_b.interval = interval
    clawback_pk = wallet_a.get_next_public_key().serialize()
    clawback_pk = hexbytes(clawback_pk)
    wallet_b.rl_clawback_pk = clawback_pk
    rl_puzzle = wallet_b.rl_puzzle_for_pk(wallet_b_pk, limit, interval, origin_coin.name(), clawback_pk)
    rl_puzzlehash = ProgramHash(rl_puzzle)
    wallet_a.clawback_puzzlehash = rl_puzzlehash
    wallet_a.rl_receiver_pk = wallet_b_pk
    wallet_a.clawback_pk = clawback_pk
    wallet_a.clawback_interval = interval
    wallet_a.clawback_limit = limit
    wallet_a.clawback_origin = origin_coin.name()

    # wallet A is normal wallet, it sends coin that's rate limited to wallet B
    amount = 5000
    spend_bundle = wallet_a.generate_signed_transaction_with_origin(amount, rl_puzzlehash, origin_coin.name())
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_a.current_balance == 999995000
    assert wallet_b.current_rl_balance == 5000
    assert wallet_c.current_balance == 0
    assert wallet_b.rl_available_balance() == 0

    commit_and_notify(remote, wallets, Wallet())
    assert wallet_b.rl_available_balance() == 0
    commit_and_notify(remote, wallets, Wallet())
    assert wallet_b.rl_available_balance() == 100

    amount = 100
    spend_bundle = wallet_b.rl_generate_signed_transaction(amount, wallet_c.get_new_puzzlehash())
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_b.current_rl_balance == 4900
    assert wallet_c.current_balance == 100

    commit_and_notify(remote, wallets, Wallet())
    commit_and_notify(remote, wallets, Wallet())
    assert wallet_b.rl_available_balance() == 100
    commit_and_notify(remote, wallets, Wallet())
    commit_and_notify(remote, wallets, Wallet())
    assert wallet_b.rl_available_balance() == 200
    commit_and_notify(remote, wallets, Wallet())
    commit_and_notify(remote, wallets, Wallet())
    assert wallet_b.rl_available_balance() == 300
    commit_and_notify(remote, wallets, Wallet())
    commit_and_notify(remote, wallets, Wallet())
    assert wallet_b.rl_available_balance() == 400

def test_spending_over_limit():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete
    # A gives B some money, but B can only send that money to C (and generate change for itself)
    wallet_a = RLWallet()
    wallet_b = RLWallet()
    wallet_c = RLWallet()
    wallets = [wallet_a, wallet_b, wallet_c]

    limit = 20
    interval = 2
    commit_and_notify(remote, wallets, wallet_a)

    origin_coin = wallet_a.my_utxos.copy().pop()
    wallet_b_pk = wallet_b.get_next_public_key().serialize()
    wallet_b.set_origin(origin_coin)
    wallet_b.limit = limit
    wallet_b.interval = interval
    clawback_pk = wallet_a.get_next_public_key().serialize()
    clawback_pk = hexbytes(clawback_pk)
    wallet_b.rl_clawback_pk = clawback_pk
    rl_puzzle = wallet_b.rl_puzzle_for_pk(wallet_b_pk, limit, interval, origin_coin.name(), clawback_pk)
    rl_puzzlehash = ProgramHash(rl_puzzle)
    wallet_a.clawback_puzzlehash = rl_puzzlehash
    wallet_a.rl_receiver_pk = wallet_b_pk
    wallet_a.clawback_pk = clawback_pk
    wallet_a.clawback_interval = interval
    wallet_a.clawback_limit = limit
    wallet_a.clawback_origin = origin_coin.name()

    # wallet A is normal wallet, it sends coin that's rate limited to wallet B
    amount = 5000
    spend_bundle = wallet_a.generate_signed_transaction_with_origin(amount, rl_puzzlehash, origin_coin.name())
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_a.current_balance == 999995000
    assert wallet_b.current_rl_balance == 5000
    assert wallet_c.current_balance == 0

    commit_and_notify(remote, wallets, Wallet())
    commit_and_notify(remote, wallets, Wallet())
    assert wallet_b.rl_available_balance() == 20

    amount = 30
    spend_bundle = wallet_b.rl_generate_signed_transaction(30, wallet_c.get_new_puzzlehash())
    _ = run(remote.push_tx(tx=spend_bundle))
    assert _.args[0].startswith("exception: (<Err.ASSERT_BLOCK_AGE_EXCEEDS_FAILED: 13>")
    commit_and_notify(remote, wallets, Wallet())
    assert wallet_a.current_balance == 999995000
    assert wallet_b.current_rl_balance == 5000
    assert wallet_c.current_balance == 0


def test_rl_aggregation():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete
    # A gives B some money, but B can only send that money to C (and generate change for itself)
    wallet_a = RLWallet()
    wallet_b = RLWallet()
    wallet_c = RLWallet()
    wallets = [wallet_a, wallet_b, wallet_c]

    limit = 10
    interval = 1
    commit_and_notify(remote, wallets, wallet_a)

    origin_coin = wallet_a.my_utxos.copy().pop()
    wallet_b_pk = wallet_b.get_next_public_key().serialize()
    wallet_b.set_origin(origin_coin)
    wallet_b.limit = limit
    wallet_b.interval = interval
    clawback_pk = wallet_a.get_next_public_key().serialize()
    clawback_pk = hexbytes(clawback_pk)
    wallet_b.rl_clawback_pk = clawback_pk
    rl_puzzle = wallet_b.rl_puzzle_for_pk(wallet_b_pk, limit, interval, origin_coin.name(), clawback_pk)
    rl_puzzlehash = ProgramHash(rl_puzzle)
    wallet_a.clawback_puzzlehash = rl_puzzlehash
    wallet_a.rl_receiver_pk = wallet_b_pk
    wallet_a.clawback_pk = clawback_pk
    wallet_a.clawback_interval = interval
    wallet_a.clawback_limit = limit
    wallet_a.clawback_origin = origin_coin.name()

    # wallet A is normal wallet, it sends coin that's rate limited to wallet B
    amount = 5000
    spend_bundle = wallet_a.generate_signed_transaction_with_origin(amount, rl_puzzlehash, origin_coin.name())
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_a.current_balance == 999995000
    assert wallet_b.current_rl_balance == 5000
    assert wallet_c.current_balance == 0

    # Now send some coins from b to c
    commit_and_notify(remote, wallets, Wallet())
    assert wallet_b.rl_available_balance() == 10
    commit_and_notify(remote, wallets, Wallet())
    assert wallet_b.rl_available_balance() == 20

    agg_puzzlehash = wallet_b.rl_get_aggregation_puzzlehash(rl_puzzlehash)
    amount = 5000
    spend_bundle = wallet_a.generate_signed_transaction(amount, agg_puzzlehash)
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    commit_and_notify(remote, wallets, Wallet())
    assert wallet_a.current_balance == 999990000
    assert wallet_b.current_rl_balance == 10000
    assert wallet_c.current_balance == 0


def test_rl_spend_all():
    remote = make_client_server()
    run = asyncio.get_event_loop().run_until_complete
    # A gives B some money, but B can only send that money to C (and generate change for itself)
    wallet_a = RLWallet()
    wallet_b = RLWallet()
    wallet_c = RLWallet()
    wallets = [wallet_a, wallet_b, wallet_c]

    limit = 100
    interval = 1
    commit_and_notify(remote, wallets, wallet_a)

    origin_coin = wallet_a.my_utxos.copy().pop()
    wallet_b_pk = wallet_b.get_next_public_key().serialize()
    wallet_b.set_origin(origin_coin)
    wallet_b.limit = limit
    wallet_b.interval = interval
    clawback_pk = wallet_a.get_next_public_key().serialize()
    clawback_pk = hexbytes(clawback_pk)
    wallet_b.rl_clawback_pk = clawback_pk
    rl_puzzle = wallet_b.rl_puzzle_for_pk(wallet_b_pk, limit, interval, origin_coin.name(), clawback_pk)
    rl_puzzlehash = ProgramHash(rl_puzzle)
    wallet_a.clawback_puzzlehash = rl_puzzlehash
    wallet_a.rl_receiver_pk = wallet_b_pk
    wallet_a.clawback_pk = clawback_pk
    wallet_a.clawback_interval = interval
    wallet_a.clawback_limit = limit
    wallet_a.clawback_origin = origin_coin.name()

    # wallet A is normal wallet, it sends coin that's rate limited to wallet B
    amount = 300
    spend_bundle = wallet_a.generate_signed_transaction_with_origin(amount, rl_puzzlehash, origin_coin.name())
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_a.current_balance == 999999700
    assert wallet_b.current_rl_balance == 300
    assert wallet_c.current_balance == 0

    commit_and_notify(remote, wallets, Wallet())
    assert wallet_b.rl_available_balance() == 100
    commit_and_notify(remote, wallets, Wallet())
    assert wallet_b.rl_available_balance() == 200
    commit_and_notify(remote, wallets, Wallet())
    assert wallet_b.rl_available_balance() == 300

    amount = 300
    spend_bundle = wallet_b.rl_generate_signed_transaction(amount, wallet_c.get_new_puzzlehash())
    _ = run(remote.push_tx(tx=spend_bundle))
    commit_and_notify(remote, wallets, Wallet())

    assert wallet_a.current_balance == 999999700
    assert wallet_b.current_rl_balance == 0
    assert wallet_c.current_balance == 300


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