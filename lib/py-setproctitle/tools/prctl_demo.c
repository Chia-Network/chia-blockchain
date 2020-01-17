/* A test to check what happens using ``prctl()``.
 *
 * The ``prctl()`` call is available in Linux from 2.6.9.
 *
 * See http://www.kernel.org/doc/man-pages/online/pages/man2/prctl.2.html
 */

#include <sys/prctl.h>          /* for prctl() */
#include <linux/prctl.h>        /* for PR_SET_NAME */

#include <stdio.h>
#include <unistd.h>

int
main(int argc, char **argv)
{
    printf("Process PID: %i\n", getpid());

    prctl(PR_SET_NAME, "Hello world");
    printf("Title changed, press enter\n");
    getchar();

    /* The string set by prctl can be read in ``/proc/PID/stat``
     * and ``/proc/PID/status``. It is displayed by ``ps`` but not by ``ps a``
     * (which instead displays the content of ``/proc/PID/cmdline``). ``top``
     * toggles between both visualizations pressing ``c``.
     */
    return 0;
}
