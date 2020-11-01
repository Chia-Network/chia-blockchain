from src.wallet.settings.settings_objects import BackupInitialized

default_backup_initialized = BackupInitialized(False, False, False, True)

default_settings = {BackupInitialized.__name__: default_backup_initialized}
