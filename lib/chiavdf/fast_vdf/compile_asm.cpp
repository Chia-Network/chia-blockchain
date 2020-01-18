#include <x86intrin.h>

#include "include.h"

#include "parameters.h"

#define COMPILE_ASM

#ifdef TEST_ASM
    #undef TEST_ASM
#endif

#include "bit_manipulation.h"
#include "double_utility.h"
#include "integer.h"

#include "gpu_integer.h"
#include "gpu_integer_divide.h"

#include "gcd_base_continued_fractions.h"
#include "gcd_base_divide_table.h"
#include "gcd_128.h"
#include "gcd_unsigned.h"

#include "asm_types.h"
#include "asm_vm.h"

#include "asm_base.h"
#include "asm_gcd_base_continued_fractions.h"
#include "asm_gcd_base_divide_table.h"
#include "asm_gcd_128.h"
#include "asm_gcd_unsigned.h"

#include "asm_main.h"

int main(int argc, char** argv) {
    set_rounding_mode();

    asm_code::compile_asm();
}
