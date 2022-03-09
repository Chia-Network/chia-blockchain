import React from 'react';
import BigNumber from 'bignumber.js';

const Convert: [BigNumber, string][] = [
  [new BigNumber(0), 'B'],
  [new BigNumber(1024).exponentiatedBy(1), 'KiB'],
  [new BigNumber(1024).exponentiatedBy(2), 'MiB'],
  [new BigNumber(1024).exponentiatedBy(3), 'GiB'],
  [new BigNumber(1024).exponentiatedBy(4), 'TiB'],
  [new BigNumber(1024).exponentiatedBy(5), 'PiB'],
  [new BigNumber(1024).exponentiatedBy(6), 'EiB'],
  [new BigNumber(1024).exponentiatedBy(7), 'ZiB'],
  [new BigNumber(1024).exponentiatedBy(8), 'YiB'],
];

const CovertReversed = Convert.slice().reverse();

type Props = {
  value: number;
  unit?: 'B' | 'KiB' | 'MiB' | 'GiB' | 'TiB' | 'PiB' | 'EiB' | 'ZiB' | 'YiB';
  unitSeparator?: string;
  precision?: number;
  removeUnit?: boolean;
  fixedDecimals?: boolean;
};

export default function FormatBytes(props: Props) {
  const {
    value,
    precision,
    unit,
    removeUnit,
    unitSeparator = ' ',
    fixedDecimals,
  } = props;

  if (value === null || value === undefined) {
    return null;
  }

  const bigValue = new BigNumber(value);
  const isNegative = bigValue.isNegative();
  const absValue = isNegative ? bigValue.abs() : bigValue;

  let humanValue;
  let humanUnit;

  if (unit) {
    const unitIndex = Convert.findIndex(item => item[1].toLowerCase() === unit.toLowerCase());
    const [unitValue, unitName] = Convert[unitIndex];

    humanValue = bigValue.dividedBy(unitValue);
    humanUnit = unitName;
  } else {
    // convert value to nearest bytes representation
    const unitIndex = Math.min(CovertReversed.length -1, CovertReversed.findIndex(item => absValue.isGreaterThanOrEqualTo(item[0])));
    const [unitValue, unitName] = CovertReversed[unitIndex];

    humanValue = !unitValue.isZero() 
      ? bigValue.dividedBy(unitValue) 
      : bigValue;
    humanUnit = unitName;
  }

  if (fixedDecimals) {
    humanValue = humanValue.decimalPlaces(precision ?? 2);
  }

  if (precision || fixedDecimals) {
    humanValue = humanValue.toFixed(precision ?? 2);
  } else {
    humanValue = humanValue.toString();
  }

  if (removeUnit) {
    return humanValue;
  }

  return (
    <>
      {humanValue}
      {unitSeparator}
      {humanUnit}
    </>
  );
}
