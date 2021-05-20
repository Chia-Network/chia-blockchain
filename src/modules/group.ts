import type Group from '../types/Group';

export async function createGroup() {}

type GroupState = {
  groups?: Group[];
};

const initialState: GroupState = {
  groups: [
    {
      id: '1',
      self: false,
      name: 'Group A',
      poolUrl: 'http://poolin.com/info',
      state: 'FREE',
      balance: 0,
      address: 'xch1rdgndazfzqn6qf0kt4a62k4zq6ny6altk0rfssy4xtavfysvupyq389a57',
    },
    {
      id: '2',
      self: true,
      name: 'Group B',
      state: 'POOLING',
      balance: 0,
      address: 'xch1rdgndazfzqn6qf0kt4a62k4zq6ny6altk0rfssy4xtavfysvupyq389a57',
    },
    {
      id: '3',
      self: false,
      name: 'Group C',
      poolUrl: 'http://poolin2.com/info',
      state: 'ESCAPING',
      balance: 0,
      address: 'xch1rdgndazfzqn6qf0kt4a62k4zq6ny6altk0rfssy4xtavfysvupyq389a57',
    },
  ],
};

export default function groupReducer(
  state = { ...initialState },
  action: any,
): GroupState {
  const { queue } = action;

  switch (action.type) {
    case 'POOL_GROUP_INIT':
      return {
        ...state,
        groups: action.groups,
      };
    default:
      return state;
  }
}
