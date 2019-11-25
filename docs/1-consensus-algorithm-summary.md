# Part 1: Consensus Algorithm Summary

The Chia blockchain and consensus algorithm aims to provide a more environmentally,
decentralized, and secure alternative to proof of work and proof of stake, while
maintaing some of the key properties that make Nakamoto consensus desireable. The full
description of the algorithm can be seen in the [Chia Network greenpaper](https://www.chia.net/assets/ChiaGreenPaper.pdf).

The main idea is that mining nodes called **Farmers** (as opposed to Bitcoin's miners), use
their disk space to compete on finding blocks. Whereas in Bitcoin, owning 5% of the hashpower, or
CPU power allows you to win 5% of the blocks, in Chia having 5% of the allocated hard drive
*space* will allow you to win these blocks. Furthermore, coinbase rewards and fees in blocks
are given to the farmers (and/or pools).

This allocated hard drive space is stored in a series of files referred to as "plots".
Plots are lookup tables filled with
hashes and pointers, which allow farmers to efficiently look up and find proofs of space, cryptographic
proofs of storage of data. Farmers can create plots through the plotting process, which can take
days of intesive CPU and disk usage, but after that, they can farm with almost no cpu or electricity
usage. More information on proofs of space and the exact construction can be found [here](https://github.com/Chia-Network/proof-of-space).

Whenever a new block is propagated through the network, all farmers check their hard drives to
see if they have any very good proofs of space (analogous to someone checking their bingo card to
see if they've won), and propagate these proofs if they've found a lucky number. Farmers also propagate a block
with these proofs, and sign it with a private key that is associated with their plot.

In order to prevent grinding attacks, these proofs of space must be put through a proof of time as well.
Each block has one proof of space and one proof of time.
**Proofs of time**, or verifiable delay function proofs, are cryptographic proofs that a sequential
computation was performed on a given input, for a given number of iterations. These proofs of
time create time between blocks, and make generating an alternative blockchain very take time. The nodes
that create proofs of time are called **Timelords**, and they don't get any rewards for doing this. The
idea is that they help the network operate, and as long as there is one honest timelord that is close
enough to the fastest timelord, then the grinding resistance is preserved.

A block which does not yet have a proof of time on it, is called an **unfinished block**.

## Difficulty and Iterations

In Chia, there is also a difficulty parameter which is a constant factor that can increase or decrease
the number of iterations required for the proof of time, and therefore change expected block times.
The formula for the proof of space iterations required to finish a block is below:

```
Iterations required = 30 * ips + difficulty * -ln(0.H(qual_str)) / expected_plot_size(k)
```

* **ips** is the estimated iterations per second of the timelords in the network. This is calculated as
the total iterations in the previous epoch, divided by the total time elapsed in that epoch. Epochs are groups of
2048 blocks starting at block 0 (genesis). The ips is only used from block i+512 where i is the start of a
new epoch (similarly to difficulty).
Note that the 30 * ips factor is a constant 30 seconds that is always necessary.
This allows farmers some time to fetch all their qualities and proofs from disk.

* **difficulty**  is a number that is also changed every epoch, starting at block i+512 where i%2048 is 0.
The difficulty parameter allows us to increase or decrease the number of iterations, in order to get closer
to the target block time of 2.5 minutes. If blocks came much faster or much slower than expected in the
previous epoch, the difficulty is adjusted based on the formula in the greenpaper. Source code is in src/blockchain.py.
The difficulty is increased regardless of which component improved, the space or the time. If a large farmer
came into the network, blocks will come faster and thus increase the difficulty. Same thing if a faster
timelord joins the network.

* **-ln(x)** negative log is applied to a number between 0 and 1, to make proportion of space in the network
equal to the proportion of blocks won. This is computed using a simple Pade approximation for log, which is
very accurate for values close to 1.

* **0.H(x)** this is a conversion from a hash (32 byte sha256 output) to a value between 0 and 1, by taking
all the bits of the hash "xxxxx.." and representing a decimal in binary as 0.xxxxx... In the code, we
actually skip this step and use integers directly in the Pade approximation, to avoid floating points.

* **qual_str** is the quality string, is a variable sized bytestring that can be efficiently retrieved from
the plot (it's actually a subset of the proof of space). This allows farmers to efficiently check whether
a proof of space is "good" (requires low iterations), without fetching the whole proof from disk. A quality
lookup takes around 50ms on a slow HDD, while a proof of space lookup takes around 500ms. Note that this
is like finding a good hash in Bitcoin, but does not require elecricity, and can be done instantly.

* **k** is an integer between 30 and 59 which determines the size of a plot.

* **expected_plot_size** is a function from k to the number of bytes on disk to store a plot of that size.
Increasing k by one roughly doubles the size of the plot.


Whenever a farmer sees a new block in the network, she retrieves the quality and computes the iterations,
which when divided by ips, yields the expected time to finalize that block. If this number is close enough
to the expected block time (2.5 minutes), the entire proof of space is fetched from disk, the unfinished
block is creaed, and then it is propagated through the network.


As farmers in the network receive new blocks, and find their qualities and proofs of space, they
will propagate them and timelords will receive them. The proofs of space on block i will determine
the number of iterations that the proof of time on block i must have, but it is not included in
the challenge for block i. Therefore the timelord can start iterating on their VDF as soon as block
i-1 is finalized by another timelord. More information is given in the [greenpaper](https://github.com/Chia-Network/proof-of-space).


...

