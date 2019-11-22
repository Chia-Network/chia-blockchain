New Generation Entropy coders
=============================

This library proposes two high speed entropy coders :

__Huff0__, a [Huffman codec](https://en.wikipedia.org/wiki/Huffman_coding) designed for modern CPU, 
featuring OoO (Out of Order) operations on multiple ALU (Arithmetic Logic Unit),
achieving extremely fast compression and decompression speeds.

__FSE__ is a new kind of [Entropy encoder](http://en.wikipedia.org/wiki/Entropy_encoding),
based on [ANS theory, from Jarek Duda](http://arxiv.org/abs/1311.2540),
achieving precise compression accuracy (like [Arithmetic coding](http://en.wikipedia.org/wiki/Arithmetic_coding)) at much higher speeds.

|Branch      |Status   |
|------------|---------|
|master      | [![Build Status](https://travis-ci.org/Cyan4973/lz4.svg?branch=master)](https://travis-ci.org/Cyan4973/FiniteStateEntropy) |
|dev         | [![Build Status](https://travis-ci.org/Cyan4973/lz4.svg?branch=dev)](https://travis-ci.org/Cyan4973/FiniteStateEntropy) |


Benchmarks
-------------------------

Benchmarks are run on an Intel Core i7-5600U, with Linux Mint 64-bits.
Source code is compiled using GCC 4.8.4, 64-bits mode.
Test files are generated using the provided `probagen` program.
Benchmark breaks sample files into blocks of 32 KB.
`Huff0` and `FSE` are compared to `zlibh`, the huffman encoder within zlib, provided by Frederic Kayser.

| File    | Codec | Ratio  | Compression | Decompression |
| ------- | ----- |:------:| -----------:| -------------:|
| Proba80 |       |        |             |               |
|         | Huff0 |  6.38  |__600 MB/s__ |__1350 MB/s__  |
|         | FSE   |__8.84__|  325 MB/s   |   440 MB/s    |
|         | zlibh |  6.38  |  265 MB/s   |   300 MB/s    |
| Proba14 |       |        |             |               |
|         | Huff0 |  1.90  |  595 MB/s   |   860 MB/s    |
|         | FSE   |  1.91  |  330 MB/s   |   460 MB/s    |
|         | zlibh |  1.90  |  255 MB/s   |   250 MB/s    |
| Proba02 |       |        |             |               |
|         | Huff0 |  1.13  |  525 MB/s   |   555 MB/s    |
|         | FSE   |  1.13  |  325 MB/s   |   445 MB/s    |
|         | zlibh |  1.13  |  180 MB/s   |   210 MB/s    |

By design, Huffman can't break the "1 bit per symbol" limit, hence loses efficiency on squeezed distributions, such as `Proba80`.
FSE is free of such limit, and its compression efficiency remains close to Shannon limit in all circumstances.
However, this accuracy is not always necessary, and less compressible distributions show little difference with Huffman.
On its side, Huff0 delivers in the form of a massive speed advantage.

Branch Policy
-------------------------
External contributions are welcomed and encouraged.
The "master" branch is only meant to host stable releases.
The "dev" branch is the one where all contributions are merged. If you want to propose a patch, please commit into "dev" branch or dedicated feature branch. Direct commit to "master" are not permitted.

