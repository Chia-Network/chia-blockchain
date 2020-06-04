from abc import ABC, abstractmethod


class AbstractWallet(ABC):
    def __init__(self):
        super().__init__()

    @abstractmethod
    def get_new_puzzle(self):
        pass

    @abstractmethod
    def puzzle_for_pk(self, pubkey: bytes):
        pass

    @abstractmethod
    def get_pending_change_balance(self):
        pass

    @abstractmethod
    def get_unconfirmed_balance(self):
        pass

    @abstractmethod
    def get_confirmed_balance(self):
        pass

    @abstractmethod
    def get_new_puzzlehash(self):
        pass
