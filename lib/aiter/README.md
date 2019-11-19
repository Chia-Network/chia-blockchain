[![Build Status](https://travis-ci.org/richardkiss/aiter.png?branch=master)](https://travis-ci.org/richardkiss/aiter)
[![codecov.io](https://codecov.io/github/richardkiss/aiter/coverage.svg?branch=master)](https://codecov.io/github/richardkiss/aiter)
[![Documentation Status](https://readthedocs.org/projects/aiter/badge/?version=latest)](https://aiter.readthedocs.io/en/latest/?badge=latest)



aiter -- Asynchronous Iterator Patterns
=======================================


[PEP 525](https://www.python.org/dev/peps/pep-0525/) describes *asynchronous iterators*, a merging of iterators with async functionality. Python 3.6 makes legal constructs such as

```
async for event in peer.event_iterator:
    await process_event(event)
```

which is a huge improvement over using `async.Queue` objects which have no built-in way to determine "end-of-stream" conditions.

This module implements some patterns useful for python asynchronous iterators.

Documentation available on [readthedocs.io](https://aiter.readthedocs.io/).

A [tutorial](TUTORIAL.org) is available. [github version](https://github.com/richardkiss/aiter/blob/feature/tutorial/TUTORIAL.org)

*CAVEAT* This project is still in its infancy, and I reserve the right to rename things and cause other breaking changes.
