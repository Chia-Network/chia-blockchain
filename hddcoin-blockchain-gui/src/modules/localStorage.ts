import { uniqBy, orderBy } from 'lodash';
import type Challenge from '../types/Challenge';
import { service_farmer, service_harvester } from '../util/service_names';

export function setItem(key: string, value: any) {
  return {
    type: 'LOCAL_STORAGE_SET_ITEM',
    key,
    value,
  };
}

export function removeItem(key: string) {
  return {
    type: 'LOCAL_STORAGE_REMOVE_ITEM',
    key,
  };
}

type LocalStorageState = {
  [key: string]: any;
};

const initialState: LocalStorageState = {};

export default function localStorageReducer(
  state = { ...initialState },
  action: any,
): LocalStorageState {
  const { key, value } = action;

  switch (action.type) {
    case 'LOCAL_STORAGE_SET_ITEM':
      return {
        ...state,
        [key]: value,
      };
    case 'LOCAL_STORAGE_REMOVE_ITEM':
      const newState = { ...state };
      if (key in newState) {
        delete newState[key];
      }

      return newState;

    case 'INCOMING_MESSAGE':
      if (
        action.message.origin !== service_farmer &&
        action.message.origin !== service_harvester
      ) {
        return state;
      }
      const {
        message: { data, command },
      } = action;

      if (command === 'get_latest_challenges') {
        if (data.success === false) {
          return state;
        }

        const { latest_challenges } = data;

        const challengesWithEstimation = latest_challenges
          .filter((item: Challenge) => item.estimates && item.estimates.length)
          .map((challenge: Challenge) => ({
            ...challenge,
            timestamp: Date.now(),
          }));

        const newLastAttepmtedProof = state.lastAttepmtedProof
          ? [...state.lastAttepmtedProof, ...challengesWithEstimation]
          : [...challengesWithEstimation];

        const uniqueLastAttepmtedProof = orderBy(
          uniqBy(newLastAttepmtedProof, (item) => item.challenge),
          (item) => -item.height,
          'asc',
        ).slice(0, 10);

        return {
          ...state,
          lastAttepmtedProof: uniqueLastAttepmtedProof,
        };
      }
      return state;
    default:
      return state;
  }
}
