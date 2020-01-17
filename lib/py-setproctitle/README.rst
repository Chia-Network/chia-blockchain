A Python module to customize the process title
==============================================

:author: Daniele Varrazzo

The ``setproctitle`` module allows a process to change its title (as displayed
by system tools such as ``ps`` and ``top``).

Changing the title is mostly useful in multi-process systems, for example
when a master process is forked: changing the children's title allows to
identify the task each process is busy with.  The technique is used by
PostgreSQL_ and the `OpenSSH Server`_ for example.

The procedure is hardly portable across different systems.  PostgreSQL provides
a good `multi-platform implementation`__:  this module is a Python wrapper
around PostgreSQL code.

- `Homepage <https://github.com/dvarrazzo/py-setproctitle>`__
- `Download <http://pypi.python.org/pypi/setproctitle/>`__
- `Bug tracker <https://github.com/dvarrazzo/py-setproctitle/issues>`__


.. _PostgreSQL: http://www.postgresql.org
.. _OpenSSH Server: http://www.openssh.com/
.. __: http://doxygen.postgresql.org/ps__status_8c_source.html


Installation
------------

``setproctitle`` is a C extension: in order to build it you will need a C
compiler and the Python development support (the ``python-dev`` package in
most Linux distributions). No further external dependencies are required.

You can use ``pip`` to install the module::

    pip install setproctitle

You can use ``pip -t`` or ``virtualenv`` for local installations, ``sudo pip``
for a system-wide one... the usual stuff. Read pip_ or virtualenv_ docs for
all the details.

.. _pip: https://pip.readthedocs.org/
.. _virtualenv: https://virtualenv.readthedocs.org/


Python 3 support
~~~~~~~~~~~~~~~~

As of version 1.1 the module works with Python 3. Just use
``pip``/``virtualenv`` for Python 3.

In order to build from the source package and test the module under Python 3,
the ``Makefile`` contains some helper targets.


Usage
-----

The ``setproctitle`` module exports the following functions:

``setproctitle(title)``
    Set *title* as the title for the current process.

``getproctitle()``
    Return the current process title.


Environment variables
~~~~~~~~~~~~~~~~~~~~~

A few environment variables can be used to customize the module behavior:

``SPT_NOENV``
    Avoid clobbering ``/proc/PID/environ``.

    On many platforms, setting the process title will clobber the
    ``environ`` memory area. ``os.environ`` will work as expected from within
    the Python process, but the content of the file ``/proc/PID/environ`` will
    be overwritten.  If you require this file not to be broken you can set the
    ``SPT_NOENV`` environment variable to any non-empty value: in this case
    the maximum length for the title will be limited to the length of the
    command line.

``SPT_DEBUG``
    Print debug information on ``stderr``.

    If the module doesn't work as expected you can set this variable to a
    non-empty value to generate information useful for debugging.  Note that
    the most useful information is printed when the module is imported, not
    when the functions are called.


Module status
-------------

The module can be currently compiled and effectively used on the following
platforms:

- GNU/Linux
- BSD
- MacOS X
- Windows

Note that on Windows there is no way to change the process string:
what the module does is to create a *Named Object* whose value can be read
using a tool such as `Process Explorer`_ (contribution of a more useful tool
to be used together with ``setproctitle`` would be well accepted).

The module can probably work on HP-UX, but I haven't found any to test with.
It is unlikely that it can work on Solaris instead.

.. _Process Explorer: http://technet.microsoft.com/en-us/sysinternals/bb896653.aspx


Other known implementations and discussions
-------------------------------------------

- `procname`_: a module exposing the same functionality, but less portable
  and not well packaged.
- `Issue 5672`_: where the introduction of such functionality into the stdlib
  is being discussed.

.. _procname: http://code.google.com/p/procname/
.. _Issue 5672: http://bugs.python.org/issue5672
