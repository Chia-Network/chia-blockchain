import { useEffect, useRef, useCallback } from 'react';
import { useSelector } from 'react-redux';
import { useUpdate } from 'react-use';
import { throttle } from 'lodash';

export default function useThrottleSelector<T extends (...args: any) => any>(
  fn: T,
  options: {
    wait?: number;
    leading?: boolean;
    trailing?: boolean;
    force?: (
      data: any,
      dataBefore: any,
      state: any,
      stateBefore: any,
    ) => boolean;
  } = {},
): ReturnType<T> {
  const { force, leading = true, trailing = true, wait = 0 } = options;

  const update = useUpdate();

  const refState = useRef<any>();
  const refData = useRef<any>();

  const processUpdate = useCallback(
    throttle(
      () => {
        update();
      },
      wait,
      {
        leading,
        trailing,
      },
    ),
    [wait, leading, trailing],
  );

  useSelector((state: any) => {
    const newState = fn(state);
    if (newState !== refData.current) {
      const stateBefore = refState.current;
      refState.current = state;

      const dataBefore = refData.current;
      refData.current = fn(state);
      processUpdate();

      if (
        force &&
        force(refData.current, dataBefore, refState.current, stateBefore)
      ) {
        update();
      }
    }
  });

  useEffect(
    () => () => {
      // @ts-ignore
      processUpdate.cancel();
    },
    [],
  );

  return refData.current;
}
