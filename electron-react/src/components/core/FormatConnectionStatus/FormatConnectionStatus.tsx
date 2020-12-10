import React, { ReactNode } from 'react';
import styled from 'styled-components';
import { Trans } from '@lingui/macro';
import { Typography, TypographyProps } from '@material-ui/core';
import { FiberManualRecord as FiberManualRecordIcon } from '@material-ui/icons';
import { Flex } from '@chia/core';

function getIconSize(size: string): string {
  switch (size) {
    case 'lg':
      return '1.5rem';
    case 'sm':
      return '0.8rem';
    case 'xs':
      return '0.5rem';
    default:
      return '1rem';
  }
}

const StyledFiberManualRecordIcon = styled(({ iconSize, ...rest }) => (
  <FiberManualRecordIcon {...rest} />
))`
  font-size: ${({ iconSize }) => getIconSize(iconSize)};
`;

type Props = {
  connected: boolean;
  connectedTitle?: ReactNode;
  notConnectedTitle?: ReactNode;
  variant?: TypographyProps['variant'];
  iconSize?: 'lg' | 'normal' | 'sm' | 'xs';
};

export default function FormatConnectionStatus(props: Props) {
  const {
    connected,
    connectedTitle,
    notConnectedTitle,
    variant,
    iconSize,
  } = props;
  const color = connected ? 'primary' : 'secondary';

  return (
    <Flex alignItems="center" gap={1}>
      <Typography variant={variant} color={color}>
        {connected ? connectedTitle : notConnectedTitle}
      </Typography>
      <StyledFiberManualRecordIcon color={color} iconSize={iconSize} />
    </Flex>
  );
}

FormatConnectionStatus.defaultProps = {
  connectedTitle: (
    <Trans id="FormatConnectionStatus.connected">Connected</Trans>
  ),
  notConnectedTitle: (
    <Trans id="FormatConnectionStatus.notConnected">Not connected</Trans>
  ),
  variant: 'caption',
  iconSize: 'sm',
};
