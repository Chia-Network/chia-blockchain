# Part 2: Coins, Spends and Wallets

This guide directly continues on from [part 1](./part1_basics.md) so if you haven't read that, please do so before reading this.

This section of the guide will cover evaluating a program inside a program, how ChiaLisp relates to transactions and coins on the Chia network, and cover some techniques to create smart transactions using ChiaLisp.
If there are any terms that you aren't sure of, be sure to check the [glossary](./glossary.md).


## Coins

A coin's ID is constructed from 3 pieces of information.
1. The ID of its parent
2. The hash of its puzzle (AKA the puzzlehash)
3. The amount that it is worth

To construct a coin ID simply take the hash of these 3 pieces of information concatenated in order.

```
coinID == sha256(parent_ID + puzzlehash + amount)
```

This means that a coin's puzzle and amount are intrinsic parts of it.
You cannot change a coin's puzzle or amount, you can only spend a coin.

The body of a coin is also made up of these 3 pieces of information, but instead of being hashed, they are stored in full.
Here is the actual code that defines a coin:

```python
class Coin:
    parent_coin_info: "CoinName"
    puzzle_hash: ProgramHash
    amount: uint64
```

## Spends

When you spend a coin you destroy it.
Unless the behaviour of a puzzle designates what to do with the coin's value when it is spent, the value of the coin is also destroyed in the spend.

To spend a coin you need 3 pieces of information (and an optional 4th).
1. The coin's ID
2. The full source of the coin's puzzle
3. A solution to the coin's puzzle
4. (OPTIONAL) A collection of signatures grouped together, called an aggregated signature

Remember the puzzle and solution is the same as we covered in part 1, except the puzzle has already been stored inside the coin and anybody can submit a solution.

The network / ledger-sim has no concept of coin ownership, anybody can attempt to spend any coin on the network.
It's up to the puzzles to prevent coins from being stolen or spent in unintended ways.

If anybody can submit a solution for a coin, you maybe wondering how somebody can "own" a coin.
By the end of the next section of the guide, hopefully it should be clear.


## Puzzles and Solutions in Practice

So far in [part 1](./part1_basics.md) we have covered ChiaLisp programs that will evaluate to some result.
Remember the first part represents a puzzle which is committed to locking up a coin, and the second part is a solution anybody can submit:

```
$ brun '(+ (f (a)) (f (r (a))))' '(40 50)'
90

$ brun '(c (q 800) (a))' '("some data" 0xdeadbeef)'
(800 "some data" 0xdeadbeef)
```

These are fun exercises in isolation, but this format can be used to communicate instructions to the blockchain network of how a coin should behave when it is spent.
This can be done by having the result of an evaluation be a list of **OpCodes**.

### OpCodes

The OpCodes are split into two categories: *"this spend is only valid if X"* and *"if this spend is valid then X"*.

Here is the complete list of OpCodes along with their format and behaviour.

* **AGG_SIG - [50] - (50 0xpubkey 0xdatahash)**: This spend is only valid if the aggregated signature in this block contains a signature from the given public key of the given value hash.
* **CREATE_COIN - [51] - (51 0xpuzzlehash amount)**: If this spend is valid then create a new coin with the given puzzlehash and amount.
* **ASSERT_COIN_CONSUMED - [52] - (52 0xcoinID)**: This spend is only valid if the given Coin ID has also been spent in this block. This allows you to use the consumed coins value as part of your own output.
* **ASSERT_MY_COIN_ID - [53] - (53 0xcoinID)**: This spend is only valid if the presented coin ID is exactly the same as the ID of the coin that contains this puzzle.
* **ASSERT_MIN_TIME - [54] - (54 time)**: This spend is only valid if the given time has passed.
* **ASSERT_BLOCK_INDEX_EXCEEDS - [55] - (55 block_index)**: The spend is only valid if the given block_index has been reached.
* **ASSERT_BLOCK_AGE_EXCEEDS - [56] - (56 block_age)**: The spend is only valid if the given block_age has surpassed the age of the coin being spent.

These are returned as a list of lists in the form:
```
((51 0xabcd1234 200) (50 0x1234abcd) (53 0xdeadbeef))
```
Remember: this is what a puzzle should evaluate to when presented with a solution so that a full-node/ledger-sim can understand it.

Let's create a few examples puzzles and solutions to demonstrate how this is used in practice.


### Example 1: Password Locked Coin

Let's create a coin that can be spent by anybody as long as they know the password.

To implement this we would have the hash of the password committed into the puzzle and, if presented with the correct password, the puzzle will return instructions to create a new coin with a puzzlehash given in the solution.
For the following example the password is "hello" which has the hash value 0x2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824.
The implementation for the above coin would be thus:

```
(i (= (sha256 (f (a))) (q 0x2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824)) (c (q 51) (c (f (r (a))) (c (q 100) (q ())))) (q "wrong password"))
```

This program takes `(sha256 (f (a)))` the hash of the first element in the solution and compares that value with the already committed.
If the password is correct it will return `(c (q 51) (c (f (r (a))) (c (q 100) (q ())))` which evaluates to `(51 0xmynewpuzzlehash 100)`.
Remember, `51` is the OpCode to create a new coin using the puzzlehash presented in the solution.

If the password is incorrect it will return the string "wrong password".

The format for a solution to this is expected to be formatted as `(password newpuzzlehash)`.
Remember, anybody can attempt to spend this coin as long as they know its ID and the puzzle code.

Let's test it out using clvm_tools.
```
$ brun '(i (= (sha256 (f (a))) (q 0x2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824)) (c (q 51) (c (f (r (a))) (c (q 100) (q ())))) (q "wrong password"))' '("let_me_in" 0xdeadbeef)'
"wrong password"

$ brun '(i (= (sha256 (f (a))) (q 0x2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824)) (c (q 51) (c (f (r (a))) (c (q 100) (q ())))) (q "wrong password"))' '("incorrect" 0xdeadbeef)'
"wrong password"

$ brun '(i (= (sha256 (f (a))) (q 0x2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824)) (c (q 51) (c (f (r (a))) (c (q 100) (q ())))) (q "wrong password"))' '("hello" 0xdeadbeef)'
(51 0xdeadbeef 100)
```

There is one final change we need to make before this is a complete smart transaction.

If you want to invalidate a spend then you need to raise an exception using `x`.
Otherwise you just have a valid spend that isn't returning any OpCodes, and that would destroy our coin and be bad!
So we need to change the fail condition to be `(x (q "wrong password"))`.

If we're doing this then we should also change the `(i A B C)` pattern to `((c (i A (q B) (q C)) (a)))`.
The reason for this is explained in [part 3](./part3_deeperintoCLVM.md). For now don't worry about why.

Here is our completed password protected coin:
```
((c (i (= (sha256 (f (a))) (q 0x2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824)) (q (c (q 51) (c (f (r (a))) (c (q 100) (q ()))))) (q (x (q "wrong password")))) (a)))
```

Let's test it out using clvm_tools:

```
$ brun '((c (i (= (sha256 (f (a))) (q 0x2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824)) (q (c (q 51) (c (f (r (a))) (c (q 100) (q ()))))) (q (x (q "wrong password")))) (a)))' '("let_me_in" 0xdeadbeef)'
FAIL: clvm raise ("wrong password")

$ brun '((c (i (= (sha256 (f (a))) (q 0x2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824)) (q (c (q 51) (c (f (r (a))) (c (q 100) (q ()))))) (q (x (q "wrong password")))) (a)))' '("hello" 0xdeadbeef)'
(51 0xdeadbeef 100)
```

### Generating OpCodes from the Puzzle vs. from the Solution

Let's take a moment to consider the balance of power between the send and the spender.
Another way of phrasing this is "how much control over the output should the solution have?"

Suppose we lock a coin up using the following puzzle:

```
(q ((51 0x365bdd80582fcc2e4868076ab9f24b482a1f83f6d88fd795c362c43544380e7a 100)))
```
Regardless of what solution is passed this puzzle will *always* return instructions to create a new coin with the puzzlehash 0x365bdd80582fcc2e4868076ab9f24b482a1f83f6d88fd795c362c43544380e7a and the amount 100.

```
$ brun '(q ((51 0x365bdd80582fcc2e4868076ab9f24b482a1f83f6d88fd795c362c43544380e7a 100)))' '(80 90 "hello")'
((51 0x365bdd80582fcc2e4868076ab9f24b482a1f83f6d88fd795c362c43544380e7a 100))

$ brun '(q ((51 0x365bdd80582fcc2e4868076ab9f24b482a1f83f6d88fd795c362c43544380e7a 100)))' '("it doesn't matter what we put here")'
((51 0x365bdd80582fcc2e4868076ab9f24b482a1f83f6d88fd795c362c43544380e7a 100))
```

In this example the result of spending the coin is entirely determined from the puzzle.
Even though anybody could initiate the spend of the coin, the person that locked the coin up has all the power in the way that the coin is spent as the solution doesn't matter at all.

Conversely lets consider a coin locked up with the following puzzle:
```
(a)
```
In this example the person that locked the coin up as delegated all of the control to the solution.
The result of the spend is entirely dependent on the solution.
```
$ brun '(a)' '((51 0xf00dbabe 50) (51 0xfadeddab 50))'
((51 0xf00dbabe 50) (51 0xfadeddab 50))

$ brun '(a)' '((51 0xf00dbabe 75) (51 0xfadeddab 15) (51 0x1234abcd 10))'
((51 0xf00dbabe 75) (51 0xfadeddab 15) (51 0x1234abcd 10))
```
In this situation, not only can anybody can spend the coin, they can spend it however they like!

This balance of power determines a lot of how puzzles are designed in ChiaLisp.
This exercise is intended to demonstrate the point that OpCodes can come from both the recipient's solution and from the sender's puzzle, and how that represents trust and the balance of power.

In the next exercise we will put everything we know together and create the "standard" transaction in Chia that underpins how wallets are able to send money to each other.


### Example: Signature Locked Coin

To 'send a coin to somebody' you simply create a puzzle that requires the recipients signature, but then allows them to return any other OpCodes that they like.
This means that the coin cannot be spent by anybody else, but the outputs are entirely decided by the recipient.

We can construct the following smart transaction where AGGSIG is 50 and the recipient's pubkey is 0xpubkey.
```
(c (c (q 50) (c (q 0xpubkey) (c (sha256tree (a)) (q ())))) (a))
```

The `sha256tree` operator simply takes a program as a parameter and then creates a hash of that program (compared to `sha256` which would take a hash of the result of the program).

This puzzle forces the resultant evaluation to contain `(50 0xpubkey *hash_of_solution*)` but then adds on all of the conditions presented in the solution.

Let's test it out in clvm_tools - for this example the recipient's pubkey will be represented as 0xdeadbeef.
The recipient wants to spend the coin to create a new coin which is locked up with the puzzle 0xfadeddab.
```
$ brun '(c (c (q 50) (c (q 0xdeadbeef) (c (sha256tree (a)) (q ())))) (a))' '((51 0xfadeddab 100))'
((50 0xdeadbeef 0x34b88c869130fc1d50aafd392d8fa6797de4370b1969e5216bb076850ed3beae) (51 0xfadeddab 100))
```

Brilliant.

Let's pull back and add some context here.

## Wallets

A wallet is some software that has several features that make it easy for a user to interact with coins.

* A wallet keeps track of public and private keys
* A wallet can generate puzzles and solutions
* A wallet can sign things with its keys
* A wallet can identify and remember what coins that the user 'owns'
* A wallet can spend coins

You may be wondering how a wallet is able to identify what coins that the user 'owns' if any person can attempt to spend a coin.
This is because all wallets already know and agree on what the standard format for sending a coin to somebody is.
They know what their own pubkeys are, so when a new coin is created a wallet can check if the puzzle inside that coin is a 'standard send puzzle' to one of their pubkeys.
If it is, then that coin can be considered to be owned by that 'wallet' as nobody else can spend it.

If the wallet that 'owns' the coin then wanted to send that coin on again to somebody else, they would generate a 'standard send puzzle' but with the new recipient's pubkey.
They could then spend the coin that they own, destroying it, and creating a new coin that is locked up with the new recipients pubkey in the process.
The new recipient can then identify that it 'owns' the coin and can send it on as they wish later.

### Change Making

Change making is simple.
If a wallet spends less than the total value of a coin, they can create another coin with the remaining portion of value, and lock it up with the standard puzzle for themselves again.
You can split a coin up into as many new coins with fractions of the original value as you'd like.

You cannot create two coins of the same value, with the same puzzlehash, from the same parent as this will lead to an ID collision and the spend will be rejected.


### Coin Aggregation and Spend Bundles

You can aggregate a bunch of smaller coins together into one large coin.
To do this, you can create a SpendBundle which groups together one or more spends so that they cannot be split.
The SpendBundle also contains an Aggregated Signature object which is how the AGGSIG condition can check if a value has been signed.

You can also further tighten the link between them by using ASSERT_COIN_CONSUMED.
Suppose you have a 20 coin and an 80 coin.
In the 20 coin you can make it return `(CREATE_COIN 0xnewpuzhash 100)` in the spend.
Then in the 80 coin you can make it return `(ASSERT_COIN_CONSUMED 0x20coinID)`.
The coupling inside the SpendBundle and the 80 value asserting its relationship to the 20 means that the value from the 80 coin is channeled into the creation of the new value 100 coin.

### Standard Transaction

We can construct an even more powerful version of the signature locked coin to use as our standard transaction.

```
(c (c (q 50) (c (q 0xpubkey) (c (sha256tree (f (a))) (q ())))) ((c (f (a)) (f (r (a))))))
```

The first part is mostly the same, the puzzle always returns an AGGSIG check for the recipients public key.
However it only checks for the first element of the solution.
This is because instead of the solution for this puzzle being a list of OpConditions to be printed out, the solution is a program/solution pair.
This means that the recipient can run their own program as part of the solution generation, or sign a puzzle and let somebody else provide the solution.

The new program and solution inside the solution are evaluated and the result of that is added to the OpCode output.
We will cover in more detail how this works in the [next part](part3_deeperintoCLVM.md) of this guide.

A basic solution for this standard transaction might look like:

```
((q ((0x51 0xmynewpuzzlehash 50) (0x51 0xanothernewpuzzlehash 50))) (q ()))
```

Running that in the clvm_tools looks like this:

```
$ brun '(c (c (q 50) (c (q 0xfadeddab) (c (sha256tree (f (a))) (q ())))) ((c (f (a)) (f (r (a))))))' '((q ((0x51 0xdeadbeef 50) (0x51 0xf00dbabe 50))) (q ()))'

((50 0xfadeddab 0x1f82d4d4c6a32459143cf8f8d27ca04be337a59f07238f1f2c31aaf0cd51d153) (81 0xdeadbeef 50) (81 0xf00dbabe 50))
```

## Conclusions

Coin ownership refers to the concept of creating a coin with a puzzle that means it can only be spent when signed by the private key of the coin's "owner".
The goal of wallet software is to generate, interpret and manage these kinds of coins and puzzles.

The next part of this guide will go further in depth in ChiaLisp, and cover how to write more complex puzzles.
If any of the material in this part of the guide has got you confused, try returning to it after the next part.

[Part 3: Deeper into CLVM](./part3_deeperintoCLVM.md)
