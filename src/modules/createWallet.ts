export const CREATE_CC_WALLET_OPTIONS = 'CREATE_CC_WALLET_OPTIONS';
export const CREATE_NEW_CC = 'CREATE_NEW_CC';
export const CREATE_EXISTING_CC = 'CREATE_EXISTING_CC';
export const CREATE_RL_WALLET_OPTIONS = 'CREATE_RL_WALLET_OPTIONS';
export const CREATE_RL_ADMIN = 'CREATE_RL_ADMIN';
export const CREATE_RL_USER = 'CREATE_RL_USER';
export const CREATE_DID_WALLET_OPTIONS = 'CREATE_DID_WALLET_OPTIONS';
export const CREATE_DID_WALLET = 'CREATE_DID_WALLET';
export const RECOVER_DID_WALLET = 'RECOVER_DID_WALLET';
export const ALL_OPTIONS = 'ALL_OPTIONS';

export const changeCreateWallet = (item: string) => ({
  type: 'CREATE_OPTIONS',
  item,
});

export const createState = (created: boolean, pending: boolean) => ({
  type: 'CREATE_STATE',
  created,
  pending,
});

type CreateWalletState = {
  view: string;
  created: boolean;
  pending: boolean;
};

const initialState: CreateWalletState = {
  view: ALL_OPTIONS,
  created: false,
  pending: false,
};

export default function createWalletReducer(
  state: CreateWalletState = { ...initialState },
  action: any,
): CreateWalletState {
  switch (action.type) {
    case 'LOG_OUT':
      return { ...initialState };
    case 'CREATE_OPTIONS':
      const { item } = action;
      return { ...state, view: item };
    case 'CREATE_STATE':
      return {
        ...state,
        created: action.created,
        pending: action.pending,
      };
    default:
      return state;
  }
}
