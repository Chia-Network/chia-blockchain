/*-------------------------------------------------------------------------
 *
 * pyrun.c
 *    Stand-alone program to test with embedded Python.
 *
 *    Run a Python program read from stdin. In case of error return 1.
 *
 * Copyright (c) 2011-2016 Daniele Varrazzo <daniele.varrazzo@gmail.com>
 *
 *-------------------------------------------------------------------------
 */

#include <Python.h>

int
main(int argc, char *argv[])
{
    int rv = 0;

    Py_Initialize();

    if (0 != PyRun_SimpleFile(stdin, "stdin")) {
        rv = 1;
    }

    Py_Finalize();

    return rv;
}

