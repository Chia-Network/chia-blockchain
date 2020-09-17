export const openDialog = (title: string, text: string) => {
  return {
    type: "DIALOG_CONTROL",
    open: true,
    title,
    text,
  };
};

export const closeDialog = (id: number) => {
  return {
    type: "DIALOG_CONTROL",
    open: false,
    id,
  };
};

type DialogState = {
  dialogs: {
    id: number,
    title: string,
    label: string,
  }[],
};

const initialState: DialogState = {
  dialogs: []
};

export default function dialogReducer(state = { ...initialState }, action: any): DialogState {
  switch (action.type) {
    case "DIALOG_CONTROL":
      if (action.open) {
        const { title, text } = action;

        return { 
          ...state, 
          dialogs: [
            ...state.dialogs,
            createDialog(Date.now(), title, text)
          ], 
        };
      } else {
        return { 
          ...state,
          dialogs: state.dialogs.filter((dialog) => dialog.id !== action.id),
        };
      }
    default:
      return state;
  }
}
