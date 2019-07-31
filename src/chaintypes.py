import dataclasses
import hashlib
import json


def sizedclass(factory, size):
    return dataclasses.field(
        default_factory = factory,
        metadata = {'size': size}
    )


def with_slots(cls):
    D = dict(cls.__dict__)
    D['__slots__'] = tuple(f.name for f in dataclasses.fields(cls))
    for f in dataclasses.fields(cls):
        D.pop(f.name, None)
    D.pop('__dict__', None)
    return type(cls)(cls.__name__, cls.__bases__, D)


class Transportable:
    @classmethod
    def import_compact(cls, compact: bytes):
        args = []
        i = 0
        for field in dataclasses.fields(cls):
            size = field.metadata['size']
            args.append(field.default_factory(compact[i : i + size]))
            i += size
        return cls(*args)

    def export_compact(self):
        ans = []
        for field in dataclasses.fields(self):
            ans.extend(getattr(self, field.name))
        return bytes(ans)

    def export_json(self):
        return json.dumps(asdict(self))

    def export_hash(self):
        return hashlib.sha256(self.export_compact()).digest()

    def __iter__(self):
        for field in dataclasses.fields(self):
            yield from getattr(self, field.name)


@with_slots
@dataclasses.dataclass
class Header(Transportable):
    timestamp: bytes = sizedclass(bytes, 8)
    prevhash: bytes = sizedclass(bytes, 32)
    filterhash: bytes = sizedclass(bytes, 32)
    poshash: bytes = sizedclass(bytes, 32)
    bodyhash: bytes = sizedclass(bytes, 32)
    extdata: bytes = sizedclass(bytes, 32)
    onetimesig: bytes = sizedclass(bytes, 32)


@with_slots
@dataclasses.dataclass
class Body(Transportable):
    coinbase_hash: bytes = sizedclass(bytes, 32)
    coinbase_amt: bytes = sizedclass(bytes, 8)
    coinbase_sig: bytes = sizedclass(bytes, 32)
    fees_hash: bytes = sizedclass(bytes, 32)
    fees_amt: bytes = sizedclass(bytes, 8)
    soln_gen: bytes = sizedclass(bytes, 32)
    cost: bytes = sizedclass(bytes, 8)
    aggsig: bytes = sizedclass(bytes, 32)


@with_slots
@dataclasses.dataclass
class ProofOfTimeOutput(Transportable):
    chall_hash: bytes = sizedclass(bytes, 32)
    num_iters: bytes = sizedclass(bytes, 8)
    final_power: bytes = sizedclass(bytes, 32)


@with_slots
@dataclasses.dataclass
class ProofOfTime(Transportable):
    output: ProofOfTimeOutput = sizedclass(bytes, 72)
    witness_type: bytes = sizedclass(bytes, 8)
    witness: bytes = sizedclass(bytes, 32)


@with_slots
@dataclasses.dataclass
class ProofOfSpace(Transportable):
    pool_pk: bytes = sizedclass(bytes, 32)
    plot_pk: bytes = sizedclass(bytes, 32)
    param_k: bytes = sizedclass(bytes, 8)
    proof: bytes = sizedclass(bytes, 512)


@with_slots
@dataclasses.dataclass
class Challenge(Transportable):
    pot_hash: bytes = sizedclass(bytes, 32)
    pos_hash: bytes = sizedclass(bytes, 32)
    height: bytes = sizedclass(bytes, 8)
    tot_weight: bytes = sizedclass(bytes, 8)


@with_slots
@dataclasses.dataclass
class Block(Transportable):
    header: Header = sizedclass(Header.import_compact, 200)
    body: Body = sizedclass(Body.import_compact, 184)
    proof_time: ProofOfTime = sizedclass(ProofOfTime.import_compact, 112)
    proof_space: ProofOfSpace = sizedclass(ProofOfSpace.import_compact, 584)
    challenge: Challenge = sizedclass(Challenge.import_compact, 80)
