"""
This file implements the `qrint` encoding of binary data to a string of decimal digits.

QR codes support different encoding modes, and generation tools typically choose them
automatically. There is a binary QR code encoding, but it doesn't work well with hand-scanners
since they act like keyboards, and most bytes can't be typed. So we need to encode the
data in a keyboard-friends subset of ASCII.

According to Wikipedia, the candidates are

- Kanji/Kana
- alphanumeric (0-9, A-Z, space plus 8 punctuation marks)
- binary (all 8-bit values)
- numeric (digits 0-9)

With western bias, I reject Kanji encoding as too difficult to read for
outsiders (and it probably hasn't had as much opportunity to be
debugged with hand-scanners).

Alphanumeric has an alphabet of 45 characters, many of them breaking,
which is an awkward number.

With binary, we are limited to the characters that can be easily typed,
which limits us to about 96 out of 256, which also places us fairly
awkwardly between standard methods that provide ease of encoding (like
base64) and efficiency (base96?).

Numeric is implemented by grouping the string of digits into 3 digit
groups and representing each as a ten-bit number from 0-1023. The
values 1000-1023 are unused, so we get some built-in inefficiency
giving us a theoretical maximum efficiency of `math.log(1000, 1024)` ~=
99.66%. Which actually isn't too bad, especially compared to base64,
which is 6 bits/8 bits = 75% efficient. But how do we convert an
integer to binary?

An obvious way is to use `int.from_bytes` and `int.to_bytes`. However,
converting long strings of digits to the bignum type required to hold
them gets slower non-linearly as the string length increases. So
instead we group the digits into groups of N digits, and figure out how
many bits we can cram into that value. For N=3, we get 9 bits, which
means for every ten bits, we would waste one (on top of the 0.34%
wasted already by QR numeric encoding). But we can do better by increasing N.

For example, N=63 is quite nice: the integer 1<<63=9223372036854775808 fits
in 64 bits and has 19 digits. Three blocks therefore has 57 digits, which
is encoded in a QR code using 190 bits, 189 of which represent actual data.
This yields an asymptotic efficiency of 99.47%, pretty darn close to the
theoretical maximum. One downside of using a large N is that the resulting
string length must be large even if there are few bytes, and we must include
information about how much padding is included (since beach block of 19 digits
add 63 bits to the stream).

Here is a table of good N values with their efficiency:

N  |  1<< N  | digits | bne3b | bui3b |  % (max 99.66%)
---+---------+--------+-------+-------+-----
3  |   8     |   1    |   9   |  10   |  90%
13 |   8192  |   4    |  39   |  40   |  97.5%
23 | 8388608 |   7    |  69   |  70   |  98.57%
33 | 85...92 |  10    |  99   | 100   |  99%
43 | 87...08 |  13    | 129   | 130   |  99.23%
53 | 90...92 |  16    | 159   | 160   |  99.375%
63 | 92...08 |  19    | 189   | 190   |  99.474%

bne3b = bits needed to express 3 blocks (3 * N)
bui3b = bits used (by QR code) in 3 blocks (10 * len(1<<N))

So let's standardize on N=3 or N=33, and add a prefix that indicates
which N value we're using and how many bytes of padding remain.

prefix 1: N=3, no padding (since this is effectively just the string in octal)
prefix 2: N=33, no padding
prefix 3: N=33, 1 byte padding
prefix 4: N=33, 2 bytes padding
prefix 5: N=33, 3 bytes padding
prefix 6: N=33, 4 bytes padding

An additional benefit of qrint encoding is that long integers don't
include breaking characters, making them easy to select with a mouse.
"""

from typing import Tuple

from hsms.contrib.bech32m import convertbits


def b2a_qrint_payload(blob: bytes, grouping_size_bits: int) -> Tuple[int, str]:
    max_value = 1 << grouping_size_bits
    digit_block_size = len(str(max_value))
    block_count, extra_bits = divmod(len(blob) * 8, grouping_size_bits)

    if extra_bits > 0:
        block_count += 1

    bytes_in_block_count = block_count * grouping_size_bits // 8
    extra_bytes = bytes_in_block_count - len(blob)

    # now convert bytes into blocks of `grouping_size_bits` bits

    blocks = convertbits(blob, 8, grouping_size_bits, pad=True)
    format_template = "{:0%d}" % digit_block_size
    return extra_bytes, "".join(format_template.format(_) for _ in blocks)


def a2b_qrint_payload(s: str, grouping_size_bits: int) -> bytes:
    max_value = 1 << grouping_size_bits
    digit_block_size = len(str(max_value))

    len_s = len(s)
    blocks = [
        int(s[_ : _ + digit_block_size]) for _ in range(1, len_s, digit_block_size)
    ]
    return bytes(convertbits(blocks, grouping_size_bits, 8, pad=False))


def b2a_qrint(blob: bytes) -> str:
    MAX_SIZE_FOR_3_GROUP = 20

    padding_count, s33 = b2a_qrint_payload(blob, 33)

    if len(blob) < MAX_SIZE_FOR_3_GROUP:
        _, s3 = b2a_qrint_payload(blob, 3)
        if len(s3) < len(s33):
            return "1" + s3

    return "23456"[padding_count] + s33


PREFIX_TABLE = {
    "1": (3, 0),
    "2": (33, 0),
    "3": (33, 1),
    "4": (33, 2),
    "5": (33, 3),
    "6": (33, 4),
}


def a2b_qrint(s: str) -> bytes:
    c = s[0]
    if c not in PREFIX_TABLE:
        raise ValueError(f"illegal prefix {c}")
    grouping_size_bits, padding = PREFIX_TABLE[c]
    payload = a2b_qrint_payload(s, grouping_size_bits)
    if padding:
        payload = payload[:-padding]
    return payload
