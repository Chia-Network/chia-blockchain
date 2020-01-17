/* A small demo to show how to use the display change */

#include "../src/spt_status.h"

#include <stdio.h>
#include <unistd.h>

int
main(int argc, char **argv)
{
    printf("Process PID: %i\n", getpid());

    argv = save_ps_display_args(argc, argv);
    init_ps_display("hello, world");
    printf("Title changed, press enter\n");
    getchar();

    set_ps_display("new title!", true);
    printf("Title changed again, press enter to exit\n");
    getchar();

    return 0;
}

