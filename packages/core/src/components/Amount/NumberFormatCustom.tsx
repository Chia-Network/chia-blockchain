import React, { forwardRef } from 'react';
import NumberFormat from 'react-number-format';

interface NumberFormatCustomProps {
  onChange: (event: { target: { name: string; value: string } }) => void;
  name: string;
}

function NumberFormatCustom(props: NumberFormatCustomProps, ref: any) {
  const { onChange, ...other } = props;

  function handleChange(values: any) {
    onChange(values.value);
  }

  return (
    <NumberFormat
      {...other}
      getInputRef={ref}
      onValueChange={handleChange}
      thousandSeparator
      allowNegative={false}
      isNumericString
    />
  );
}

export default forwardRef(NumberFormatCustom);
