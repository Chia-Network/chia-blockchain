import { useReducer } from 'react';

export default function useForceUpdate() {
  const [_ignored, forceUpdate] = useReducer((x) => x + 1, 0);

  return forceUpdate;
}
