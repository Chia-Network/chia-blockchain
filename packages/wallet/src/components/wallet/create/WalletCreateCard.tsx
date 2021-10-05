import React, { ReactNode } from 'react';
import { Card, Flex } from '@chia/core';
import { Typography } from '@material-ui/core';
import styled from 'styled-components';

const StyledCardBody = styled(Flex)`
  min-height: 200px;
`;

type Props = {
  title: ReactNode;
  children: ReactNode;
  onSelect?: () => void;
  icon: ReactNode;
  disabled?: boolean;
  description?: string;
};

export default function WalletCreateCard(props: Props) {
  const { title, children, icon, onSelect, disabled, description } = props;

  return (
    <Card onSelect={onSelect} disabled={disabled} fullHeight>
      <StyledCardBody flexDirection="column" gap={3}>
        <Flex flexDirection="column" gap={2} flexGrow={1} alignItems="center" justifyContent="center">
          {icon}
          <Typography variant="h6">
            {title}
          </Typography>
        </Flex>
        <Typography variant="body2" color="textSecondary">
          {children}
        </Typography>
      </StyledCardBody>
      <Typography variant="caption" align="center">
        {description}
      </Typography>
    </Card>
  );
}
