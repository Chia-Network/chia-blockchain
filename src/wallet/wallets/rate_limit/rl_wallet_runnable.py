import asyncio
from rate_limit.rl_wallet import RLWallet
from chiasim.clients.ledger_sim import connect_to_ledger_sim
from chiasim.wallet.deltas import additions_for_body, removals_for_body
from chiasim.hashable import Coin
from chiasim.hashable.Body import BodyList
from utilities.decorations import print_leaf, divider, prompt
from chiasim.hashable import ProgramHash
from binascii import hexlify
from blspy import PublicKey
from chiasim.atoms import hexbytes


def get_int(message):
    amount = ""
    while amount == "":
        amount = input(message)
        if amount == "q":
            return "q"
        if not amount.isdigit():
            amount = ""
        if amount.isdigit():
            amount = int(amount)
    return amount


def print_my_details(wallet):
    print()
    print(divider)
    print(" \u2447 Wallet Details \u2447")
    print()
    print("Name: " + wallet.name)
    pk = hexlify(wallet.get_next_public_key().serialize()).decode("ascii")
    print(f"New pubkey: {pk}")
    pk = hexlify(wallet.pubkey_orig).decode("ascii")
    print(f"RL pubkey: {pk}")
    print(divider)


def view_funds(wallet):
    print(f"Current balance: {wallet.current_balance}")
    print(f"Current rate limited balance: {wallet.current_rl_balance}")
    print(f"Available RL Balance: {wallet.rl_available_balance()}")
    print("UTXOs: ")
    print([x.amount for x in wallet.temp_utxos if x.amount > 0])
    if wallet.rl_coin is not None:
        print(f"RL Coin:\nAmount {wallet.rl_coin.amount} \nRate Limit: {wallet.limit}Chia/{wallet.interval}Blocks")
        print(f"RL Coin puzzlehash: {wallet.rl_coin.puzzle_hash}")


def receive_rl_coin(wallet):
    print()
    print("Please enter the initialization string:")
    coin_string = input(prompt)
    arr = coin_string.split(":")
    ph = ProgramHash(bytes.fromhex(arr[1]))
    print(ph)
    origin = {"parent_coin_info": arr[0], "puzzle_hash": ph, "amount": arr[2], "name": arr[3]}
    limit = arr[4]
    interval = arr[5]
    clawback_pk = arr[6]
    print(origin)
    wallet.rl_clawback_pk = clawback_pk
    wallet.set_origin(origin)
    wallet.limit = int(limit)
    wallet.interval = int(interval)
    print("Rate limited coin is ready to be received")


async def create_rl_coin(wallet, ledger_api):
    utxo_list = list(wallet.my_utxos)
    if len(utxo_list) == 0:
        print("No UTXOs available.")
        return
    print("Select UTXO for origin: ")
    num = 0
    for utxo in utxo_list:
        print(f"{num}) coin_name:{utxo.name()} amount:{utxo.amount}")
        num += 1
    selected = get_int("Select UTXO for origin: ")
    origin = utxo_list[selected]
    print("Rate limit is defined as amount of Chia per time interval.(Blocks)\n")
    rate = get_int("Specify the Chia amount limit: ")
    interval = get_int("Specify the interval length (blocks): ")
    print("Specify the pubkey of receiver")
    pubkey = input(prompt)
    my_pubkey = hexbytes(wallet.get_next_public_key().serialize())
    send_amount = get_int("Enter amount to give recipient: ")
    print(f"\n\nInitialization string: {origin.parent_coin_info}:{origin.puzzle_hash}:"
          f"{origin.amount}:{origin.name()}:{rate}:{interval}:{my_pubkey}")
    print("\nPaste Initialization string to the receiver")
    print("Press Enter to continue:")
    input(prompt)
    pubkey = PublicKey.from_bytes(bytes.fromhex(pubkey)).serialize()
    rl_puzzle = wallet.rl_puzzle_for_pk(pubkey, rate, interval, origin.name(), my_pubkey)
    rl_puzzlehash = ProgramHash(rl_puzzle)
    wallet.clawback_puzzlehash = rl_puzzlehash
    wallet.clawback_origin = origin.name()
    wallet.clawback_limit = rate
    wallet.clawback_interval = interval
    wallet.clawback_pk = my_pubkey
    wallet.rl_receiver_pk = pubkey

    spend_bundle = wallet.generate_signed_transaction_with_origin(send_amount, rl_puzzlehash, origin.name())
    _ = await ledger_api.push_tx(tx=spend_bundle)



async def spend_rl_coin(wallet, ledger_api):
    if wallet.rl_available_balance() == 0:
        print("Available rate limited coin balance is 0!")
        return
    receiver_pubkey = input("Enter receiver's pubkey: 0x")
    receiver_pubkey = PublicKey.from_bytes(bytes.fromhex(receiver_pubkey)).serialize()
    amount = -1
    while amount > wallet.current_rl_balance or amount < 0:
        amount = input("Enter amount to give recipient: ")
        if amount == "q":
            return
        if not amount.isdigit():
            amount = -1
        amount = int(amount)

    puzzlehash = wallet.get_puzzlehash_for_pk(receiver_pubkey)
    spend_bundle = wallet.rl_generate_signed_transaction(amount, puzzlehash)
    _ = await ledger_api.push_tx(tx=spend_bundle)


async def retrieve_rate_limited_coin(wallet, ledger_api):
    if wallet.clawback_origin is None:
        print("There is no retrievable RL Coins")
        return 
    spend_bundle = wallet.clawback_rl_coin()
    _ = await ledger_api.push_tx(tx=spend_bundle)
    if _.get("response").startswith("accepted"):
        amount =  spend_bundle.coin_solutions._items[0].coin.amount
        print(f"{amount} Chia will be retrieved in the next block")



async def add_funds_to_rl_coin(wallet, ledger_api):
    utxo_list = list(wallet.my_utxos)
    if len(utxo_list) == 0:
        print("No UTXOs available.")
        return
    rl_puzzlehash = input("Enter RL coin puzzlehash: ")
    agg_puzzlehash = wallet.rl_get_aggregation_puzzlehash(rl_puzzlehash)
    amount = -1
    while amount > wallet.current_balance or amount < 0:
        amount = input("Enter amount to add into RL coin: ")
        if amount == "q":
            return
        if not amount.isdigit():
            amount = -1
        amount = int(amount)

    spend_bundle = wallet.generate_signed_transaction(amount, agg_puzzlehash)
    _ = await ledger_api.push_tx(tx=spend_bundle)


async def update_ledger(wallet, ledger_api, most_recent_header):
    if most_recent_header is None:
        r = await ledger_api.get_all_blocks()
    else:
        r = await ledger_api.get_recent_blocks(most_recent_header=most_recent_header)
    update_list = BodyList.from_bytes(r)
    tip = await ledger_api.get_tip()
    index = int(tip["tip_index"])
    for body in update_list:
        additions = list(additions_for_body(body))
        removals = removals_for_body(body)
        removals = [Coin.from_bytes(await ledger_api.hash_preimage(hash=x)) for x in removals]
        spend_bundle_list = wallet.notify(additions, removals, index)
        if spend_bundle_list is not None:
            for spend_bundle in spend_bundle_list:
                _ = await ledger_api.push_tx(tx=spend_bundle)

    return most_recent_header


async def new_block(wallet, ledger_api):
    coinbase_puzzle_hash = wallet.get_new_puzzlehash()
    fees_puzzle_hash = wallet.get_new_puzzlehash()
    r = await ledger_api.next_block(coinbase_puzzle_hash=coinbase_puzzle_hash, fees_puzzle_hash=fees_puzzle_hash)
    body = r["body"]
    tip = await  ledger_api.get_tip()
    index = tip["tip_index"]
    most_recent_header = r['header']
    additions = list(additions_for_body(body))
    removals = removals_for_body(body)
    removals = [Coin.from_bytes(await ledger_api.hash_preimage(hash=x)) for x in removals]
    wallet.notify(additions, removals, index)
    return most_recent_header


async def main_loop():
    ledger_api = await connect_to_ledger_sim("localhost", 9868)
    selection = ""
    wallet = RLWallet()
    most_recent_header = None
    print_leaf()
    print()
    print("Welcome to your Chia Rate Limited Wallet.")
    print()
    my_pubkey_orig = wallet.get_next_public_key().serialize()
    wallet.pubkey_orig = my_pubkey_orig
    print("Your pubkey is: " + hexlify(my_pubkey_orig).decode('ascii'))

    while selection != "q":
        print()
        print(divider)
        print(" \u2447 Menu \u2447")
        print()
        tip = await ledger_api.get_tip()
        print("Block: ", tip["tip_index"])
        print()
        print("Select a function:")
        print("\u2448 1 Wallet Details")
        print("\u2448 2 View Funds")
        print("\u2448 3 Get Update")
        print("\u2448 4 *GOD MODE* Farm Block / Get Money")
        print("\u2448 5 Receive a new rate limited coin")
        print("\u2448 6 Send a new rate limited coin")
        print("\u2448 7 Spend from rate limited coin")
        print("\u2448 8 Add funds to existing rate limited coin")
        print("\u2448 9 Retrieve sent rate limited coin")
        print("\u2448 q Quit")
        print(divider)
        print()

        selection = input(prompt)
        if selection == "1":
            print_my_details(wallet)
        elif selection == "2":
            view_funds(wallet)
        elif selection == "3":
            most_recent_header = await update_ledger(wallet, ledger_api, most_recent_header)
        elif selection == "4":
            most_recent_header = await new_block(wallet, ledger_api)
        elif selection == "5":
            receive_rl_coin(wallet)
        elif selection == "6":
            await create_rl_coin(wallet, ledger_api)
        elif selection == "7":
            await spend_rl_coin(wallet, ledger_api)
        elif selection == "8":
            await add_funds_to_rl_coin(wallet, ledger_api)
        elif selection == "9":
            await retrieve_rate_limited_coin(wallet, ledger_api)


def main():
    run = asyncio.get_event_loop().run_until_complete
    run(main_loop())

if __name__ == "__main__":
    main()


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