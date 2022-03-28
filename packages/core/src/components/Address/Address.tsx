import React from 'react';
import { Box } from '@mui/material';
import styled from 'styled-components';
import toBech32m from '../../utils/toBech32m';
import useCurrencyCode from '../../hooks/useCurrencyCode';
import Tooltip from '../Tooltip';
import CopyToClipboard from '../CopyToClipboard';
import Flex from '../Flex';

const StyledValue = styled(Box)`
  word-break: break-all;
`;

type Props = {
  value: string;
  copyToClipboard?: boolean;
  tooltip?: boolean;
  children?: (address: string) => JSX.Element;
};

export default function Address(props: Props) {
  const { value, copyToClipboard, tooltip, children } = props;

  const currencyCode = useCurrencyCode();
  const address =
    currencyCode && value ? toBech32m(value, currencyCode.toLowerCase()) : '';

  if (!children) {
    if (copyToClipboard) {
      return (
        <Flex alignItems="center" gap={1}>
          <StyledValue>{address}</StyledValue>
          <CopyToClipboard value={address} fontSize="small" />
        </Flex>
      );
    }

    return address;
  }

  if (tooltip) {
    return (
      <Tooltip title={address} copyToClipboard={copyToClipboard}>
        {children(address)}
      </Tooltip>
    );
  }

  if (copyToClipboard) {
    return (
      <Flex alignItems="center" gap={1}>
        {children(address)} asdf
        <CopyToClipboard value={address} fontSize="small" />
      </Flex>
    );
  }

  return children(address);
}

Address.defaultProps = {
  copyToClipboard: false,
  tooltip: false,
};
