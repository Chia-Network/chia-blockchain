/* trying to understand why in order to clobber argv
 * postgres moves around environ too.
 */
#include <stdio.h>

extern char **environ;

int
main(int argc, char **argv)
{
    char **p;
    printf("argv:       %p\n", argv);
    printf("environ:    %p\n", environ);
    for (p = argv; *p; ++p) {
        printf("argv[%i]:    %p (%s)\n", p - argv, *p, *p);
    }
    for (p = environ; *p; ++p) {
        printf("environ[%i]: %p (%s)\n", p - environ, *p, *p);
    }

    /* My conclusion is that environ is contiguous to argv */
    return 0;
}

