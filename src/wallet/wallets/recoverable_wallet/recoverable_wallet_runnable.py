import asyncio
import cbor
import sys
from recoverable_wallet import RecoverableWallet
from chiasim.clients.ledger_sim import connect_to_ledger_sim
from chiasim.wallet.deltas import additions_for_body, removals_for_body
from chiasim.hashable import Coin, Header, HeaderHash, Body
from chiasim.hashable import ProgramHash
from chiasim.remote.client import RemoteError
from decimal import Decimal
from blspy import ExtendedPublicKey, PrivateKey


async def view_coins(ledger_api, wallet, most_recent_header):
    print('Recoverable coins:')
    for coin in wallet.my_utxos:
        print(f'Coin ID: {coin.name()}, Amount: {coin.amount}')
    print('Total value: ' + str(wallet.balance()))
    print('\nEscrow coins:')
    escrow_value = 0
    for recovery_string, coin_set in wallet.escrow_coins.items():
        recovery_dict = recovery_string_to_dict(recovery_string)
        escrow_duration = recovery_dict['escrow_duration']
        for coin in coin_set:
            coin_age = await get_coin_age(coin, ledger_api, most_recent_header)
            wait_period = max(escrow_duration - coin_age, 0)
            print(f'Coin ID: {coin.name()}, Block wait: {wait_period}, Amount: {coin.amount}')
        escrow_value += sum([coin.amount for coin in coin_set])
    print('Escrow value: ' + str(escrow_value))


def generate_puzzlehash(wallet):
    print('Puzzle Hash: ' + str(wallet.get_new_puzzlehash()))


async def spend_coins(wallet, ledger_api):
    puzzlehash_string = input('Enter PuzzleHash: ')
    puzzlehash = ProgramHash.from_bytes(bytes.fromhex(puzzlehash_string))
    amount = int(input('Amount: '))
    if amount > wallet.current_balance or amount < 0:
        print('Insufficient funds')
        return None
    tx = wallet.generate_signed_transaction(amount, puzzlehash)
    if tx is not None:
        await ledger_api.push_tx(tx=tx)


async def process_blocks(wallet, ledger_api, last_known_header, current_header_hash):
    r = await ledger_api.hash_preimage(hash=current_header_hash)
    header = Header.from_bytes(r)
    body = Body.from_bytes(await ledger_api.hash_preimage(hash=header.body_hash))
    if header.previous_hash != last_known_header:
        await process_blocks(wallet, ledger_api, last_known_header, header.previous_hash)
    print(f'processing block {HeaderHash(header)}')
    additions = list(additions_for_body(body))
    removals = removals_for_body(body)
    removals = [Coin.from_bytes(await ledger_api.hash_preimage(hash=x)) for x in removals]
    wallet.notify(additions, removals)
    clawback_coins = [coin for coin in additions if wallet.is_in_escrow(coin)]
    if len(clawback_coins) != 0:
        print(f'WARNING! Coins from this wallet have been moved to escrow!\n'
              f'Attempting to send a clawback for these coins:')
        for coin in clawback_coins:
            print(f'Coin ID: {coin.name()}, Amount: {coin.amount}')
        transaction = wallet.generate_clawback_transaction(clawback_coins)
        r = await ledger_api.push_tx(tx=transaction)
        if type(r) is RemoteError:
            print('Clawback failed')
        else:
            print('Clawback transaction submitted')


async def farm_block(wallet, ledger_api, last_known_header):
    coinbase_puzzle_hash = wallet.get_new_puzzlehash()
    fees_puzzle_hash = wallet.get_new_puzzlehash()
    r = await ledger_api.next_block(coinbase_puzzle_hash=coinbase_puzzle_hash, fees_puzzle_hash=fees_puzzle_hash)
    header = r['header']
    header_hash = HeaderHash(header)
    tip = await ledger_api.get_tip()
    await process_blocks(wallet,
                         ledger_api,
                         tip['genesis_hash'] if last_known_header is None else last_known_header,
                         header_hash)
    return header_hash


async def update_ledger(wallet, ledger_api, most_recent_header):
    r = await ledger_api.get_tip()
    if r['tip_hash'] != most_recent_header:
        await process_blocks(wallet,
                             ledger_api,
                             r['genesis_hash'] if most_recent_header is None else most_recent_header,
                             r['tip_hash'])
    return r['tip_hash']


def print_backup(wallet):
    print(f'In the event you lose access to this wallet, the funds in this wallet can be restored '
          f'to another wallet using the following recovery string:\n{wallet.get_backup_string()}')


def recovery_string_to_dict(recovery_string):
    recovery_dict = cbor.loads(bytes.fromhex(recovery_string))
    recovery_dict['root_public_key'] = ExtendedPublicKey.from_bytes(recovery_dict['root_public_key'])
    recovery_dict['secret_key'] = PrivateKey.from_bytes(recovery_dict['secret_key'])
    recovery_dict['stake_factor'] = Decimal(recovery_dict['stake_factor'])
    return recovery_dict


async def get_unspent_coins(ledger_api, header_hash):
    r = await ledger_api.get_tip()
    if r['genesis_hash'] == header_hash:
        return set()

    r = await ledger_api.hash_preimage(hash=header_hash)
    header = Header.from_bytes(r)
    unspent_coins = await get_unspent_coins(ledger_api, header.previous_hash)
    body = Body.from_bytes(await ledger_api.hash_preimage(hash=header.body_hash))
    additions = list(additions_for_body(body))
    unspent_coins.update(additions)
    removals = removals_for_body(body)
    removals = [Coin.from_bytes(await ledger_api.hash_preimage(hash=x)) for x in removals]
    unspent_coins.difference_update(removals)
    return unspent_coins


async def restore(ledger_api, wallet, header_hash):
    recovery_string = input('Enter the recovery string of the wallet to be restored: ')
    recovery_dict = recovery_string_to_dict(recovery_string)
    root_public_key_serialized = recovery_dict['root_public_key'].serialize()

    recovery_pubkey = recovery_dict['root_public_key'].public_child(0).get_public_key().serialize()
    unspent_coins = await get_unspent_coins(ledger_api, header_hash)
    recoverable_coins = []
    print('scanning', end='')
    for coin in unspent_coins:
        if wallet.can_generate_puzzle_hash_with_root_public_key(coin.puzzle_hash,
                                                                root_public_key_serialized,
                                                                recovery_dict['stake_factor'],
                                                                recovery_dict['escrow_duration']):
            recoverable_coins.append(coin)
            print('*', end='', flush=True)
        else:
            print('.', end='', flush=True)
    recoverable_amount = sum([coin.amount for coin in recoverable_coins])
    print(f'\nFound {len(recoverable_coins)} coins totaling {recoverable_amount}')
    stake_amount = round(recoverable_amount * (recovery_dict['stake_factor'] - 1))
    if wallet.current_balance < stake_amount:
        print(f'Insufficient funds to stake the recovery process. {stake_amount} needed.')
        return
    for coin in recoverable_coins:
        print(f'Coin ID: {coin.name()}, Amount: {coin.amount}')
        pubkey = wallet.find_pubkey_for_hash(coin.puzzle_hash,
                                             root_public_key_serialized,
                                             recovery_dict['stake_factor'],
                                             recovery_dict['escrow_duration'])
        signed_transaction, destination_puzzlehash, amount = \
            wallet.generate_signed_recovery_to_escrow_transaction(coin,
                                                                  recovery_pubkey,
                                                                  pubkey,
                                                                  recovery_dict['stake_factor'],
                                                                  recovery_dict['escrow_duration'])
        child = Coin(coin.name(), destination_puzzlehash, amount)
        r = await ledger_api.push_tx(tx=signed_transaction)
        if type(r) is RemoteError:
            print(f'Failed to recover {coin.name()}')
        else:
            print(f'Recovery transaction submitted for Coin ID: {coin.name()}')
            wallet.escrow_coins[recovery_string].add(child)


async def get_coin_age(coin, ledger_api, header_hash):
    r = await ledger_api.get_tip()
    if r['genesis_hash'] == header_hash:
        return float('-inf')

    r = await ledger_api.hash_preimage(hash=header_hash)
    header = Header.from_bytes(r)
    body = Body.from_bytes(await ledger_api.hash_preimage(hash=header.body_hash))
    additions = list(additions_for_body(body))
    if coin in additions:
        return 0
    return 1 + await get_coin_age(coin, ledger_api, header.previous_hash)


async def recover_escrow_coins(ledger_api, wallet):
    removals = set()
    for recovery_string, coin_set in wallet.escrow_coins.items():
        for coin in coin_set:
            print("Attempting to recover " + str(coin.name()))
        recovery_dict = recovery_string_to_dict(recovery_string)
        root_public_key = recovery_dict['root_public_key']
        secret_key = recovery_dict['secret_key']
        escrow_duration = recovery_dict['escrow_duration']

        signed_transaction = wallet.generate_recovery_transaction(coin_set,
                                                                  root_public_key,
                                                                  secret_key,
                                                                  escrow_duration)
        r = await ledger_api.push_tx(tx=signed_transaction)
        if type(r) is RemoteError:
            print('Too soon to recover coin')
        else:
            print('Recovery transaction submitted')
            removals.add(recovery_string)
    for recovery_string in removals:
        wallet.escrow_coins.pop(recovery_string)


async def main():
    ledger_api = await connect_to_ledger_sim('localhost', 9868)
    print('Creating a new Recoverable Wallet')
    stake_factor = input('Input stake factor (defaults to 1.1): ')
    if stake_factor == '':
        stake_factor = '1.1'
    escrow_duration = input('Enter escrow duration in number of blocks (defaults to 3): ')
    if escrow_duration == '':
        escrow_duration = '3'
    wallet = RecoverableWallet(Decimal(stake_factor), int(escrow_duration))
    most_recent_header = None
    selection = ''
    while selection != 'q':
        print('\nAvailable commands:')
        print('1: View Coins')
        print('2: Spend Coins')
        print('3: Get Updates')
        print('4: Farm Block')
        print('5: Generate Puzzle Hash')
        print('6: Print Recovery String')
        print('7: Recover Coins To Escrow')
        print('8: Recover Escrow Coins')
        print('q: Quit\n')
        selection = input()
        print()
        if selection == '1':
            await view_coins(ledger_api, wallet, most_recent_header)
        elif selection == '2':
            await spend_coins(wallet, ledger_api)
        elif selection == '3':
            most_recent_header = await update_ledger(wallet, ledger_api, most_recent_header)
        elif selection == '4':
            most_recent_header = await farm_block(wallet, ledger_api, most_recent_header)
        elif selection == '5':
            generate_puzzlehash(wallet)
        elif selection == '6':
            print_backup(wallet)
        elif selection == '7':
            await restore(ledger_api, wallet, most_recent_header)
        elif selection == '8':
            await recover_escrow_coins(ledger_api, wallet)
    sys.exit(0)


run = asyncio.get_event_loop().run_until_complete
run(main())

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