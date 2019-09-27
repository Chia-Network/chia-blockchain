/*#include "include.h"

#include "integer.h"

#include "vdf_new.h"

int main(int argc, char** argv) {
    parse_args(argc, argv);

    integer a;
    integer b;
    integer c;
    generator_for_discriminant(arg_discriminant, a, b, c);

    for (int x=0;x<arg_iterations;++x) {
        square(a, b, c);
        reduce(a, b, c);
    }

    print( "" );

    print(a.to_string());
    print( "" );

    print(b.to_string());
    print( "" );

    print(c.to_string());
    print( "" );
}**/
