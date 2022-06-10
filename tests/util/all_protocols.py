# Do not use this file as a reference for good coding practices

before = set(globals().keys())
from chia.protocols import *  # noqa: F401,E402,F403

after = set(globals().keys())
new = after - before - {"before"}

all_protocols = [globals()[name] for name in sorted(new) if name.endswith("_protocol")]
