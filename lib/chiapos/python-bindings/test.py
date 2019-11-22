from chiapos import DiskProver, DiskPlotter, Verifier
from hashlib import sha256
import secrets
import os

challenge: bytes = bytes([i for i in range(0, 32)])

plot_id: bytes = bytes([5, 104, 52, 4, 51, 55, 23, 84, 91, 10, 111, 12, 13,
                        222, 151, 16, 228, 211, 254, 45, 92, 198, 204, 10, 9,
                        10, 11, 129, 139, 171, 15, 23])
filename = "./myplot.dat"
pl = DiskPlotter()
pl.create_plot_disk(filename, 21, bytes([1, 2, 3, 4, 5]), plot_id)
pr = DiskProver(filename)


total_proofs: int = 0
iterations: int = 5000

v = Verifier()
for i in range(iterations):
    challenge = sha256(i.to_bytes(4, "big")).digest()
    for index, quality in enumerate(pr.get_qualities_for_challenge(challenge)):
        proof = pr.get_full_proof(challenge, index)
        total_proofs += 1
        ver_quality = v.validate_proof(plot_id, 21, challenge, proof)
        assert(quality == ver_quality)

os.remove(filename)

print(f"total proofs {total_proofs} out of {iterations}\
      {total_proofs / iterations}")
