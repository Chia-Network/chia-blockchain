import React, { useMemo } from 'react';
import BigNumber from 'bignumber.js';
// import { Tooltip } from '@mui/material';
import useLocale from '../../hooks/useLocale';
import bigNumberToLocaleString from '../../utils/bigNumberToLocaleString';

// const LARGE_NUMBER_THRESHOLD = 1000;

type Props = {
  value?: string | number | BigInt | BigNumber;
};

// TODO add ability to use it in new settings page
/*
const compactConfig = {
  maximumFractionDigits: 1,
  minimumFractionDigits: 1,
  notation: 'compact',
};
*/

export default function FormatLargeNumber(props: Props) {
  const { value } = props;
  const [locale] = useLocale();

  const numberFormat = useMemo(() => new Intl.NumberFormat(locale), [locale]);
  const formatedValue = useMemo(() => {
    if (typeof value === 'undefined' || value === null) {
      return value;
    } else if (value instanceof BigNumber) {
      return bigNumberToLocaleString(value, locale);
    } else if (typeof value === 'bigint') {
      return BigInt(value).toLocaleString(locale);
    }

    return numberFormat.format(value);
  }, [value, numberFormat]);

  return <span>{formatedValue}</span>;
}
