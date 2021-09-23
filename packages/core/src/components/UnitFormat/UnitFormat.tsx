import React from 'react';
import useCurrencyCode from '../../hooks/useCurrencyCode';
import State from '../../constants/State';
import StateTypography from '../StateTypography';

type Props = {
  value: number;
  variant?: string;
  state?: State;
};

export default function UnitFormat(props: Props) {
  const { value, variant, state, ...rest } = props;
  const currencyCode = useCurrencyCode();

  return (
    <StateTypography variant={variant} state={state} {...rest}>
      {`${value} ${currencyCode}`}
    </StateTypography>
  );
}

UnitFormat.defaultProps = {
  variant: 'body1',
};
