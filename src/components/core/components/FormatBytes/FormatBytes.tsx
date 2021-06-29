import React from 'react';
import bytes from 'bytes-iec';
import FormatLargeNumber from '../FormatLargeNumber';

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
  const {
    value,
    mode,
    precision,
    unit,
    unitSeparator,
    removeUnit,
    fixedDecimals,
  } = props;
  const humanValue = bytes(value, {
    unit,
    mode,
    decimalPlaces: precision,
    unitSeparator,
    fixedDecimals,
  });

  if (humanValue === null) {
    return <>{humanValue}</>;
  }

  const [justValue, unitValue] = humanValue.split(unitSeparator);
  if (humanValue && removeUnit && unitSeparator) {
    return <FormatLargeNumber value={justValue} />;
  }

  return (
    <>
      <FormatLargeNumber value={justValue} />
      {unitSeparator}
      {unitValue}
    </>
  );
}

FormatBytes.defaultProps = {
  unit: undefined,
  mode: 'binary',
  precision: 1,
  unitSeparator: ' ',
  removeUnit: false,
  fixedDecimals: false,
};
