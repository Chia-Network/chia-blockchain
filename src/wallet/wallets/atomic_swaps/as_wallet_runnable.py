import asyncio
import os
from atomic_swaps.as_wallet import ASWallet
from chiasim.clients.ledger_sim import connect_to_ledger_sim
from chiasim.wallet.deltas import additions_for_body, removals_for_body
from chiasim.hashable import Coin
from chiasim.hashable.Body import BodyList
from utilities.decorations import print_leaf, divider, prompt, start_list, close_list, selectable, informative
from clvm_tools import binutils
from utilities.puzzle_utilities import pubkey_format, puzzlehash_from_string
from binascii import hexlify


# prints wallet details, allows wallet name edit, generates new pubkeys and new puzzlehashes
def print_my_details(wallet):
    print()
    print(divider)
    print(f" {informative} Wallet Details / Generate Puzzlehash {informative}")
    print()
    print(f"Name: {wallet.name}")
    print(f"New pubkey: {hexlify(wallet.get_next_public_key().serialize()).decode('ascii')}")
    print(f"New puzzlehash: {wallet.get_new_puzzlehash()}")
    complete_edit = False
    while not complete_edit:
        print()
        print("Would you like to edit your wallet's name (type 'name'), generate a new pubkey (type 'pubkey'), generate a new puzzlehash (type 'puzzlehash'), or return to the menu (type 'menu')?")
        choice = input(prompt)
        if choice == "name":
            complete_name = False
            while not complete_name:
                print()
                print("Enter a new name for your wallet:")
                name_new = input(prompt)
                if name_new == "":
                    print()
                    print("Your wallet's name cannot be blank.")
                    complete = False
                    while not complete:
                        print()
                        print("Would you like to enter a new name (type 'name') or return to the menu (type 'menu')?")
                        choice = input(prompt)
                        if choice == "menu":
                            print(divider)
                            return
                        elif choice == "name":
                            complete = True
                        else:
                            print()
                            print("You entered an invalid selection.")
                else:
                    wallet.set_name(name_new)
                    print()
                    print("Your wallet's name has been changed.")
                    complete_name = True
        elif choice == "pubkey":
            print()
            print(f"New pubkey: {hexlify(wallet.get_next_public_key().serialize()).decode('ascii')}")
        elif choice == "puzzlehash":
            print()
            print(f"New puzzlehash: {wallet.get_new_puzzlehash()}")
        elif choice == "menu":
            print(divider)
            return
        else:
            print()
            print("You entered an invalid selection.")
            choice = "edit"
    print(divider)


# view funds in wallet
# pending atomic swap coins are marked with an asterisk (*)
def view_funds(wallet, as_swap_list):
    print()
    print(divider)
    print(f" {informative} View Funds {informative}")
    puzzlehashes = []
    for swap in as_swap_list:
        puzzlehashes.append(swap["outgoing puzzlehash"])
        puzzlehashes.append(swap["incoming puzzlehash"])
    coins = [x.amount for x in wallet.my_utxos]
    coins.extend("{}{}".format("*", x.amount) for x in wallet.as_pending_utxos)
    if coins == []:
        print()
        print("Your coins:")
        print("[ NO COINS ]")
    else:
        print()
        print("Your coins: ")
        print(coins)
    print(divider)


def view_contacts(as_contacts):
    print()
    print("Your contacts:")
    if as_contacts == {}:
        print("- NO CONTACTS -")
    else:
        for name in as_contacts:
            print(f"{selectable} {name}")


def view_contacts_details(as_contacts):
    print()
    print(divider)
    print(f" {informative} View Contacts {informative}")
    choice = "view"
    while choice == "view":
        view_contacts(as_contacts)
        if as_contacts == {}:
            print(divider)
            return
        print()
        print("Type the name of a contact to view their contact details or type 'menu' to return to menu:")
        name = input(prompt)
        if name == "menu":
            print(divider)
            return
        elif name in as_contacts:
            print()
            print(f"Name: {name}")
            print(f"Pubkey: {as_contacts[name][0]}")
            if as_contacts[name][1][0] == []:
                print("AS coin outgoing puzzlehashes: none")
            else:
                print(f"AS coin outgoing puzzlehashes: {', '.join(as_contacts[name][1][0])}")
            if as_contacts[name][1][1] == []:
                print("AS coin incoming puzzlehashes: none")
            else:
                print(f"AS coin incoming puzzlehashes: {', '.join(as_contacts[name][1][1])}")
        else:
            print()
            print("That name is not in your contact list.")
        complete = False
        while not complete:
            print()
            print("Type 'view' to view the details of another contact, or 'menu' to return to menu:")
            choice = input(prompt)
            if choice == "menu":
                print(divider)
                return
            elif choice == "view":
                complete = True
            else:
                print()
                print("You entered an invalid selection.")


def add_contact(wallet, as_contacts):
    print()
    print(divider)
    print(f" {informative} Add Contact {informative}")
    choice = "add"
    while choice == "add":
        print()
        print("Contact name:")
        name = input(prompt)
        while name == "" or name == "menu":
            print()
            print("You have entered an invalid contact name.")
            print()
            print("Please enter a contact name or type 'menu' to return to menu:")
            name = input(prompt)
            if name == "menu":
                print(divider)
                return
        print("Please enter your contact's pubkey:")
        pubkey = input(prompt)
        complete = False
        while not complete:
            try:
                hexval = int(pubkey, 16)
                if len(pubkey) != 96:
                    print()
                    print("This is not a valid pubkey. Please enter a valid pubkey or type 'menu' to return to menu: ")
                    pubkey = input(prompt)
                    if pubkey == "menu":
                        print(divider)
                        return
                else:
                    complete = True
            except:
                print()
                print("This is not a valid pubkey. Please enter a valid pubkey or type 'menu' to return to menu: ")
                pubkey = input(prompt)
                if pubkey == "menu":
                    print(divider)
                    return
        as_contacts[name] = [pubkey, [[],[]]]
        print()
        print(f"{name} has been added to your contact list.")
        complete = False
        while not complete:
            print()
            print("Type 'add' to add another contact, or 'menu' to return to menu:")
            choice = input(prompt)
            if choice == "menu":
                print(divider)
                return
            elif choice == "add":
                complete = True
            else:
                print()
                print("You entered an invalid selection.")


def edit_contact(wallet, as_contacts):
    print()
    print(divider)
    print(f" {informative} Edit Contact {informative}")
    choice = "edit"
    while choice == "edit":
        view_contacts(as_contacts)
        if as_contacts == {}:
            print()
            print("There are no available contacts to edit because your contact list is empty.")
            return
        else:
            print()
            print("Type the name of the contact you'd like to edit:")
            name = input(prompt)
            if name not in as_contacts:
                print()
                print("The name you entered is not in your contacts list.")
                complete = False
                while not complete:
                    print()
                    print("Type 'edit' to enter a different name, or 'menu' to return to menu:")
                    choice = input(prompt)
                    if choice == "menu":
                        print(divider)
                        return
                    elif choice == "edit":
                        complete = True
                    else:
                        print()
                        print("You entered an invalid selection.")
            else:
                choice = False
                while not choice:
                    print()
                    print(f"Name: {name}")
                    print(f"Pubkey: {as_contacts[name][0]}")
                    print(f"AS coin outgoing puzzlehashes: {', '.join(as_contacts[name][1][0])}")
                    print(f"AS coin incoming puzzlehashes: {', '.join(as_contacts[name][1][1])}")
                    print()
                    print("Would you like to edit the name (type 'name') or the pubkey (type 'pubkey') for this contact? (Or type 'menu' to return to the menu.)")
                    choice = input(prompt)
                    if choice == "name":
                        print()
                        print("Enter the new name for this contact or type 'menu' to return to the menu:")
                        name_new = input(prompt)
                        while name_new == "":
                            print()
                            print("Contact name cannot be blank.")
                            print()
                            print("Enter the new name for this contact or type 'menu' to return to the menu:")
                            name_new = input(prompt)
                        if name_new == "menu":
                            print(divider)
                            return
                        as_contacts[name_new] = as_contacts.pop(name)
                        print()
                        print(f"{name_new}'s name has been updated.")
                    elif choice == "pubkey":
                        print()
                        print("Enter the new pubkey for this contact or type 'menu' to return to the menu:")
                        pubkey_new = input(prompt)
                        if pubkey_new == "menu":
                            print(divider)
                            return
                        complete = False
                        while not complete:
                            try:
                                hexval = int(pubkey_new, 16)
                                if len(pubkey_new) != 96:
                                    print()
                                    print("This is not a valid pubkey.")
                                    print()
                                    print("Please enter a valid pubkey or type 'menu' to return to menu:")
                                    pubkey_new = input(prompt)
                                    if pubkey_new == "menu":
                                        print(divider)
                                        return
                                else:
                                    complete = True
                            except:
                                print()
                                print("This is not a valid pubkey.")
                                print()
                                print("Please enter a valid pubkey or type 'menu' to return to menu:")
                                pubkey_new = input(prompt)
                                if pubkey_new == "menu":
                                    print(divider)
                                    return
                        as_contacts[name][0] = pubkey_new
                        print()
                        print(f"{name}'s pubkey has been updated.")
                    elif choice == "menu":
                        print(divider)
                        return
                    else:
                        choice = False
                        print()
                        print("You entered an invalid selection.")
                complete = False
                while not complete:
                    print()
                    print("Type 'edit' to add another contact, or 'menu' to return to menu:")
                    choice = input(prompt)
                    if choice == "menu":
                        print(divider)
                        return
                    elif choice == "edit":
                        complete = True
                    else:
                        print()
                        print("You entered an invalid selection.")


def view_current_atomic_swaps(as_swap_list):
    print()
    print(divider)
    print(f" {informative} View Current Atomic Swaps {informative}")
    view_swaps(as_swap_list)
    print(divider)


def print_swap_details(swap):
    print(start_list)
    print(f"Atomic swap partner: {swap['swap partner']}")
    print(f"Atomic swap partner pubkey: {swap['partner pubkey']}")
    print(f"Atomic swap amount: {swap['amount']}")
    print(f"Atomic swap secret: {swap['secret']}")
    print(f"Atomic swap secret hash: {swap['secret hash']}")
    print(f"Atomic swap my pubkey: {swap['my swap pubkey']}")
    print(f"Atomic swap outgoing puzzlehash: {swap['outgoing puzzlehash']}")
    print(f"Atomic swap timelock time (outgoing coin): {swap['timelock time outgoing']}")
    print(f"Atomic swap timelock block height (outgoing coin): {swap['timelock block height outgoing']}")
    print(f"Atomic swap incoming puzzlehash: {swap['incoming puzzlehash']}")
    print(f"Atomic swap timelock time (incoming coin): {swap['timelock time incoming']}")
    print(f"Atomic swap timelock block height (incoming coin): {swap['timelock block height incoming']}")
    print(close_list)


def view_swaps(as_swap_list):
    if as_swap_list == []:
        print()
        print("You are not currently participating in any atomic swaps.")
    else:
        print()
        print("Your current atomic swaps:")
        for swap in as_swap_list:
            print_swap_details(swap)


# sets partner for an atomic swap
# if partner does not already exist in contacts list, creates new contact for partner
async def set_partner(wallet, ledger_api, as_contacts, method):
    view_contacts(as_contacts)
    print()
    print("Choose a contact for the atomic swap. If your partner is not currently in your contact list, enter their name now to add them to your contacts:")
    complete = False
    while not complete:
        swap_partner = input(prompt)
        if swap_partner == "" or swap_partner == "menu":
            print()
            print("You have entered an invalid swap partner name. Please enter a valid name, or type 'menu' to cancel the atomic swap:")
            swap_partner = input(prompt)
            if swap_partner == "menu":
                return None, None, None, None
        else:
            complete = True
    if swap_partner not in as_contacts:
        as_contacts[swap_partner] = ["unknown", [[],[]]]
    if method == "init":
        print()
        my_swap_pubkey = hexlify(wallet.get_next_public_key().serialize()).decode('ascii')
        print("This is your pubkey for this swap:")
        print(my_swap_pubkey)
        print()
        print("Send the above pubkey to your swap partner, and then press 'return' to continue.")
        confirm = input(prompt)
        print()
        print("Enter your swap partner's pubkey:")
        partner_pubkey = input(prompt)
        complete = False
        while not complete:
            try:
                hexval = int(partner_pubkey, 16)
                if len(partner_pubkey) != 96:
                    print()
                    print("This is not a valid pubkey. Please enter a valid pubkey, or type 'menu' to cancel the atomic swap:")
                    partner_pubkey = input(prompt)
                    if partner_pubkey == "menu":
                        return None, None, None, None
                else:
                    complete = True
            except:
                print()
                print("This is not a valid pubkey. Please enter a valid pubkey, or type 'menu' to cancel the atomic swap:")
                partner_pubkey = input(prompt)
                if partner_pubkey == "menu":
                    return None, None, None, None
        tip_at_start = await ledger_api.get_tip()
        tip_index_at_start = tip_at_start["tip_index"]
    elif method == "add":
        print()
        print("Enter your swap partner's pubkey:")
        partner_pubkey = input(prompt)
        complete = False
        while not complete:
            try:
                hexval = int(partner_pubkey, 16)
                if len(partner_pubkey) != 96:
                    print()
                    print("This is not a valid pubkey. Please enter a valid pubkey, or type 'menu' to cancel the atomic swap:")
                    partner_pubkey = input(prompt)
                    if partner_pubkey == "menu":
                        return None, None, None, None
                else:
                    complete = True
            except:
                print()
                print("This is not a valid pubkey. Please enter a valid pubkey, or type 'menu' to cancel the atomic swap:")
                partner_pubkey = input(prompt)
                if partner_pubkey == "menu":
                    return None, None, None, None
        print()
        my_swap_pubkey = hexlify(wallet.get_next_public_key().serialize()).decode('ascii')
        print("This is your pubkey for this swap:")
        print(my_swap_pubkey)
        print()
        print("Send the above pubkey to your swap partner, and then press 'return' to continue.")
        tip_at_start = await ledger_api.get_tip()
        tip_index_at_start = tip_at_start["tip_index"]
        confirm = input(prompt)
    if as_contacts[swap_partner][0] == "unknown":
        as_contacts[swap_partner][0] = partner_pubkey
    return my_swap_pubkey, swap_partner, partner_pubkey, tip_index_at_start


# sets amount to be swapped
def set_amount(wallet, as_contacts):
    print()
    print(f"Your coins: {[x.amount for x in wallet.my_utxos]}")
    print()
    print("Enter the amount being swapped:")
    amount = input(prompt)
    try:
        amount = int(amount)
    except ValueError:
        print()
        print("Invalid input: You entered an invalid amount.")
        return None
    if amount <= 0:
        print()
        print("Invalid input: The amount must be greater than 0.")
        return None
    elif wallet.current_balance <= amount:
        print()
        print("Invalid input: This amount exceeds your wallet balance.")
        return None
    else:
        return amount


# sets the timelock for the swap initiator's outgoing coin / swap adder's incoming coin
def set_timelock(wallet, as_contacts, method):
    if method == "init":
        print()
        print("Enter the timelock time for your outgoing coin (your swap partner's outgoing coin's timelock time will be half of this value):")
        time = input(prompt)
    elif method == "add":
        print()
        print("Enter the timelock time for your swap partner's outgoing coin (your outgoing coin's timelock time will be half of this value):")
        time = input(prompt)
    try:
        timelock = int(time)
    except ValueError:
        print()
        print("Invalid input: You entered an invalid timelock time.")
        return None
    if (timelock < 2) or (timelock % 2 != 0):
        print()
        print("Invalid input: Timelock time must be an even integer greater or equal to 2.")
        return None
    else:
        return timelock


# sets the swap initiator's swap parameters
async def set_parameters_init(wallet, ledger_api, as_contacts):
    complete_set_partner = False
    while not complete_set_partner:
        my_swap_pubkey, swap_partner, partner_pubkey, tip_index_at_start = await set_partner(wallet, ledger_api, as_contacts, "init")
        if my_swap_pubkey == None and swap_partner == None and partner_pubkey == None:
            return None, None, None, None, None, None, None, "menu"
        else:
            complete_set_partner = True
    complete_set_amount = False
    while not complete_set_amount:
        amount = set_amount(wallet, as_contacts)
        if amount == None:
            complete = False
            while not complete:
                print()
                print("Type 'amount' to enter a new amount, or type 'menu' to cancel the atomic swap:")
                choice = input(prompt)
                if choice == "menu":
                    return None, None, None, None, None, None, None, "menu"
                elif choice == "amount":
                    complete = True
                else:
                    print()
                    print("You entered an invalid selection.")
        else:
            complete_set_amount = True
    secret = hexlify(os.urandom(256)).decode('ascii')
    secret_hash = wallet.as_generate_secret_hash(secret)
    print()
    print("The hash of the secret for this swap is:")
    print(secret_hash)
    print()
    print("Please send the hash of the secret to your swap partner, and then press 'return' to continue.")
    confirm = input(prompt)
    complete_set_timelock = False
    while not complete_set_timelock:
        timelock = set_timelock(wallet, as_contacts, "init")
        if timelock == None:
            complete = False
            while not complete:
                print()
                print("Type 'time' to enter a new timelock time, or type 'menu' to cancel the atomic swap:")
                choice = input(prompt)
                if choice == "menu":
                    return None, None, None, None, None, None, None, "menu"
                elif choice == "time":
                    complete = True
                else:
                    print()
                    print("You entered an invalid selection.")
        else:
            complete_set_timelock = True
    return my_swap_pubkey, swap_partner, partner_pubkey, amount, secret, secret_hash, timelock, None


# adds the swap initiator's incoming coin's puzzlehash to their swap parameters
def add_puzzlehash_init(wallet):
    complete = False
    while not complete:
        print()
        print("Enter your incoming coin's puzzlehash (get this information from your swap partner), or type 'menu' to cancel the atomic swap:")
        puzzlehash = input(prompt)
        if puzzlehash == "menu":
            return puzzlehash
        if puzzlehash == "":
            print()
            print("Invalid input: The incoming coin's puzzlehash cannot be left blank.")
        else:
            try:
                hexval = int(puzzlehash, 16)
                if len(puzzlehash) != 64:
                    print()
                    print("Invalid input: You did not enter a valid puzzlehash.")
                else:
                    complete = True
            except:
                print()
                print("Invalid input: You did not enter a valid puzzlehash.")
    return puzzlehash


# begins creating the swap initiator's swap
# sets parameters
# creates swap initiator's outgoing coin
async def init_swap_start(wallet, ledger_api, as_contacts, as_swap_list):
    print()
    print(divider)
    print(f" {informative} Initiate Atomic Swap {informative}")
    my_swap_pubkey, swap_partner, partner_pubkey, amount, secret, secret_hash, timelock, menu = await set_parameters_init(wallet, ledger_api, as_contacts)
    if menu == "menu":
        print(divider)
        return None, None, None
    tip = await ledger_api.get_tip()
    timelock_outgoing = timelock
    timelock_block_outgoing = int(timelock_outgoing + tip["tip_index"])
    puzzlehash_outgoing = wallet.as_get_new_puzzlehash(bytes.fromhex(my_swap_pubkey), bytes.fromhex(partner_pubkey), amount, timelock_block_outgoing, secret_hash)
    puzzlehash_incoming = "unknown"
    timelock_incoming = int(0.5 * timelock)
    timelock_block_incoming = "unknown"
    spend_bundle = wallet.generate_signed_transaction(amount, puzzlehash_outgoing)
    print()
    print("This is the puzzlehash of your outgoing coin:")
    print(hexlify(puzzlehash_outgoing).decode('ascii'))
    print()
    print("Please send your outgoing puzzlehash to your swap partner, and press 'return' to continue.")
    confirm = input(prompt)
    new_swap = {
            "swap partner" : swap_partner,
    		"partner pubkey" : partner_pubkey,
    		"amount" : amount,
    		"secret" : secret,
            "secret hash" : secret_hash,
            "my swap pubkey" : my_swap_pubkey,
            "outgoing puzzlehash" : hexlify(puzzlehash_outgoing).decode('ascii'),
            "timelock time outgoing" : timelock_outgoing,
            "timelock block height outgoing" : timelock_block_outgoing,
            "incoming puzzlehash" : puzzlehash_incoming,
            "timelock time incoming" : timelock_incoming,
            "timelock block height incoming" : timelock_block_incoming
    	}
    as_swap_list.append(new_swap)
    return spend_bundle, puzzlehash_outgoing, tip


# finishes creating the swap initiator's swap
async def init_swap_finish(wallet, ledger_api, most_recent_header, as_contacts, as_swap_list, puzzlehash_outgoing, tip_index):
    for swap in as_swap_list:
        if hexlify(puzzlehash_outgoing).decode('ascii') == str(swap["outgoing puzzlehash"]):
            swap_index = as_swap_list.index(swap)
    puzzlehash_incoming = add_puzzlehash_init(wallet)
    if puzzlehash_incoming == "menu":
        return
    as_swap_list[swap_index]["incoming puzzlehash"] = puzzlehash_incoming
    print()
    print("Waiting for your incoming coin to appear on the blockchain . . .")
    check = False
    while not check:
        await get_update(wallet, ledger_api, most_recent_header, as_contacts, as_swap_list)
        tip = await ledger_api.get_tip()
        for coin in wallet.as_pending_utxos:
            if puzzlehash_incoming == hexlify(coin.puzzle_hash).decode('ascii'):
                check = True
    print()
    print("Update complete.")
    timelock_block_incoming = await sender_check(wallet, ledger_api, puzzlehash_incoming, as_swap_list[swap_index]["partner pubkey"], as_swap_list[swap_index]["my swap pubkey"], as_swap_list[swap_index]["amount"], as_swap_list[swap_index]["timelock time incoming"], as_swap_list[swap_index]["secret hash"], tip_index)
    as_swap_list[swap_index]["timelock block height incoming"] = timelock_block_incoming
    as_contacts[as_swap_list[swap_index]["swap partner"]][1][0].append(hexlify(puzzlehash_outgoing).decode('ascii'))
    as_contacts[as_swap_list[swap_index]["swap partner"]][1][1].append(puzzlehash_incoming)
    print()
    print("You are now participating in the following atomic swap:")
    print_swap_details(as_swap_list[swap_index])
    print(divider)


# adds hashlock secret to swap adder's swap parameters
def add_secret_hash(wallet):
    print()
    print("Enter the hash of the hashlock secret for this atomic swap:")
    secret_hash = input(prompt)
    complete = False
    while not complete:
        try:
            hexval = int(secret_hash, 16)
            if len(secret_hash) != 66:
                print()
                print("This is not a valid hashlock secret hash.")
                print()
                print("Please enter a valid hashlock secret hash, or type 'menu' to cancel the atomic swap:")
                secret_hash = input(prompt)
                if secret_hash == "menu":
                    return
            else:
                complete = True
        except:
            print()
            print("This is not a valid hashlock secret hash.")
            print()
            print("Please enter a valid hashlock secret hash, or type 'menu' to cancel the atomic swap:")
            secret_hash = input(prompt)
            if secret_hash == "menu":
                return
    return secret_hash


# allows swap adder to specify a buffer between the timeout times of the incoming and outgoing coins
def add_buffer(timelock):
    max_buffer = (timelock // 2) - 1
    print()
    print(f"Enter the minimum number of blocks you will accept as a buffer between the timeout times of your outgoing and incoming coins (buffer must be greater than 0 and less than or equal to {max_buffer}):")
    buffer = input(prompt)
    try:
        buffer = int(buffer)
    except ValueError:
        print()
        print("Invalid input: You entered an invalid buffer time.")
        return None
    if buffer <= 0:
        print()
        print("Invalid input: Buffer time must be greater than 0.")
        return None
    elif buffer > max_buffer:
        print()
        print(f"Invalid input: Buffer time may not be greater than {max_buffer}.")
    else:
        return buffer


# adds the swap adder's incoming coin's puzzlehash to their swap parameters
async def add_puzzlehash(wallet, ledger_api, partner_pubkey, my_swap_pubkey, amount, timelock, secret_hash, tip_index_at_start, buffer):
    print()
    print("Enter the incoming coin's puzzlehash:")
    puzzlehash = input(prompt)
    try:
        hexval = int(puzzlehash, 16)
        if len(puzzlehash) != 64:
            print()
            print("Invalid input: You did not enter a valid puzzlehash.")
            return None, None
    except:
        print()
        print("Invalid input: You did not enter a valid puzzlehash.")
        return None, None
    timelock_block_incoming = await receiver_check(wallet, ledger_api, puzzlehash, partner_pubkey, my_swap_pubkey, amount, timelock, secret_hash, tip_index_at_start, buffer)
    if timelock_block_incoming == None:
        return puzzlehash, None
    return puzzlehash, timelock_block_incoming


# checks that the swap adder's buffer time is ensured, given the incoming coin's timeout time and the current block height
async def receiver_check(wallet, ledger_api, puzzlehash, partner_pubkey, my_swap_pubkey, amount, timelock, secret_hash, tip_index_at_start, buffer):
    tip = await ledger_api.get_tip()
    for t in range(tip_index_at_start, tip["tip_index"] + 1):
        timelock_block_incoming = int(timelock + t)
        if puzzlehash_from_string(puzzlehash) == wallet.as_get_new_puzzlehash(bytes.fromhex(partner_pubkey), bytes.fromhex(my_swap_pubkey), amount, timelock_block_incoming, secret_hash):
            timelock_block_outgoing_check = int(tip["tip_index"] + (timelock * 0.5))
            if timelock_block_incoming < (timelock_block_outgoing_check + buffer):
                print()
                print(f"Current block height: {tip['tip_index']}")
                print(f"Incoming coin timelock block: {timelock_block_incoming}")
                print(f"Outgoing coin minimum timelock block: {timelock_block_outgoing_check}")
                print()
                print("Timelock error: There are too few blocks between the incoming coin's timelock block and the minimum possible timelock block of your outgoing coins. You may not proceed with this atomic swap, and your outgoing coin has been cancelled. Please coordinate with your partner to restart the atomic swap.")
                return None
            else:
                return timelock_block_incoming
    print()
    print("An error has occurred. Please coordinate with your partner to restart the atomic swap.")
    return None


# finds the timeout time of the swap initiator's incoming coin to add that info to their swap parameters
async def sender_check(wallet, ledger_api, puzzlehash, partner_pubkey, my_swap_pubkey, amount, timelock, secret_hash, tip_index_at_start):
    tip = await ledger_api.get_tip()
    for t in range(tip_index_at_start, tip["tip_index"] + 1):
        timelock_block_incoming = int(timelock + t)
        if puzzlehash_from_string(puzzlehash) == wallet.as_get_new_puzzlehash(bytes.fromhex(partner_pubkey), bytes.fromhex(my_swap_pubkey), amount, timelock_block_incoming, secret_hash):
            return timelock_block_incoming


# sets the swap adder's swap parameters
async def set_parameters_add(wallet, ledger_api, as_contacts, as_swap_list):
    complete_set_partner = False
    while not complete_set_partner:
        my_swap_pubkey, swap_partner, partner_pubkey, tip_index_at_start = await set_partner(wallet, ledger_api, as_contacts, "add")
        if my_swap_pubkey == None and swap_partner == None and partner_pubkey == None:
            return None, None, None, None, None, None, None, None, None, None, "menu"
        else:
            complete_set_partner = True
    complete_set_amount = False
    while not complete_set_amount:
        amount = set_amount(wallet, as_contacts)
        if amount == None:
            complete = False
            while not complete:
                print()
                print("Type 'amount' to enter a new amount, or type 'menu' to cancel the atomic swap:")
                choice = input(prompt)
                if choice == "menu":
                    return None, None, None, None, None, None, None, None, None, None, "menu"
                elif choice == "amount":
                    complete = True
                else:
                    print()
                    print("You entered an invalid selection.")
        else:
            complete_set_amount = True
    secret = "unknown"
    secret_hash = add_secret_hash(wallet)
    if secret_hash == None:
        return None, None, None, None, None, None, None, None, None, None, "menu"
    else:
        choice = "continue"
    complete_set_timelock = False
    while not complete_set_timelock:
        timelock = set_timelock(wallet, as_contacts, "add")
        if timelock == None:
            complete = False
            while not complete:
                print()
                print("Type 'time' to enter a new timelock time, or type 'menu' to cancel the atomic swap:")
                choice = input(prompt)
                if choice == "menu":
                    return None, None, None, None, None, None, None, None, None, None, "menu"
                elif choice == "time":
                    complete = True
                else:
                    print()
                    print("You entered an invalid selection.")
        else:
            complete_set_timelock = True
    complete_set_buffer = False
    while not complete_set_buffer:
        buffer = add_buffer(timelock)
        if buffer == None:
            complete = False
            while not complete:
                print()
                print("Type 'buffer' to enter a new timelock buffer, or type 'menu' to cancel the atomic swap:")
                choice = input(prompt)
                if choice == "menu":
                    return None, None, None, None, None, None, None, None, None, None, "menu"
                elif choice == "buffer":
                    complete = True
                else:
                    print()
                    print("You entered an invalid selection.")
        else:
            complete_set_buffer = True
    complete_set_puzzlehash = False
    while not complete_set_puzzlehash:
        puzzlehash, timelock_block_incoming = await add_puzzlehash(wallet, ledger_api, partner_pubkey, my_swap_pubkey, amount, timelock, secret_hash, tip_index_at_start, buffer)
        if puzzlehash == None:
            complete = False
            while not complete:
                print()
                print("Type 'puzzlehash' to enter a new puzzlehash, or type 'menu' to cancel the atomic swap:")
                choice = input(prompt)
                if choice == "menu":
                    return None, None, None, None, None, None, None, None, None, None, "menu"
                elif choice == "puzzlehash":
                    complete = True
                else:
                    print()
                    print("You entered an invalid selection.")
        elif timelock_block_incoming == None:
            return None, None, None, None, None, None, None, None, None, None, "menu"
        else:
            complete_set_puzzlehash = True
    return my_swap_pubkey, swap_partner, partner_pubkey, amount, secret, secret_hash, timelock, puzzlehash, timelock_block_incoming, buffer, None


# creates the swap adder's swap
# sets parameters
# creates swap adder's outgoing coin
async def add_swap(wallet, ledger_api, most_recent_header, as_contacts, as_swap_list):
    print()
    print(divider)
    print(f" {informative} Add Atomic Swap {informative}")
    my_swap_pubkey, swap_partner, partner_pubkey, amount, secret, secret_hash, timelock, puzzlehash_incoming, timelock_block_incoming, buffer, menu = await set_parameters_add(wallet, ledger_api, as_contacts, as_swap_list)
    if menu == "menu":
        print(divider)
        return
    puzzlehash_outgoing = "pending"
    timelock_outgoing = int(0.5 * timelock)
    timelock_block_outgoing = "pending"
    new_swap = {
            "swap partner" : swap_partner,
    		"partner pubkey" : partner_pubkey,
    		"amount" : amount,
    		"secret" : secret,
            "secret hash" : secret_hash,
            "my swap pubkey" : my_swap_pubkey,
            "outgoing puzzlehash" : puzzlehash_outgoing,
            "timelock time outgoing" : timelock_outgoing,
            "timelock block height outgoing" : timelock_block_outgoing,
            "incoming puzzlehash" : puzzlehash_incoming,
            "timelock time incoming" : timelock,
            "timelock block height incoming" : timelock_block_incoming
    	}
    as_swap_list.append(new_swap)
    check = False
    print()
    print("Waiting for your incoming coin to appear on the blockchain . . .")
    while not check:
        await get_update(wallet, ledger_api, most_recent_header, as_contacts, as_swap_list)
        tip = await ledger_api.get_tip()
        for coin in wallet.as_pending_utxos:
            if puzzlehash_incoming == hexlify(coin.puzzle_hash).decode('ascii'):
                check = True
    print()
    print("Update complete.")
    timelock_block_outgoing = int(timelock_outgoing + tip["tip_index"])
    if timelock_block_incoming < (timelock_block_outgoing + buffer):
        print()
        print(f"Current block height: {tip['tip_index']}")
        print(f"Incoming coin timelock block: {timelock_block_incoming}")
        print(f"Outgoing coin minimum timelock block: {timelock_block_outgoing}")
        print()
        print("Timelock error: There are too few blocks between the timelock blocks of your incoming and outgoing coins. You may not proceed with this atomic swap, and your outgoing coin has been cancelled. Please coordinate with your partner to restart the atomic swap.")
        return None
    puzzlehash_outgoing = wallet.as_get_new_puzzlehash(bytes.fromhex(my_swap_pubkey), bytes.fromhex(partner_pubkey), amount, timelock_block_outgoing, secret_hash)
    spend_bundle = wallet.generate_signed_transaction(amount, puzzlehash_outgoing)
    print()
    print("This is the puzzlehash of your outgoing coin:")
    print(hexlify(puzzlehash_outgoing).decode('ascii'))
    print()
    print("Please send your outgoing puzzlehash to your swap partner, and press 'return' to continue.")
    confirm = input(prompt)
    as_contacts[swap_partner][1][0].append(hexlify(puzzlehash_outgoing).decode('ascii'))
    as_contacts[swap_partner][1][1].append(puzzlehash_incoming)
    for swap in as_swap_list:
        if puzzlehash_incoming == str(swap["incoming puzzlehash"]):
            swap_index = as_swap_list.index(swap)
    as_swap_list[swap_index]["outgoing puzzlehash"] = hexlify(puzzlehash_outgoing).decode('ascii')
    as_swap_list[swap_index]["timelock block height outgoing"] = timelock_block_outgoing
    as_swap_list[swap_index]["timelock block height incoming"] = timelock_block_incoming
    print()
    print("You are now participating in the following atomic swap:")
    print_swap_details(as_swap_list[swap_index])
    print(divider)
    return spend_bundle


# finds the atomic swap coin to be spent
def find_coin(as_swap_list):
    complete_find_coin = False
    while not complete_find_coin:
        view_swaps(as_swap_list)
        print()
        print("Enter the puzzlehash for the atomic swap coin you wish to spend:")
        puzzlehash = input(prompt)
        for swap in as_swap_list:
            if puzzlehash == str(swap["outgoing puzzlehash"]):
                return as_swap_list.index(swap), "outgoing"
            elif puzzlehash == str(swap["incoming puzzlehash"]):
                return as_swap_list.index(swap), "incoming"
        print()
        print("The puzzlehash you entered is not in your list of available atomic swaps.")
        complete = False
        while not complete:
            print()
            print("Type 'puzzlehash' to enter a new puzzlehash, or 'menu' to return to menu:")
            choice = input(prompt)
            if choice == "menu":
                return None, None
            elif choice == "puzzlehash":
                complete = True
            else:
                print()
                print("You entered an invalid selection.")


# manually updates an atomic swap's secret
def update_secret(as_swap_list, swap_index):
    swap = as_swap_list[swap_index]
    complete = False
    while not complete:
        print()
        print("You do not have a secret on file for this atomic swap. Would you like to enter one now? (y/n)")
        response = input(prompt)
        if response == "y":
            complete = True
        elif response == "n":
            print()
            print("A secret is required to spend this atomic swap coin. Please try again when you know the secret.")
            return "menu"
        else:
            print()
            print("You entered an invalid selection.")
    complete_secret = False
    while not complete_secret:
        print()
        print("Enter the secret for this atomic swap:")
        new_secret = input(prompt)
        if new_secret == "":
            print()
            print("You did not enter a secret. A secret is required to spend this atomic swap coin.")
            complete = False
            while not complete:
                print()
                print("Would you like to enter a secret now? (y/n)")
                response = input(prompt)
                if response == "y":
                    complete = True
                elif response == "n":
                    print()
                    print("A secret is required to spend this atomic swap coin. Please try again when you know the secret.")
                    return "menu"
                else:
                    print()
                    print("You entered an invalid selection.")
        else:
            swap["secret"] = new_secret
            complete_secret = True
    return


# spends a pending atomic swap coin using the coin's secret (used for incoming coins)
def spend_with_secret(wallet, as_swap_list, swap_index):
    swap = as_swap_list[swap_index]
    if swap["secret"] == "unknown":
        menu = update_secret(as_swap_list, swap_index)
        if menu == "menu" or swap["secret"] == "unknown":
            return
    complete_spend_with_secret = False
    while not complete_spend_with_secret:
        print()
        print(f"The secret you have on file for this atomic swap is: {swap['secret']}")
        print()
        print("Would you like to use this secret to spend this atomic swap coin? (y/n)")
        response = input(prompt)
        if response == "y":
            complete_spend_with_secret = True
        elif response == "n":
            complete = False
            while not complete:
                print()
                print("Would you like to update the secret now? (y/n)")
                response = input(prompt)
                if response == "y":
                    update_secret(as_swap_list, swap_index)
                    complete = True
                elif response == "n":
                    print()
                    print("A secret is required to spend this atomic swap coin. Please try again when you know the secret.")
                    return
                else:
                    print()
                    print("You entered an invalid selection.")
        else:
            print()
            print("You entered an invalid selection.")
    secret_hash = wallet.as_generate_secret_hash(swap["secret"])
    spend_bundle = wallet.as_create_spend_bundle(swap["incoming puzzlehash"], swap["amount"], int(swap["timelock block height incoming"]), secret_hash, as_pubkey_sender = bytes.fromhex(swap["partner pubkey"]), as_pubkey_receiver = bytes.fromhex(swap["my swap pubkey"]), who = "receiver", as_sec_to_try = swap["secret"])
    return spend_bundle


# spends a pending atomic swap coin using the coin's timelock condition (used for outgoing coins)
def spend_with_timelock(wallet, as_swap_list, swap_index):
    swap = as_swap_list[swap_index]
    spend_bundle = wallet.as_create_spend_bundle(swap["outgoing puzzlehash"], swap["amount"], int(swap["timelock block height outgoing"]), swap["secret hash"], as_pubkey_sender = bytes.fromhex(swap["my swap pubkey"]), as_pubkey_receiver = bytes.fromhex(swap["partner pubkey"]), who = "sender", as_sec_to_try = swap["secret"])
    return spend_bundle


# removes atomic swap coins and info throughout the wallet after the swap's pending coins are spent
def remove_swap_instances(wallet, as_contacts, as_swap_list, removals):
    for coin in removals:
        pcoins = wallet.as_pending_utxos.copy()
        for pcoin in pcoins:
            if coin.puzzle_hash == pcoin.puzzle_hash:
                wallet.as_pending_utxos.remove(pcoin)
        for swap in as_swap_list:
            if hexlify(coin.puzzle_hash).decode('ascii') == swap["outgoing puzzlehash"]:
                as_contacts[swap["swap partner"]][1][0].remove(swap["outgoing puzzlehash"])
                swap["outgoing puzzlehash"] = "spent"
                if swap["outgoing puzzlehash"] == "spent" and swap["incoming puzzlehash"] == "spent":
                    as_swap_list.remove(swap)
            if hexlify(coin.puzzle_hash).decode('ascii') == swap["incoming puzzlehash"]:
                as_contacts[swap["swap partner"]][1][1].remove(swap["incoming puzzlehash"])
                swap["incoming puzzlehash"] = "spent"
                if swap["outgoing puzzlehash"] == "spent" and swap["incoming puzzlehash"] == "spent":
                    as_swap_list.remove(swap)


# redeems a pending atomic swap coin
def spend_coin(wallet, as_contacts, as_swap_list):
    print()
    print(divider)
    print(f" {informative} Redeem Atomic Swap Coin {informative}")
    swap_index, whichpuz = find_coin(as_swap_list)
    if swap_index == None and whichpuz == None:
        print(divider)
        return
    swap = as_swap_list[swap_index]
    if whichpuz == "incoming":
        spend_bundle = spend_with_secret(wallet, as_swap_list, swap_index)
    elif whichpuz == "outgoing":
        spend_bundle = spend_with_timelock(wallet, as_swap_list, swap_index)
    print(divider)
    return spend_bundle


# finds the secret used to spend a swap coin so that it can be used to spend the swap's other coin
def pull_preimage(wallet, as_swap_list, body, removals):
    for coin in removals:
        for swap in as_swap_list:
            if hexlify(coin.puzzle_hash).decode('ascii') == swap["outgoing puzzlehash"]:
                l = [(puzzle_hash, puzzle_solution_program) for (puzzle_hash, puzzle_solution_program) in wallet.as_solution_list(body.solution_program)]
                for x in l:
                    if hexlify(x[0]).decode('ascii') == hexlify(coin.puzzle_hash).decode('ascii'):
                        pre1 = binutils.disassemble(x[1])
                        preimage = pre1[(len(pre1) - 515):(len(pre1) - 3)]
                        swap["secret"] = preimage
                        #breakpoint()


async def get_update(wallet, ledger_api, most_recent_header, as_contacts, as_swap_list):
    if most_recent_header is None:
        r = await ledger_api.get_all_blocks()
    else:
        r = await ledger_api.get_recent_blocks(most_recent_header=most_recent_header)
    update_list = BodyList.from_bytes(r)
    for body in update_list:
        additions = list(additions_for_body(body))
        removals = removals_for_body(body)
        removals = [Coin.from_bytes(await ledger_api.hash_preimage(hash=x)) for x in removals]
        if as_swap_list != []:
            pull_preimage(wallet, as_swap_list, body, removals)
        remove_swap_instances(wallet, as_contacts, as_swap_list, removals)
        wallet.notify(additions, removals, as_swap_list)


async def update_ledger(wallet, ledger_api, most_recent_header, as_contacts, as_swap_list):
    print()
    print(divider)
    print(f" {informative} Get Update {informative}")
    await get_update(wallet, ledger_api, most_recent_header, as_contacts, as_swap_list)
    print()
    print("Update complete.")
    print(divider)


async def farm_block(wallet, ledger_api, as_contacts, as_swap_list):
    print()
    print(divider)
    print(f" {informative} Commit Block {informative}")
    print()
    print("You have received a block reward.")
    coinbase_puzzle_hash = wallet.get_new_puzzlehash()
    fees_puzzle_hash = wallet.get_new_puzzlehash()
    r = await ledger_api.next_block(coinbase_puzzle_hash=coinbase_puzzle_hash, fees_puzzle_hash=fees_puzzle_hash)
    body = r["body"]
    most_recent_header = r['header']
    additions = list(additions_for_body(body))
    removals = removals_for_body(body)
    removals = [Coin.from_bytes(await ledger_api.hash_preimage(hash=x)) for x in removals]
    remove_swap_instances(wallet, as_contacts, as_swap_list, removals)
    wallet.notify(additions, removals, as_swap_list)
    del wallet.overlook[:]
    print(divider)
    return most_recent_header


async def main_loop():
    ledger_api = await connect_to_ledger_sim("localhost", 9868)
    selection = ""
    wallet = ASWallet()
    as_contacts = {}
    as_swap_list = []
    most_recent_header = None
    print_leaf()
    print()
    print("Welcome to your Chia Atomic Swap Wallet.")
    print()
    print(f"Your pubkey is: {hexlify(wallet.get_next_public_key().serialize()).decode('ascii')}")

    while selection != "q":
        print()
        print(divider)
        print(f" {informative} Menu {informative}")
        print()
        tip = await ledger_api.get_tip()
        print(f"Block: {tip['tip_index']}")
        print()
        print("Select a function:")
        print(f"{selectable} 1 Wallet Details / Generate Puzzlehash ")
        print(f"{selectable} 2 View Funds")
        print(f"{selectable} 3 View Contacts")
        print(f"{selectable} 4 Add Contact")
        print(f"{selectable} 5 Edit Contact")
        print(f"{selectable} 6 View Current Atomic Swaps")
        print(f"{selectable} 7 Initiate Atomic Swap")
        print(f"{selectable} 8 Add Atomic Swap")
        print(f"{selectable} 9 Redeem Atomic Swap Coin")
        print(f"{selectable} 10 Get Update")
        print(f"{selectable} 11 *GOD MODE* Farm Block / Get Money")
        print(f"{selectable} q Quit")
        print(divider)
        print()

        selection = input(prompt)
        if selection == "1":
            print_my_details(wallet)
        if selection == "2":
            view_funds(wallet, as_swap_list)
        elif selection == "3":
            view_contacts_details(as_contacts)
        elif selection == "4":
            add_contact(wallet, as_contacts)
        elif selection == "5":
            edit_contact(wallet, as_contacts)
        elif selection == "6":
            view_current_atomic_swaps(as_swap_list)
        elif selection == "7":
            spend_bundle, puzzlehash_outgoing, tip = await init_swap_start(wallet, ledger_api, as_contacts, as_swap_list)
            if spend_bundle is not None:
                await ledger_api.push_tx(tx=spend_bundle)
                await farm_block(wallet, ledger_api, as_contacts, as_swap_list)
                await init_swap_finish(wallet, ledger_api, most_recent_header, as_contacts, as_swap_list, puzzlehash_outgoing, tip["tip_index"])
        elif selection == "8":
            spend_bundle = await add_swap(wallet, ledger_api, most_recent_header, as_contacts, as_swap_list)
            if spend_bundle is not None:
                await ledger_api.push_tx(tx=spend_bundle)
                await farm_block(wallet, ledger_api, as_contacts, as_swap_list)
        elif selection == "9":
            spend_bundle = spend_coin(wallet, as_contacts, as_swap_list)
            if spend_bundle is not None:
                await ledger_api.push_tx(tx=spend_bundle)
        elif selection == "10":
            await update_ledger(wallet, ledger_api, most_recent_header, as_contacts, as_swap_list)
        elif selection == "11":
            most_recent_header = await farm_block(wallet, ledger_api, as_contacts, as_swap_list)


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
