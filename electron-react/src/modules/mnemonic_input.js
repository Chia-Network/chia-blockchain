export const wordChanged = msg => ({ type: "MNEMONIC_TYPING" });
export const resetMnemonic = msg => ({ type: "RESET_MNEMONIC" });
export const setIncorrectWord = word => ({ type: "SET_INCORRECT_WORD", word });

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
      current_input[id] = word;
      return { ...state, mnemonic_input: current_input };
    case "RESET_MNEMONIC":
      return {
        mnemonic_input: new Array(24).fill(""),
        incorrect_word: null
      };
    case "SET_INCORRECT_WORD":
      return { ...state, incorrect_word: action.word };
    default:
      return state;
  }
};
