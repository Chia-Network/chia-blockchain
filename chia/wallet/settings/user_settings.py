from typing import Any, Dict

from chia.wallet.key_val_store import KeyValStore
from chia.wallet.settings.default_settings import default_settings
from chia.wallet.settings.settings_objects import BackupInitialized


class UserSettings:
    settings: Dict[str, Any]
    basic_store: KeyValStore

    @staticmethod
    async def create(
        store: KeyValStore,
        name: str = None,
    ):
        self = UserSettings()
        self.basic_store = store
        self.settings = {}
        await self.load_store()
        return self

    def _keys(self):
        all_keys = [BackupInitialized]
        return all_keys

    async def load_store(self):
        keys = self._keys()
        for setting in keys:
            name = setting.__name__
            object = await self.basic_store.get_object(name, BackupInitialized)
            if object is None:
                object = default_settings[name]

            assert object is not None
            self.settings[name] = object

    async def setting_updated(self, setting: Any):
        name = setting.__class__.__name__
        await self.basic_store.set_object(name, setting)
        self.settings[name] = setting
