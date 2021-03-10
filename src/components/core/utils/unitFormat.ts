import Unit from '../constants/Unit';
import CurrencyCode from '../constants/CurrencyCode';

type Options = {
  from?: Unit;
  to?: Unit;
  currencyCode?: boolean;
};

const defaultOptions = {
  to: Unit.CHIA,
  from: Unit.CHIA,
};

export default function unitFormat(value: number, options: Options): string {
  const { to, currencyCode } = {
    ...defaultOptions,
    ...options,
  };

  const updatedValue = value;

  if (currencyCode) {
    // @ts-ignore
    const code = CurrencyCode[to];
    if (!code) {
      throw new Error(`Currency code is not defined for ${to}`);
    }

    return `${updatedValue} ${code}`;
  }

  return String(updatedValue);
}
