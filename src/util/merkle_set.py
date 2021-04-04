from abc import ABCMeta, abstractmethod
from hashlib import sha256
from typing import Any, Dict, List, Tuple

from chia.types.blockchain_format.sized_bytes import bytes32

"""
A simple, confidence-inspiring Merkle Set standard

Advantages of this standard:
Low CPU requirements
Small proofs of inclusion/exclusion
Reasonably simple implementation

The main tricks in this standard are:

Skips repeated hashing of exactly two things even when they share prefix bits


Proofs support proving including/exclusion for a large number of values in
a single string. They're a serialization of a subset of the tree.

Proof format:

multiproof: subtree
subtree: middle or terminal or truncated or empty
middle: MIDDLE 1 subtree subtree
terminal: TERMINAL 1 hash 32
# If the sibling is empty truncated implies more than two children.
truncated: TRUNCATED 1 hash 32
empty: EMPTY 1
EMPTY: \x00
TERMINAL: \x01
MIDDLE: \x02
TRUNCATED: \x03
"""

EMPTY = bytes([0])
TERMINAL = bytes([1])
MIDDLE = bytes([2])
TRUNCATED = bytes([3])

BLANK = bytes([0] * 32)

prehashed: Dict = {}


def init_prehashed():
    for x in [EMPTY, TERMINAL, MIDDLE]:
        for y in [EMPTY, TERMINAL, MIDDLE]:
            prehashed[x + y] = sha256(bytes([0] * 30) + x + y)


init_prehashed()


def hashdown(mystr: bytes):
    assert len(mystr) == 66
    h = prehashed[bytes(mystr[0:1] + mystr[33:34])].copy()
    h.update(mystr[1:33] + mystr[34:])
    return h.digest()[:32]


def compress_root(mystr: bytes):
    assert len(mystr) == 33
    if mystr[0:1] == MIDDLE:
        return mystr[1:]
    if mystr[0:1] == EMPTY:
        assert mystr[1:] == BLANK
        return BLANK
    return sha256(mystr).digest()[:32]


def get_bit(mybytes: bytes, pos: int):
    assert len(mybytes) == 32
    return (mybytes[pos // 8] >> (7 - (pos % 8))) & 1


class Node(metaclass=ABCMeta):
    hash: bytes

    @abstractmethod
    def get_hash(self) -> bytes:
        pass

    @abstractmethod
    def is_empty(self) -> bool:
        pass

    @abstractmethod
    def is_terminal(self) -> bool:
        pass

    @abstractmethod
    def is_double(self) -> bool:
        pass

    @abstractmethod
    def add(self, toadd: bytes, depth: int) -> "Node":
        pass

    @abstractmethod
    def remove(self, toremove: bytes, depth: int):
        pass

    @abstractmethod
    def is_included(self, tocheck: bytes, depth: int, p: List[bytes]):
        pass

    @abstractmethod
    def other_included(self, tocheck: bytes, depth: int, p: List[bytes], collapse: bool):
        pass

    @abstractmethod
    def _audit(self, hashes: List[bytes], bits: List[int]):
        pass


class MerkleSet:
    root: Node

    def __init__(self, root: Node = None):
        if root is None:
            self.root = _empty
        else:
            self.root = root

    def get_root(self) -> Node:
        return compress_root(self.root.get_hash())

    def add_already_hashed(self, toadd: bytes):
        self.root = self.root.add(toadd, 0)

    def remove_already_hashed(self, toremove: bytes):
        self.root = self.root.remove(toremove, 0)

    def is_included_already_hashed(self, tocheck: bytes) -> Tuple[bool, bytes]:
        proof: List = []
        r = self.root.is_included(tocheck, 0, proof)
        return r, b"".join(proof)

    def _audit(self, hashes: List[bytes]):
        newhashes: List = []
        self.root._audit(newhashes, [])
        assert newhashes == sorted(newhashes)


class EmptyNode(Node):
    def __init__(self):
        self.hash = BLANK

    def get_hash(self) -> bytes:
        return EMPTY + BLANK

    def is_empty(self) -> bool:
        return True

    def is_terminal(self) -> bool:
        return False

    def is_double(self) -> bool:
        raise SetError()

    def add(self, toadd: bytes, depth: int) -> Node:
        return TerminalNode(toadd)

    def remove(self, toremove: bytes, depth: int) -> Node:
        return self

    def is_included(self, tocheck: bytes, depth: int, p: List[bytes]) -> bool:
        p.append(EMPTY)
        return False

    def other_included(self, tocheck: bytes, depth: int, p: List[bytes], collapse: bool):
        p.append(EMPTY)

    def _audit(self, hashes: List[bytes], bits: List[int]):
        pass


_empty = EmptyNode()


class TerminalNode(Node):
    def __init__(self, hash: bytes, bits: List[int] = None):
        assert len(hash) == 32
        self.hash = hash
        if bits is not None:
            self._audit([], bits)

    def get_hash(self) -> bytes:
        return TERMINAL + self.hash

    def is_empty(self) -> bool:
        return False

    def is_terminal(self) -> bool:
        return True

    def is_double(self) -> bool:
        raise SetError()

    def add(self, toadd: bytes, depth: int) -> Node:
        if toadd == self.hash:
            return self
        if toadd > self.hash:
            return self._make_middle([self, TerminalNode(toadd)], depth)
        else:
            return self._make_middle([TerminalNode(toadd), self], depth)

    def _make_middle(self, children: Any, depth: int) -> Node:
        cbits = [get_bit(child.hash, depth) for child in children]
        if cbits[0] != cbits[1]:
            return MiddleNode(children)
        nextvals: List[Node] = [_empty, _empty]
        nextvals[cbits[0] ^ 1] = _empty  # type: ignore
        nextvals[cbits[0]] = self._make_middle(children, depth + 1)
        return MiddleNode(nextvals)

    def remove(self, toremove: bytes, depth: int) -> Node:
        if toremove == self.hash:
            return _empty
        return self

    def is_included(self, tocheck: bytes, depth: int, p: List[bytes]) -> bool:
        p.append(TERMINAL + self.hash)
        return tocheck == self.hash

    def other_included(self, tocheck: bytes, depth: int, p: List[bytes], collapse: bool):
        p.append(TERMINAL + self.hash)

    def _audit(self, hashes: List[bytes], bits: List[int]):
        hashes.append(self.hash)
        for pos, v in enumerate(bits):
            assert get_bit(self.hash, pos) == v


class MiddleNode(Node):
    def __init__(self, children: List[Node]):
        self.children = children
        if children[0].is_empty() and children[1].is_double():
            self.hash = children[1].hash
        elif children[1].is_empty() and children[0].is_double():
            self.hash = children[0].hash
        else:
            if children[0].is_empty() and (children[1].is_empty() or children[1].is_terminal()):
                raise SetError()
            if children[1].is_empty() and children[0].is_terminal():
                raise SetError
            if children[0].is_terminal() and children[1].is_terminal() and children[0].hash >= children[1].hash:
                raise SetError
            self.hash = hashdown(children[0].get_hash() + children[1].get_hash())

    def get_hash(self) -> bytes:
        return MIDDLE + self.hash

    def is_empty(self) -> bool:
        return False

    def is_terminal(self) -> bool:
        return False

    def is_double(self) -> bool:
        if self.children[0].is_empty():
            return self.children[1].is_double()
        if self.children[1].is_empty():
            return self.children[0].is_double()
        return self.children[0].is_terminal() and self.children[1].is_terminal()

    def add(self, toadd: bytes, depth: int) -> Node:
        bit = get_bit(toadd, depth)
        child = self.children[bit]
        newchild = child.add(toadd, depth + 1)
        if newchild is child:
            return self
        newvals = [x for x in self.children]
        newvals[bit] = newchild
        return MiddleNode(newvals)

    def remove(self, toremove: bytes, depth: int) -> Node:
        bit = get_bit(toremove, depth)
        child = self.children[bit]
        newchild = child.remove(toremove, depth + 1)
        if newchild is child:
            return self
        otherchild = self.children[bit ^ 1]
        if newchild.is_empty() and otherchild.is_terminal():
            return otherchild
        if newchild.is_terminal() and otherchild.is_empty():
            return newchild
        newvals = [x for x in self.children]
        newvals[bit] = newchild
        return MiddleNode(newvals)

    def is_included(self, tocheck: bytes, depth: int, p: List[bytes]) -> bool:
        p.append(MIDDLE)
        if get_bit(tocheck, depth) == 0:
            r = self.children[0].is_included(tocheck, depth + 1, p)
            self.children[1].other_included(tocheck, depth + 1, p, not self.children[0].is_empty())
            return r
        else:
            self.children[0].other_included(tocheck, depth + 1, p, not self.children[1].is_empty())
            return self.children[1].is_included(tocheck, depth + 1, p)

    def other_included(self, tocheck: bytes, depth: int, p: List[bytes], collapse: bool):
        if collapse or not self.is_double():
            p.append(TRUNCATED + self.hash)
        else:
            self.is_included(tocheck, depth, p)

    def _audit(self, hashes: List[bytes], bits: List[int]):
        self.children[0]._audit(hashes, bits + [0])
        self.children[1]._audit(hashes, bits + [1])


class TruncatedNode(Node):
    def __init__(self, hash: bytes):
        self.hash = hash

    def get_hash(self) -> bytes:
        return MIDDLE + self.hash

    def is_empty(self) -> bool:
        return False

    def is_terminal(self) -> bool:
        return False

    def is_double(self) -> bool:
        return False

    def add(self, toadd: bytes, depth: int) -> Node:
        return self

    def remove(self, toremove: bytes, depth: int) -> Node:
        return self

    def is_included(self, tocheck: bytes, depth: int, p: List[bytes]) -> bool:
        raise SetError()

    def other_included(self, tocheck: bytes, depth: int, p: List[bytes], collapse: bool):
        p.append(TRUNCATED + self.hash)

    def _audit(self, hashes: List[bytes], bits: List[int]):
        pass


class SetError(Exception):
    pass


def confirm_included(root: Node, val: bytes, proof: bytes32) -> bool:
    return confirm_not_included_already_hashed(root, sha256(val).digest(), proof)


def confirm_included_already_hashed(root: Node, val: bytes, proof: bytes32) -> bool:
    return _confirm(root, val, proof, True)


def confirm_not_included(root: Node, val: bytes, proof: bytes32) -> bool:
    return confirm_not_included_already_hashed(root, sha256(val).digest(), proof)


def confirm_not_included_already_hashed(root: Node, val: bytes, proof: bytes32) -> bool:
    return _confirm(root, val, proof, False)


def _confirm(root: Node, val: bytes, proof: bytes32, expected: bool) -> bool:
    try:
        p = deserialize_proof(proof)
        if p.get_root() != root:
            return False
        r, junk = p.is_included_already_hashed(val)
        return r == expected
    except SetError:
        return False


def deserialize_proof(proof: bytes32) -> MerkleSet:
    try:
        r, pos = _deserialize(proof, 0, [])
        if pos != len(proof):
            raise SetError()
        return MerkleSet(r)
    except IndexError:
        raise SetError()


def _deserialize(proof: bytes32, pos: int, bits: List[int]) -> Tuple[Node, int]:
    t = proof[pos : pos + 1]  # flake8: noqa
    if t == EMPTY:
        return _empty, pos + 1
    if t == TERMINAL:
        return TerminalNode(proof[pos + 1 : pos + 33], bits), pos + 33  # flake8: noqa
    if t == TRUNCATED:
        return TruncatedNode(proof[pos + 1 : pos + 33]), pos + 33  # flake8: noqa
    if t != MIDDLE:
        raise SetError()
    v0, pos = _deserialize(proof, pos + 1, bits + [0])
    v1, pos = _deserialize(proof, pos, bits + [1])
    return MiddleNode([v0, v1]), pos
