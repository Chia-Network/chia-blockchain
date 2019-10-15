Copyright 2018 Ilya Gorodetskov
generic@sundersoft.com

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

=== Summary ===

The NUDUPL algorithm is used. The equations are based on cryptoslava's equations from the previous contest. They were modified slightly to increase the level of parallelism.

The GCD is a custom implementation with scalar integers. There are two base cases: one uses a lookup table with continued fractions and the other uses the euclidean algorithm with a division table. The division table algorithm is slightly faster even though it has about 2x as many iterations.

After the base case, there is a 128 bit GCD that generates 64 bit cofactor matricies with Lehmer's algorithm. This is required to make the long integer multiplications efficient (Flint's implementation doesn't do this).

The GCD also implements Flint's partial xgcd function, but the output is slightly different. This implementation will always return an A value which is > the threshold and a B value which is <= the threshold. For a normal GCD, the threshold is 0, B is 0, and A is the GCD. Also the interfaces are slightly different.

Scalar integers are used for the GCD. I don't expect any speedup for the SIMD integers that were used in the last implementation since the GCD only uses 64x1024 multiplications, which are too small and have too high of a carry overhead for the SIMD version to be faster. In either case, most of the time seems to be spent in the base case so it shouldn't matter too much.

If SIMD integers are used with AVX-512, doubles have to be used because the multiplier sizes for doubles are significantly larger than for integers. There is an AVX-512 extension to support larger integer multiplications but no processor implements it yet. It should be possible to do a 50 bit multiply-add into a 100 bit accumulator with 4 fused multiply-adds if the accumulators have a special nonzero initial value and the inputs are scaled before the multiplication. This would make AVX-512 about 2.5x faster than scalar code for 1024x1024 integer multiplications (assuming the scalar code is unrolled and uses ADOX/ADCX/MULX properly, and the CPU can execute this at 1 cycle per iteration which it probably can't).

The GCD is parallelized by calculating the cofactors in a separate slave thread. The master thread will calculate the cofactor matricies and send them to the slave thread. Other calculations are also parallelized.

The VDF implementation from the first contest is still used as a fallback and is called about once every 5000 iterations. The GCD will encounter large quotients about this often and these are not implemented. This has a negligble effect on performance. Also, the NUDUPL case where A<=L is not implemented; it will fall back to the old implementation in this case (this never happens outside of the first 20 or so iterations).

There is also corruption detection by calculating C with a non-exact division and making sure the remainder is 0. This detected all injected random corruptions that I tested. No corruptions caused by bugs were observed during testing. This cannot correct for the sign of B being wrong.

=== GCD continued fraction lookup table ===

The is implemented in gcd_base_continued_fractions.h and asm_gcd_base_continued_fractions.h. The division table implementation is the same as the previous entry and was discussed there. Currently the division table is only used if AVX2 is enabled but it could be ported to SSE or scalar code easily. Both implementations have about the same performance.

The initial quotient sequence of gcd(a,b) is the same as the initial quotient sequence of gcd(a*2^n/b, 2^n) for any n. This is because the GCD quotients are the same as the continued fraction quotients of a/b, and the initial continued fraction quotients only depend on the initial bits of a/b. This makes it feasible to have a lookup table since it now only has one input.

a*2^n/b is calculated by doing a double precision division of a/b, and then truncating the lower bits. Some of the exponent bits are used in the table in addition to the fraction bits; this makes each slot of the table vary in size depending on what the exponent is. If the result is outside the table bounds, then the division result is floored to fall back to the euclidean algorithm (this is very rare).

The table is calculated by iterating all of the possible continued fractions that have a certain initial quotient sequence. Iteration ends when all of these fractions are either outside the table or they don't fully contain at least one slot of the table. Each slot that is fully contained by such a fraction is updated so that its quotient sequence equals the fraction's initial quotient sequence. Once this is complete, the cofactor matricies are calculated from the quotient sequences. Each cofactor matrix is 4 doubles.

The resulting code seems to have too many instructions so it doesn't perform very well. There might be some way to optimize it. It was written for SSE so that it would run on both processors.

This might work better on an FPGA possibly with low latency DRAM or SRAM (compared to the euclidean algorithm with a division table). There is no limit to the size of the table but doubling the latency would require the number of bits in the table to also be doubled to have the same performance.

=== Other GCD code ===

The gcd_128 function calculates a 128 bit GCD using Lehmer's algorithm. It is pretty straightforward and uses only unsigned arithmetic. Each cofactor matrix can only have two possible signs: [+ -; - +] or [- +; + -]. The gcd_unsigned function uses unsigned arithmetic and a jump table to apply the 64-bit cofactor matricies to the A and B values. It uses ADOX/ADCX/MULX if they are available and falls back to ADC/MUL otherwise. It will track the last known size of A to speed up the bit shifts required to get the top 128 bits of A.

No attempt was made to try to do the A and B long integer multiplications on a separate thread; I wouldn't expect any performance improvement from this.

=== Threads ===

There is a master thread and a slave thread. The slave thread only exists for each batch of 5000 or so squarings and is then destroyed and recreated for the next batch (this has no measurable overhead). If the original VDF is used as a fallback, the batch ends and the slave thread is destroyed.

Each thread has a 64-bit counter that only it can write to. Also, during a squaring iteration, it will not overwrite any value that it has previously written and transmitted to the other thread. Each squaring is split up into phases. Each thread will update its counter at the start of the phase (the counter can only be increased, not decreased). It can then wait on the other thread's counter to reach a certain value as part of a spin loop. If the spin loop takes too long, an error condition is raised and the batch ends; this should prevent any deadlocks from happening.

No CPU fences or atomics are required since each value can only be written to by one thread and since x86 enforces acquire/release ordering on all memory operations. Compiler memory fences are still required to prevent the compiler from caching or reordering memory operations.

The GCD master thread will increment the counter when a new cofactor matrix has been outputted. The slave thread will spin on this counter and then apply the cofactor matrix to the U or V vector to get a new U or V vector.

It was attempted to use modular arithmetic to calculate k directly but this slowed down the program due to GMP's modulo or integer multiply operations not having enough performance. This also makes the integer multiplications bigger.

The speedup isn't very high since most of the time is spent in the GCD base case and these can't be parallelized.