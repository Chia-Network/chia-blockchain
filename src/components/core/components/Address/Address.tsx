import React from 'react';
import toBech32m from '../../../../util/toBech32m';
import useCurrencyCode from '../../../../hooks/useCurrencyCode';
import Tooltip from '../Tooltip';

type Props = {
  value: string;
  copyToClipboard?: boolean;
  tooltip?: boolean;
  children?: (address: string) => JSX.Element;
};

export default function Address(props: Props) {
  const { value, copyToClipboard, tooltip, children } = props;

  const currencyCode = useCurrencyCode();
  const address = currencyCode 
    ? toBech32m(value, currencyCode.toLowerCase())
    : '';

  if (!children) {
    return address;
  }

  if (tooltip) {
    return (
      <Tooltip title={address} copyToClipboard={copyToClipboard}>
        {children(address)}
      </Tooltip>
    );
  }

  return children(address);
}

Address.defaultProps = {
  copyToClipboard: false,
  tooltip: false,
};