from fastvdf import prove, verify_wesolowski, create_discriminant
import secrets
import time

for _ in range(10):
    discriminant_challenge = secrets.token_bytes(10)
    discriminant_size = 512
    discriminant = create_discriminant(discriminant_challenge, discriminant_size)
    int_size = (discriminant_size + 16) >> 4

    iters = 2000000
    t1 = time.time()
    result = prove(discriminant_challenge, discriminant_size, iters)
    t2 = time.time()
    print(f"IPS: {iters / (t2 - t1)}")

    is_valid = verify_wesolowski(
        str(discriminant),
        str(2),
        str(1),
        str(
            int.from_bytes(
                result[0:int_size],
                "big",
                signed=True,
            )
        ),
        str(
            int.from_bytes(
                result[int_size:2*int_size],
                "big",
                signed=True,
            )
        ),
        str(
            int.from_bytes(
                result[2*int_size:3*int_size],
                "big",
                signed=True,
            )
        ),
        str(
            int.from_bytes(
                result[3*int_size:4*int_size],
                "big",
                signed=True,
            )
        ),
        iters,
    )
    print(f"Valid: {is_valid}")