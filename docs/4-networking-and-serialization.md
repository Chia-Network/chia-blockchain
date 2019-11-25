# Networking and Serialization

## Asynchronous

## CBOR serialization

CBOR is a serialization format (Concise Binary Object Representation, RFC 7049), which optimizes for
small code size and small message size.

## Streamable Format
Chia hashes objects using the simple streamable format.

The primitives are:
* Sized ints serialized in in big endian format, i.e uint64
* Sized bytes serialized in big endian format, i.e bytes32
* BLSPublic keys serialized in bls format
* BLSSignatures serialized in bls format

An item is one of:
* streamable
* primitive
* List[item]
* Optional[item]

A streamable is an ordered group of items.

1. An streamable with fields 1..n is serialized by appending the serialization of each field.
2. A List is serialized into a 4 byte size prefix (number of items) and the serialization of each item
3. An Optional is serialized into a 1 byte prefix of 0x00 or 0x01, and if it's one, it's followed by the serialization of the item

This format can be implemented very easily, and allows us to hash objects like headers and proofs of space,
without complex serialization logic.

Most objects in the Chia protocol are stored and trasmitted using the streamable format.

## Handshake

## Ping Pong

## Introducer