const dialogControl = () => ({ type: "DIALOG_CONTROL" });

export const openDialog = (title, text) => {
  var action = dialogControl();
  action.open = true;
  action.title = title;
  action.text = text;
  return action;
};

export const closeDialog = id => {
  var action = dialogControl();
  action.open = false;
  action.id = id;
  return action;
};

const initial_state = {
  dialogs: []
};

const dialog = (id, title, label) => ({ id: id, title, label });

export const dialogReducer = (state = { ...initial_state }, action) => {
  switch (action.type) {
    case "DIALOG_CONTROL":
      if (action.open) {
        const id = Date.now();
        const title = action.title;
        const text = action.text;
        const di = dialog(id, title, text);
        const new_dialogs = [...state.dialogs];
        new_dialogs.push(di);

        return { ...state, dialogs: new_dialogs };
      } else {
        const new_dialogs = [];

        for (var i = 0; i < state.dialogs.length; i++) {
          const dialog = state.dialogs[i];
          if (dialog.id === action.id) {
            continue;
          } else {
            new_dialogs.push(dialog);
          }
        }

        return { ...state, dialogs: new_dialogs };
      }
    default:
      return state;
  }
};
