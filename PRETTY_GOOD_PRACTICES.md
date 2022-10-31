<!--
- Use semantic newlines (one line per sentence generally)
- Do not wrap lines
-->

# Pretty Good Practices

Software development is complicated and often requires significant flexibility in terms of the patterns used.
But...
Using that flexibility in all cases results in difficult to read and buggy code.
The topics covered here are intended to provide good default patterns to use in most cases.
In exceptional cases, other patterns can be discussed and considered.

The goal of defining and applying these practices is to increase code quality when the code is first written.
This is expected to improve product quality while also decreasing development time.

<!--
- Avoid simple common flaws early
- improved maintainability by all, including the community
- avoid excluding the community and their contributions
- automatic code formatting
- Small functions are readable and testable
- Clearly express yourself, avoid clever code golf style solutions
- avoid leveraging language flexibility in favor of relatively static approaches
- often highly dynamic and introspective code can be well isolated and buffered from the rest of the code
- Test coverage, both unit and integration independently
- avoid burying i/o
- process/guidelines
- education
- more robust against changes, functional or refactor
- type checking
- comments
- architecture level quality
-->

## Context managers

When you want to make sure you do something later, context managers are the answer.
The `with` statement is how you use a context manager.
This is useful for many forms of resource management and cleanup.

- Closing files that are opened
- Releasing locks that are acquired
- Committing or rolling back database transactions
- Shutting down services that are started
- Deleting temporary files that are created
- etc

One common use of a context manager is to encapsulate a `try:` block in a reusable form.
The underlying dunder (double underscore) methods for a context manager are `.__enter__()` and `.__exit__()`.
Usually it is more natural to use `@contextlib.contextmanager` to create a context manager from a generator function.
Async context managers can be similarly created for use with the `async with` statement.

Context managers can often also replace functions that accept callback functions which are called immediately while providing some setup or teardown.
The context manager has the upside that the 'callback function' can be just bare code and also that the manager doesn't need to have any awareness of the code it is providing setup and teardown for.

Note that you can already use a file object as a context manager so these definitions are already available directly on the file, but it makes a simple example.

```python
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, TextIO, TypeVar


T = TypeVar("T")


# just manually do it without any re-usability

def manual(path: Path):
    file = open(path)
    try:
        return file.read()
    finally:
        file.close()


# use a function that takes a callback

def callbacker(path: Path, callback: Callable[[TextIO], T]) -> T:
    file = open(path)
    try:
        return callback(file)
    finally:
        file.close()


def the_callback(file: TextIO) -> str:
    return file.read()


def use_callbacker(path: Path) -> str:
    return callbacker(path=path, callback=the_callback)


# the preferred form for this example with a context manager

@contextmanager
def manager(path: Path):
    file = open(path)
    try:
        yield file
    finally:
        file.close()

def use_managed(path: Path):
    with manager(path=path) as file:
        return file.read()


# the real form for this since files are already context managers

def use_open_directly(path: Path):
    with open(path) as file:
        return file.read()
```


### Context managers for single use scenarios

Even when no reuse is necessary there are still reasons to use context managers.
They allow encapsulation of the setup and teardown separately from the code using it.
In doing so they help avoid mixing with other setup and teardown resulting in unintended consequences.

```python
def f(x, y, z):
    x.setup()
    y.setup(x)
    try:
        z.process(x, y)
    finally:
        x.teardown()
        y.teardown()
```

This example has some likely errors and risks.
Normally you teardown in the opposite order that you setup while this code does not.
If `y.setup()` fails then `x.teardown()` will not get called.
If `x.teardown()` fails then `y.teardown()` will not get called.
These errors would not be possible as written below.

```python
def f(x, y, z):
    with x.setup():
        with y.setup(x):
            z.process(x, y)
```


### Examples

- https://github.com/Chia-Network/chia-blockchain/pull/11467
- https://github.com/Chia-Network/chia-blockchain/pull/10166


## Classes

There are a few basic goals for classes that are targeted by the guidance provided below.

- Creating an instance of a class should be a trivial activity so that when needed it can be done without any expensive computation, waiting on other resources, reading from disk, or having to bypass any restrictive checks.
- The attributes of a class should always be present from the moment the instance exists until the last reference is dropped.
- The list of attributes should be clearly apparent at a glance including detailed type hints.

### `dataclasses`

One useful tool in encouraging and helping achieve the above goals is the `dataclasses` module.
It is useful for the vast majority of classes, not just trivial classes with a few attributes and no methods.
One of the benefits of using a more structured form of class definition is to take away flexibility in favor of quickly understandable consistency.
Here is the basic form of a class written using `dataclasses`.

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class Developer:
    name: str
    words_per_minute: float
    primary_language: str
```

When we avoid using `@dataclass` it is easy to make various errors.
There are two places where you might add hints: on the class itself and in `.__init__()`.
It is easy to miss hints altogether.
Some attributes may only be assigned in some cases.
All of these make it more complicated to write a quality class and harder to read the result even when it is correct.

### Handling expensive operations adjacent to construction

While it is important to be able to construct an instance of a class trivially, there are often expensive operations that coincide with instantiation in many cases.
Since there is only one `.__init__()`, we must use regular functions and `@classmethods` to move forward with supporting the non-trivial cases of construction.
This is often a foreign and troublesome concept to accept.
Let's consider a case with a builtin type where not doing this would be clearly problematic.
In a case where you want a random integer, would you rather write `random.randrange(10)` or `int(random=True, maximum=10)`?
For another way we like to create integers, do we want `int.from_bytes(blob, byteorder="big")` or `int(from_bytes=True, byteorder="big")`.
If you consider the number of parameters that would have to be mixed together in `int.__init__()` to handle all the possible cases it quickly becomes apparent that using `int()` for all means of creating an integer is not practical.
Luckily, most classes don't do that and ours don't have to either.
How about a couple examples.

```python
import json
from dataclasses import dataclass
from typing import Type, TypeVar


_T_Coin = TypeVar("_T_Coin", bound="Coin")

@dataclass(frozen=True)
class Coin:
    hash: bytes
    value: int

    @classmethod
    def from_json(cls: Type[_T_Coin], text: str) -> _T_Coin:
        decoded = json.loads(text)

        return cls(
            hash=bytes.fromhex(decoded["hash"]),
            value=decoded["value"],
        )


def create_coin_from_bytes(blob: bytes) -> Coin:
    return Coin(
        hash=blob[:32],
        value=int.from_bytes(blob[32:], byteorder="big"),
    )
```

### Immutability

In many cases there isn't much need to modify a class.
This comes with benefits like knowing that an object won't be modified when you are using it.
Inline with the above recommendations there is `@dataclass(frozen=True)` for this.
While Python offers no true guarantees of immutability, using `frozen=True` will result in an exception if you try to assign a new value to an attribute using any normal means.
This is a good default to start with until you find the need to mutate the instances.

Note that this does not stop you from mutating an attribute object itself.
`my_frozen_instance.a_list_attribute.append(23)` is still possible.
Keep this in mind when considering what types to use as attributes on frozen classes.

### Inheritance

In some languages inheritance is the only way to mix multiple types of objects into a single container.
That is not the case with Python.
We should strive to learn about other options and figure out how to make them work for us.

Inheritance is somewhere between hard and impossible to do right.

## Type Hinting

At nearly all cost, do not hint `Any`...
Yes, before you know anything about type hinting, know that.
`Any` indicates that you can do anything you want with the hinted object which basically defeats the use of type checking.
If you don't care what type the object is, use `object`.

Now that you know how to avoid defeating type hint checks...

Python is strongly and dynamically typed.
Being strongly typed means that an object isn't just an object with attributes, it is an instance of a specific type.
Being dynamically typed means that a variable, an attribute, a list element, or any other reference can refer to an object that is an instance of any type and that can change at any assignment.
While not being constrained to strictly only referencing particular types can be useful, it can also encourage impossible to follow code.
It is often helpful to default to not leveraging this flexibility.
Type hints are used to indicate the intended level of flexibility at each point in the code.
Objects are not checked against the type hints at runtime.
mypy is used to statically analyze the hints.

Clearly defining what types can be properly handled in each function parameter, variable, and attribute allows for static analysis to check for errors basic errors.
Passing a list where a set is expected, returning a float where an int is expected, indexing a list with a string because you thought it was a dict, and so on.
While tests are still critical to confirm that the proper _values_ are created, hinting makes it easy to get extensive coverage that proper _types_ are being processed.
Our goal is to reach complete hinting coverage on all code with relatively strict mypy configuration.
This provides a rigorous level of checking for basic errors such as accessible unavailable attributes, mixing different types of elements in lists, treating a list as if it is a dict, and so on.

Note that as of Python 3.9 there were some broad changes implemented that allowed for hinting with the builting `list[int]` as opposed to `typing.List[int]`.
Also, in new Python versions `Union[str, int]` can be written as `str | int`.
While it is possible to some degree for us to use those forms despite running in older Python versions, we will not presently be using the newer forms.

### Should hinting affect the form of the code

Yes.
If it is hard to hint, it is often hard to reason about and this should be taken as encouragement to explore simpler alternative forms for the code.
If it is hard to deal with the knock on complaints from mypy triggered by the hints, then again, maybe there's another better form for the code.

### Basic hints

```python
from typing import List

def sum_bigger_values(values: List[int], minimum: int) -> int:
    return sum(value for value in values if value > minimum)
```

This says that our function accepts a parameter `values` that is hinted as `List[int]` meaning it will be a list where each element is an integer.
The `minimum` parameter should be an integer.
`-> int:` indicates that the returned value will be an integer.

Note that Python functions always return a single object.
If there is either no `return` statement or just a bare `return` statement, the `None` object is returned.
Regardless, this should be hinted explicitly with `-> None:`.
While a bit verbose, this is simpler than making exceptions for the right cases while not letting the wrong cases slip through.

### Optional values

All Python references always refer to an object.
Sometimes we want to indicate that there presently is no object for them to refer to.
Often we use the `None` object for these cases.
The term 'optional' is used to express this.

```python
from typing import Optional

def print_name(first: str, last: Optional[str] = None) -> None:
    if last is None:
        return first

    return f"{first} {last}"
```

The `last` parameter can be passed either a string or `None`.
Note that an optional parameter is distinct from an optional hint, though they are often used together.
An optional parameter has a default and is not required to be passed when calling the function.
For example, `def f(x: int = 0) -> None:` can be called as `f()` without passing the optional `x` parameter.
Since it is not hinted as optional, `f(x=None)` is not valid from a type hinting perspective.
In the other direction, `def g(x: Optional[int]) -> None` may be called as `g(x=None)` since `x` is hinted as `Optional`, but `g()` is not valid since the parameter `x` has no default value.

Note that `Optional[int]` is equivalent to `Union[None, int]`.
Sometimes in error messages from mypy you will see the `Union` form even when you typed the `Optional` form.

While optional hinted parameters aren't too much trouble, optional returns and attributes have significant implications.
Every location that calls a function with an optional return or accesses an optionally hinted attribute is likely to have to `if value is None:` or similar before acting on the value.
If we consider a hint such as `Optional[List[int]]`, in many cases it will be simpler to just hint `List[int]` and have an empty list instead of `None`.
Another option is to raise an exception instead of returning `None`.
The best choice is highly dependent on the context in which the function is called and how the result is handled.
Please consider all options against both the concept of the function and the pragmatic usage of the function.
In some cases it will take a non-trivial code reorganization to avoid the optionality.
With new code, take that seriously.
With existing code, at least try to see what the alternative form would be as a chance to practice thinking it through.

### Union

Sometimes code can handle multiple different types despite them not being in a common inheritance hierarchy.
Unions describe these cases when the types are just different.

```python
from os import PathLike
from pathlib import Path
from typing import Union


def read_file(path: Union[str, PathLike]) -> str:
    return Path(path).read_text(encoding="utf-8")
```

### Protocols

In other cases of allowing multiple types that are also not related by inheritance but which do provide similar attributes and methods, interfaces can be used.
The preferred mechanism for defining object interfaces is [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol).
This enables [structural typing](https://en.wikipedia.org/wiki/Structural_type_system) where the type hints can require certain attributes of the object instead of operating purely based on an inheritance hierarchy to determine compatibility.
Since inheritance isn't required, this can be retrofitted to existing purely duck-typed code without having to actually modify every relevant class in every repo.
Until we drop Python 3.7 support we will need to get the `Protocol` class from `typing_extensions` instead of from `typing`.

```python
from dataclasses import dataclass

from typing_extensions import Protocol


class WaterfowlProtocol(Protocol):
    species: str

    def vocalize(self, count: int) -> str:
        ...


def bother_waterfowl(fowl: WaterfowlProtocol, aggressiveness: int):
    print(f"the {fowl.species} went {fowl.vocalize(count=aggressiveness)}")


@dataclass
class Duck:
    species: str = "duck"

    def vocalize(self, count: int) -> str:
        return " ".join(["quack"] * count)


@dataclass
class Goose:
    species: str = "goose"

    def vocalize(self, count: int) -> str:
        return " ".join(["honk"] * count)


bother_waterfowl(fowl=Duck(), aggressiveness=1)
bother_waterfowl(fowl=Goose(), aggressiveness=3)
```

When hinting based on a Protocol there can often be unexpected complexities.
Consider passing in an instance of a class with an attribute hinted `str` while the protocol hints it as `Union[str, int]`.
It is common to expect that `str` satisfies `Union[str, int]` and to be throughly confused by mypy's complaint that it does not.
The hazard here is that since the function receiving the object thinks the attribute can be either a `str` or an `int` it may decide to assign an `int` to it.
The protocol says this is ok.
A good solution for many cases is to hint that attribute as being read only on the protocol.
This is done via a read only [property](https://docs.python.org/3/library/functions.html#property).
Note that attributes of protocols that are themselves protocols should be read-only (https://github.com/python/mypy/issues/12990).

```python
from typing import Union

from typing_extensions import Protocol


class AProtocol(Protocol):
    a_writable_attribute: bool

    @property
    def a_read_only_attribute(self) -> Union[str, int]:
        ...
```

Aside from identifying attributes on a class, `Protocol` can be used for more expressive hinting of callables than you can do with `Callable`.
One use is to be able to indicate parameter names.
Remember that functions and methods are just themselves regular Python objects.
When you call an object such as calling `f` by writing `f()`, the [`.__call__()`](https://docs.python.org/3/reference/datamodel.html#object.__call__) method is what gets executed.
A protocol for a callable often has just a `.__call__()` method.

```python
from typing_extensions import Protocol


class ThreeIntAdder(Protocol):
    def __call__(self, first: int, second: int, third: int) -> int:
        ...
```

Another option for additional expressivity around hinting a callable with a protocol is to use overloads to narrow the possible combinations of calls.
It is often better to just avoid overload situations, but as we retrofit hints to existing code we may prefer this option sometimes.


### Type variables

`TypeVar` allows you to create 'variables' for type hints.
While a regular hint indicates something about a single element that you are hinting, a `TypeVar` is used to indicate a relationship between multiple elements being hinted.
They are not meant for basic individual element hinting, at least not generally.

```python
from typing import TypeVar


T = TypeVar("T")


def double(original: T) -> T:
    return 2 * original


an_int = double(original=2)
a_list = double(original=["a", "b"])
```

In this case we have related the parameter `original` indicating that it will be the same type as the return value will be.
If you pass in an `int` you will get an `int` back.
If you pass in a `list` you will get a `list` back.

`TypeVar` is not a good tool for relating multiple parameter types to each other.

```python
from typing import TypeVar


T = TypeVar("T")


def add(this: T, that: T) -> T:
    return this + that


an_int = add(this=3, that=9)
an_object = add(this="a", that=2)
```

What is happening here is that mypy will see that there are two parameters using the `TypeVar` and it will find the common ancestor of their types.
When passing an `int` and an `int` the common ancestor is `int` so you get that back as you might like to.
When passing a `str` and an `int`, they both directly inherit from `object` so that is the common ancestor and so that is the return type.
You probably intended to get an error in this case.
Probably don't do this.

### Generics

While not the most basic sort of hint, it is pretty common to see something like `List[str]`.
This just says that there will be a list, and it will contain strings.
`List` here is a generic.
While useful in other contexts, the use here of having a generic container where you can describe what it holds is an easy way to get started with generics.
Let's step it up a notch and consider a dictionary with string keys mapping to integer values, `Dict[str, int]`.
With this information mypy is able to know what sorts of objects will be in the result of `.keys()` or `.values()`.
Or that in `for key, value in the_dict.items():`, `key` will be a `str` and `value` will be an `int`.

When you look at defining a generic it becomes mostly about relating type hints in different places to each other.
Without writing an implementation, let's see what part of a cache leveraging generics might look like.

```python
from dataclasses import dataclass, field
from typing import Dict, Generic, Optional, TypeVar

KT = TypeVar("KT")
VT = TypeVar("VT")

@dataclass
class Cache(Generic[KT, VT]):
    _mapping: Dict[KT, VT] = field(default_factory=dict)

    def get(self, key: KT, default: Optional[VT] = None) -> Optional[VT]:
        ...

    def set(self, key: KT, value: VT) -> None:
        ...


c = Cache[int, str]()

# error: Argument 1 to "get" of "Cache" has incompatible type "str"; expected "int"
c.get("abc")

# error: Incompatible types in assignment (expression has type "Optional[str]", variable has type "bytes")
x: bytes = c.get(3)
```

### Forward References

Occasionally you need to hint a thing that does not exist yet.
This may occur when defining a class where a method needs to hint the class itself.
Here is a failing example.

```python
from typing_extensions import final


@final
class C:
    @classmethod
    def create(cls) -> C:
        return cls()
```

This results in a `NameError`.

```python-traceback
Traceback (most recent call last):
  File "/home/altendky/tmp/x.py", line 4, in <module>
    class C:
  File "/home/altendky/tmp/x.py", line 6, in C
    def create(cls) -> C:
NameError: name 'C' is not defined
```

The definition of class `C` has not been completed yet so the resulting object has not been assigned to the name `C` yet, hence the `NameError`.
This can be avoided for the Python runtime case by quoting as `-> "C":`.

```python
from typing_extensions import final


@final
class C:
    @classmethod
    def create(cls) -> "C":
        return cls()
```

When you either run mypy or use `typing.get_type_hints()`, this string `"C"` will get resolved to the class itself.
An alternative that does not require the quotes is to use the special import `from __future__ import annotations`.
This is the recommended form.

```python
from __future__ import annotations

from typing_extensions import final


@final
class C:
    @classmethod
    def create(cls) -> C:
        return cls()
```

This behavior was going to become default in Python 3.10 but was removed and did not make it into Python 3.11 either.
See [the footnote](https://docs.python.org/3.10/library/__future__.html#id1) on the `__future__` doc page.
If you want to read more about this see [PEP 563](https://peps.python.org/pep-0563/) and [PEP 649](https://peps.python.org/pep-0649/).

A more complicated case can come about from circular imports that are only relevant to hinting, not to runtime code.
Avoiding the circular import at runtime is done by 'hiding' the problematic import in an `if TYPE_CHECKING:` block.
At runtime, Python will consider that false and ignore it.
When running mypy analysis it will consider it true and process the imports.
mypy doesn't suffer from the circular import issues.
This does trigger the situation similar to above though where you try to reference a class which is not defined.
Both practices can be used together as in the example below to get to a complete solution.

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Note that the wallet state manager module imports the wallets.
    # This would create a problematic circular import condition at
    # runtime that `if TYPE_CHECKING:` avoids.
    from chia.wallet.wallet_state_manager import WalletStateManager


@dataclass
class SomeWallet:
    wallet_state_manager: WalletStateManager
```

## Tests

- Do not import `test_*` modules.  Instead locate shared tooling in non-test files within the `tests/` directory or subdirectories.
- Do not import fixtures.  Fixtures are shared by locating them in `conftest.py` files at whatever directory layer you want them to be recursively available from.
- Do not use test classes.
  `unittest` requires that tests be held in a class.
  pytest does not.
  Our tests are fully dependent on pytest so there's no use in retaining `unittest` compatibility for this single point.
  Making a few tests `unittest` compatible is not useful compared with the cost of inconsistency.

## CLI

- Use Click.
- Use subcommands for separate activities.
- Don't make users write JSON generally.
- Short options should be a single character.
- Long options should delimit words by dashes, not underscores.
- But backwards compatibility and consistency with the existing not-this-way stuff, how do we handle that?

## Async

- Don't catch `CancelledError`
- Consider shielding cancellation in shutdown cleanup code, maybe
- Store references to all tasks you spawn and be sure to clean them up

## Time

- For delta timing within a process do not use `time.time()` as it can have 'fake' deltas due to system clock changes.
  `time.monotonic()` is the direct alternative, though for specific cases other clocks tied to CPU performance, process time, or thread time may be of interest.

## Idioms

- Avoid use of non-booleans as booleans such as `if the_list:`.  If you mean `if len(the_list) > 0:` write that, if you mean `if an_optional_thing is not None:` write that.

## Exceptions

Exceptions provide a somewhat secondary path through the code compared to the normal `return` path from functions.
This adds complexity when considering the program flow.
It also avoids error checking and propagation boilerplate in code that won't be handling the exceptions.
This in turn avoids accidentally forgetting to check for or propagate an error.
Sadly, there are no 'type hints for exceptions' in Python at this time.

Exception handling should be focused.
Catch only the specific exceptions you know how to handle properly at that specific location.
When catching exceptions, remember that only rarely have you thought through all the possible exceptions that could occur.
Consider that if you have made a typo such as `pint("something")` (note the `r` missing from `print`) you probably want to know about this immediately.
You want the code to fail quickly and clearly with a `NameError`, not silently continue on to doing other things as if some miscellaneous network connection error occurred, for example.
This is why linters discourage bare `except:` and overly broad `except Exception:` clauses.
Especially don't `except BaseException:` as that can consume even shutdown requests.


```python
from datetime import datetime


class TooBigError(Exception):
    pass


def maybe_add_two(x: int) -> int:
    y = int(input("enter a number:"))

    if y > 3:
        raise TooBigError(f"{y} is too big!")

    return x + y

value = 0
for value in range(5):
    try:
        value += maybe_add_two(x=value)
    except TooBigError:
        print("oh well, too big, whatever")
        continue

    date_string = datetime.now().isoformat(timespec="microseconds")
    print(f"{date_string} value: {value}")
```

This example shows a few aspects of focused exception handling.
Let's compare it with the broad example below.

```python
from datetime import datetime


def maybe_add_two(x: int) -> int:
    y = int(input("enter a number:"))

    if y > 3:
        raise ValueError(f"{y} is too big!")

    return x + y

value = 0
for value in range(5):
    try:
        value += maybe_add_two(x=value)
        date_string = datetime.now().isoformat(timespec="microseconds")
        print(f"{date_string} value: {value}")
    except:
        print("oh well, too big, whatever")
```

In normal cases, these examples do the same thing.
In some exceptional cases, they do not.
One case where they differ is that the broad example has several lines in the `try:` block.
An exception from any of these lines, or functions they call, will trigger the `except:` block.
In the focused example, only the one line that we have considered handling the exception from can trigger the `except TooBigError:` block.
Additionally, in the focused example we catch only a single exception, `TooBigError`.
The broad example would also catch any `NameError`s coming from typos, etc., which would make debugging those much more complicated.
Not only does the focused example only catch a single exception type, it catches a single exception type that we defined.
This puts us in control of what might raise it.
In the broad example, there are two separate points that could readily exercise this hole.
First, the `int()` of the input could raise a `ValueError` such as for an input of `"m"` which can't be parsed to an integer.
Second, the `.isoformat()` call can raise a `ValueError` for an invalid `timespec=` argument.
Neither of these are the `"is too big!"` exception we were intending to catch.

- Raise your own errors to avoid grouping with other exceptions
- Include as few lines as possible in the `try:` block to avoid handling exceptions from other lines
- Catch specific exceptions you have thought about how to handle

Note that deeply buried I/O is rich with both opportunities for exceptions to be raised and the types of exceptions.
Just imagine all the numerous ways that reading and writing from disk can fail.
Picking the proper exception can be difficult.
Sometimes `OSError` is a useful intermediately scoped exception to handle file not found, permissions errors, etc.

In some cases you want to respond to a specific exception but still have an exception propagate.
You may want the original exception to continue after your action, or to raise a new exception that is more descriptive.
When reraising the original exception use just `raise` instead of `raise e`.
This avoids the exception traceback looking like it came from the line where it was reraised.

When raising a new exception that is meant to replace the original, use `raise TheException() from e`.
This documents that the new exception didn't just happen to occur while handling the original, rather it is a more descriptive replacement for the original.
In either case, both tracebacks will be included, but they will describe themselves differently.
Either `During handling of the above exception, another exception occurred:` for a new `raise TheException()` or `The above exception was the direct cause of the following exception:` for `raise TheException() from e`.

```python
class TooBigError(Exception):
    pass


class InvalidInputError(Exception):
    pass


def maybe_add_two(x: int) -> int:
    y_raw = input("enter a number:")
    try:
        y = int(y_raw)
    except ValueError as e:
        print(f"unable to parse as an integer: {y_raw!r}")
        raise InvalidInputError() from e

    if y > 3:
        raise TooBigError(f"{y} is too big!")

    return x + y

```

On occasions where it is desired to handle a broad swath of exceptions, there are some specific considerations.
This should happen primarily at a high level such as in an RPC framework.
For example, the RPC framework may want to take any exception raised by the route handler code and turn it into a well-formed failure response with `"success": False`, the error, and the traceback.
A corner case around such places where you might `except Exception as e:` is that in Python 3.7 and below `asyncio.CancelledError` inherits from `Exception`.
In Python 3.8 and above `asyncio.CancelledError` inherits from `BaseException`.
Cancellation should not be consumed except _maybe_ at the highest levels.
To provide broad exception handling while not accidentally catching cancellation, the cancellation exception can be caught and raised first.

```python
import asyncio

async def main():
    try:
        await asyncio.sleep(5)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(e)
```

## Information Exposure

- Categorize information into groups
  - mnemonics
  - local usernames
  - coin IDs
  - etc
- Which groups can go in logs?
- Which groups can go in RPC responses?
- Which groups can go in diagnostic reports? (beta program, etc)

## Git

- use `-x` with cherry pick
