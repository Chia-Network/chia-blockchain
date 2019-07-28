from chiabip158 import PyBIP158
from array import *
from hashlib import sha256
import random

print("BIP 158 test")

hsharray=[]

for i in range (1000):
    hsh=bytearray(sha256(i.to_bytes(4, "big")).digest())
    hsharray.append(hsh)

pl = PyBIP158(hsharray)

while True:
  print("*** Match Test ***")
  matcharray=[]
  for j in range (10):
    rando=random.randint(0,6000);
    matchhash=bytearray(sha256(rando.to_bytes(4, "big")).digest())
    if pl.Match(matchhash):
        print(str(rando)+" OK")
    else:
        print(str(rando)+" not found")
    matcharray.append(matchhash)

  if pl.MatchAny(matcharray):
    print("OK")
  else:
    print("NONE FOUND")
    break;
