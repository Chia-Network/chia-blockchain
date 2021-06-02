import { useEffect } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { useInterval } from 'react-use';
import type { RootState } from '../modules/rootReducer';
import type Group from '../types/Group';
import { getPoolState } from '../modules/farmerMessages';

export default function usePoolState(): {
  loading: boolean;
  groups?: Group[];
} {
  const dispatch = useDispatch();
  const groups = useSelector((state: RootState) => state.group.groups);
  const loading = !groups;

  useInterval(() => {
    dispatch(getPoolState());
  }, 60000);

  useEffect(() => {
    dispatch(getPoolState());
  }, []);

  return {
    loading,
    groups,
  };
}