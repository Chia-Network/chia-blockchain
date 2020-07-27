export const presentBackupInfo = "BACKUP_INFO";
export const presentMain = "MAIN";

export const changeBackupView = view => ({ type: "BACKUP_VIEW", view: view });
export const setBackupInfo = backup_info => ({
  type: "BACKUP_INFO",
  backup_info: backup_info
});

export const selectFilePath = file_path => ({
  type: "SELECT_FILEPATH",
  file_path: file_path
});

const initial_state = {
  view: presentMain,
  backup_info: {},
  selected_file_path: null
};

export const backupReducer = (state = { ...initial_state }, action) => {
  switch (action.type) {
    case "BACKUP_VIEW":
      var view = action.view;
      return { ...state, view: view };
    case "BACKUP_INFO":
      var backup_info = action.backup_info;
      return { ...state, backup_info: backup_info };
    case "SELECT_FILEPATH":
      const file_path = action.file_path;
      return { ...state, selected_file_path: file_path };
    default:
      return state;
  }
};
