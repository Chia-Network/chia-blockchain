import Wallet from '../types/Wallet';

export const presentBackupInfo = 'BACKUP_INFO';
export const presentMain = 'MAIN';

export const changeBackupView = (view: 'MAIN' | 'BACKUP_INFO') => ({
  type: 'BACKUP_VIEW',
  view,
});
export const setBackupInfo = (backup_info: Object) => ({
  type: 'BACKUP_INFO',
  backup_info,
});

export const selectFilePath = (file_path: string) => ({
  type: 'SELECT_FILEPATH',
  file_path,
});

type BackupState = {
  view: 'MAIN' | 'BACKUP_INFO';
  backup_info: {
    type?: 'BACKUP_INFO' | 'SELECT_FILEPATH';
    backup_info?: string;
    file_path?: string;
    timestamp?: number;
    version?: string;
    wallets?: Wallet[];
    downloaded?: boolean;
    backup_host?: string;
    fingerprint?: string;
  };
  selected_file_path?: string | null;
};

const initialState: BackupState = {
  view: presentMain,
  backup_info: {},
  selected_file_path: null,
};

export default function backupReducer(
  state: BackupState = { ...initialState },
  action: any,
): BackupState {
  switch (action.type) {
    case 'BACKUP_VIEW':
      return {
        ...state,
        view: action.view,
      };
    case 'BACKUP_INFO':
      return {
        ...state,
        backup_info: action.backup_info,
      };
    case 'SELECT_FILEPATH':
      return {
        ...state,
        selected_file_path: action.file_path,
      };
    default:
      return state;
  }
}
