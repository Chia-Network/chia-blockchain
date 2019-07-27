from chiabip158 import PyBIP158
from array import *

a = [1,2,3]
b = [4,5,6]
c = [a,b]
d = [7,8,9]

pl = PyBIP158(c)
if pl.Match(a):
    print("OK")
else:
    print("NOT FOUND")
