import { transform } from 'lodash';
import BigNumber from 'bignumber.js';

export default function toSafeNumber(object: Object): Object {
  return transform(object, (acc, value, key) => {
    if (value instanceof BigNumber && value.isInteger() && value.isLessThanOrEqualTo(Number.MAX_SAFE_INTEGER)) {
      acc[key] = value.toNumber();
    } else {
      acc[key] = value;
    }
  });
}
