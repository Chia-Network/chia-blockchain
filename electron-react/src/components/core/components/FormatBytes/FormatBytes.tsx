import React from 'react';
// @ts-ignore
import byteSize from 'byte-size';

type Props = {
  value: number;
  units?: string;
  precision?: number;
};

export default function FormatBytes(props: Props): JSX.Element {
  const { value, units, precision } = props;
  const { value: humanValue, unit } = byteSize(value, { units, precision });

  return <>{`${humanValue} ${unit}`}</>;
}

FormatBytes.defaultProps = {
  units: 'iec',
  precision: 1,
};
