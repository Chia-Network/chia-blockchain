export const wordChanged = () => ({ type: 'MNEMONIC_TYPING' });
export const resetMnemonic = () => ({ type: 'RESET_MNEMONIC' });
export const setIncorrectWord = (word: string) => ({
  type: 'SET_INCORRECT_WORD',
  word,
});

type MnemonicState = {
  mnemonic_input: string[];
  incorrect_word?: string | null;
};

const initialState: MnemonicState = {
  mnemonic_input: new Array(24).fill(''),
  incorrect_word: null,
};

export const mnemonic_word_added = (data: unknown) => ({
  ...wordChanged(),
  data,
});

export default function mnemonicReducer(
  state = { ...initialState },
  action: any,
): MnemonicState {
  switch (action.type) {
    case 'MNEMONIC_TYPING':
      const { word, id } = action.data;
      const current_input = state.mnemonic_input;
      current_input[id] = word;
      return { ...state, mnemonic_input: current_input };
    case 'RESET_MNEMONIC':
      return {
        mnemonic_input: new Array(24).fill(''),
        incorrect_word: null,
      };
    case 'SET_INCORRECT_WORD':
      return { ...state, incorrect_word: action.word };
    default:
      return state;
  }
}
