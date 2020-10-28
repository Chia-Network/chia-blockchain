import React from 'react';
// @ts-ignore
import byteSize from 'byte-size';

type Props = {
  value: number,
  units?: string,
};

export default function FormatBytes(props: Props): JSX.Element {
  const { value, units } = props;
  const { value: humanValue, unit } = byteSize(value, { units });

  return (
    <>
      {`${humanValue} ${unit}`}
    </>
  );
}

FormatBytes.defaultProps = {
  units: 'iec',
};
