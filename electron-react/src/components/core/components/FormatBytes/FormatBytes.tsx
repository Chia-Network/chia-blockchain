import React from 'react';
import bytes from 'bytes-iec';

type Props = {
  value: number;
  unit: FormatOptions['unit'];
  mode: FormatOptions['mode'];
  unitSeparator: string;
  precision?: number;
  removeUnit?: boolean;
  fixedDecimals?: boolean;
};

export default function FormatBytes(props: Props) {
  const { value, mode, precision, unit, unitSeparator, removeUnit, fixedDecimals } = props;
  const humanValue = bytes(value, {
    unit,
    mode, 
    decimalPlaces: precision,
    unitSeparator,
    fixedDecimals,
  });

  if (humanValue && removeUnit && unitSeparator) {
    const [justValue] = humanValue.split(unitSeparator);
    return <>{justValue}</>;
  }

  return <>{humanValue}</>;
}

FormatBytes.defaultProps = {
  unit: undefined,
  mode: 'binary',
  precision: 1,
  unitSeparator: ' ',
  removeUnit: false,
  fixedDecimals: false,
};
