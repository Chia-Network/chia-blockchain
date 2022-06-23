import {
  Location,
  NavigateFunction,
  NavigateOptions,
  To,
  useLocation,
  useNavigate,
} from 'react-router-dom';
import JSONbig from 'json-bigint';
import { isString } from 'lodash';

export type SerializedNavigationStateResult = {
  navigate: NavigateFunction;
  location: Location;
  getLocationState: () => any;
};

export default function useSerializedNavigationState(): SerializedNavigationStateResult {
  const originalNavigate = useNavigate();
  const location = useLocation();

  function wrappedNavigate(path: To | number, options?: NavigateOptions): void {
    if (options?.state) {
      const state = JSONbig.stringify(options?.state);
      originalNavigate(path, { ...options, state });
    } else {
      originalNavigate(path, options);
    }
  }

  function getLocationState() {
    const { state } = location;
    if (state && isString(state)) {
      return JSONbig.parse(state);
    }
    return state;
  }

  return { navigate: wrappedNavigate, location, getLocationState };
}
