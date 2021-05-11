import React from 'react';
import { Tooltip } from '@material-ui/core';

import useLocale from '../../../../hooks/useLocale';
import { defaultLocale } from '../../../../config/locales';

const LARGE_NUMBER_THRESHOLD = 1000;

type Props = {
  value: number;
};

export default function FormatLargeNumber(props: Props) {
  const { value } = props;
  const [locale] = useLocale(defaultLocale);

  if (value < LARGE_NUMBER_THRESHOLD) {
    return value;
  }

  return (
    <Tooltip title={value}>
      <span>
        {new Intl.NumberFormat(locale, {
          maximumFractionDigits: 1,
          minimumFractionDigits: 1,
          notation: 'compact',
        }).format(value)}
      </span>
    </Tooltip>
  );
}
