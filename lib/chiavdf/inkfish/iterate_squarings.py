def iterate_squarings(x, powers_to_calculate):
    """
    Repeatedly square x.

    The values in the "powers_to_calculate" (an iterator),
    which must be increasing, will be returned.
    """

    powers_calculated = {}
    powers_to_calculate = sorted(powers_to_calculate)

    # Repeatedly square x
    previous_power = 0
    for current_power in powers_to_calculate:
        for _ in range(current_power - previous_power):
            x = pow(x, 2)
        powers_calculated[current_power] = x
        previous_power = current_power
    return powers_calculated


"""
Copyright 2018 Chia Network Inc

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
