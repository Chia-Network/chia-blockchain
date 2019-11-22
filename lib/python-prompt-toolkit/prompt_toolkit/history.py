"""
Implementations for the history of a `Buffer`.

NOTE: Notice that there is no `DynamicHistory`. This doesn't work well, because
      the `Buffer` needs to be able to attach an event handler to the event
      when a history entry is loaded. This loading can be done asynchronously
      and making the history swappable would probably break this.
"""
import datetime
import os
from abc import ABCMeta, abstractmethod
from typing import AsyncGenerator, Iterable, List

from prompt_toolkit.application.current import get_app

from .eventloop import generator_to_async_generator
from .utils import Event

__all__ = [
    'History',
    'ThreadedHistory',
    'DummyHistory',
    'FileHistory',
    'InMemoryHistory',
]


class History(metaclass=ABCMeta):
    """
    Base ``History`` class.

    This also includes abstract methods for loading/storing history.
    """
    def __init__(self) -> None:
        # In memory storage for strings.
        self._loading = False
        self._loaded_strings: List[str] = []
        self._item_loaded: Event['History'] = Event(self)

    async def _start_loading(self) -> None:
        """
        Consume the asynchronous generator: `load_history_strings_async`.

        This is only called once, because once the history is loaded, we don't
        have to load it again.
        """
        def add_string(string: str) -> None:
            " Got one string from the asynchronous history generator. "
            self._loaded_strings.insert(0, string)
            self._item_loaded.fire()

        async for item in self.load_history_strings_async():
            add_string(item)

    #
    # Methods expected by `Buffer`.
    #

    def start_loading(self) -> None:
        " Start loading the history. "
        if not self._loading:
            self._loading = True
            get_app().create_background_task(self._start_loading())

    def get_item_loaded_event(self) -> Event['History']:
        " Event which is triggered when a new item is loaded. "
        return self._item_loaded

    def get_strings(self) -> List[str]:
        """
        Get the strings from the history that are loaded so far.
        """
        return self._loaded_strings

    def append_string(self, string: str) -> None:
        " Add string to the history. "
        self._loaded_strings.append(string)
        self.store_string(string)

    #
    # Implementation for specific backends.
    #

    @abstractmethod
    def load_history_strings(self) -> Iterable[str]:
        """
        This should be a generator that yields `str` instances.

        It should yield the most recent items first, because they are the most
        important. (The history can already be used, even when it's only
        partially loaded.)
        """
        while False:
            yield

    async def load_history_strings_async(self) -> AsyncGenerator[str, None]:
        """
        Asynchronous generator for history strings. (Probably, you won't have
        to override this.)

        This is an asynchronous generator of `str` objects.
        """
        for item in self.load_history_strings():
            yield item

    @abstractmethod
    def store_string(self, string: str) -> None:
        """
        Store the string in persistent storage.
        """


class ThreadedHistory(History):
    """
    Wrapper that runs the `load_history_strings` generator in a thread.

    Use this to increase the start-up time of prompt_toolkit applications.
    History entries are available as soon as they are loaded. We don't have to
    wait for everything to be loaded.
    """
    def __init__(self, history: History) -> None:
        self.history = history
        super().__init__()

    async def load_history_strings_async(self) -> AsyncGenerator[str, None]:
        """
        Asynchronous generator of completions.
        This yields both Future and Completion objects.
        """
        async for item in generator_to_async_generator(self.history.load_history_strings):
            yield item

    # All of the following are proxied to `self.history`.

    def load_history_strings(self) -> Iterable[str]:
        return self.history.load_history_strings()

    def store_string(self, string: str) -> None:
        self.history.store_string(string)

    def __repr__(self) -> str:
        return 'ThreadedHistory(%r)' % (self.history, )


class InMemoryHistory(History):
    """
    :class:`.History` class that keeps a list of all strings in memory.
    """
    def load_history_strings(self) -> Iterable[str]:
        return []

    def store_string(self, string: str) -> None:
        pass


class DummyHistory(History):
    """
    :class:`.History` object that doesn't remember anything.
    """
    def load_history_strings(self) -> Iterable[str]:
        return []

    def store_string(self, string: str) -> None:
        pass

    def append_string(self, string: str) -> None:
        # Don't remember this.
        pass


class FileHistory(History):
    """
    :class:`.History` class that stores all strings in a file.
    """
    def __init__(self, filename: str) -> None:
        self.filename = filename
        super(FileHistory, self).__init__()

    def load_history_strings(self) -> Iterable[str]:
        strings: List[str] = []
        lines: List[str] = []

        def add() -> None:
            if lines:
                # Join and drop trailing newline.
                string = ''.join(lines)[:-1]

                strings.append(string)

        if os.path.exists(self.filename):
            with open(self.filename, 'rb') as f:
                for line_bytes in f:
                    line = line_bytes.decode('utf-8')

                    if line.startswith('+'):
                        lines.append(line[1:])
                    else:
                        add()
                        lines = []

                add()

        # Reverse the order, because newest items have to go first.
        return reversed(strings)

    def store_string(self, string: str) -> None:
        # Save to file.
        with open(self.filename, 'ab') as f:
            def write(t: str) -> None:
                f.write(t.encode('utf-8'))

            write('\n# %s\n' % datetime.datetime.now())
            for line in string.split('\n'):
                write('+%s\n' % line)
