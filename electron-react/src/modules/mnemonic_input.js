export const wordChanged = msg => ({ type: "MNEMONIC_TYPING" });
export const resetMnemonic = msg => ({ type: "RESET_MNEMONIC" });

const initial_state = {
  mnemonic_input: new Array(24).fill(""),
  incorrect_word: null
};

export const mnemonic_word_added = data => {
  var action = wordChanged();
  action.data = data;
  return action;
};

export const mnemonicReducer = (state = { ...initial_state }, action) => {
  switch (action.type) {
    case "MNEMONIC_TYPING":
      var word = action.data.word;
      var id = action.data.id;
      var current_input = state.mnemonic_input;
      console.log(state.mnemonic_input);
      current_input[id] = word;
      return { ...state, mnemonic_input: current_input };
    case "RESET_MNEMONIC":
      return { ...initial_state };
    case "INCOMING_MESSAGE":
      if (command === "add_key") {
        success = data.success;
        if (!success) {
          incorrect_word = data.reason;
        }
      }

    default:
      return state;
  }
};
