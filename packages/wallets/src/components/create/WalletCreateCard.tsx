import React, { useState, ReactNode } from 'react';
import { Card, Flex, Loading } from '@chia/core';
import { Typography } from '@mui/material';
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
  loadingDescription?: ReactNode;
  symbol?: string;
};

export default function WalletCreateCard(props: Props) {
  const { title, children, icon, onSelect, disabled, description, symbol, loadingDescription } = props;
  const [loading, setLoading] = useState<boolean>(false);

  async function handleSelect() {
    if (!onSelect || loading) {
      return;
    }

    try {
      setLoading(true);
      await onSelect();
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card onSelect={handleSelect} disabled={disabled} fullHeight>
      <StyledCardBody flexDirection="column" gap={3}>
        <Flex flexDirection="column" gap={1} flexGrow={1} alignItems="center" justifyContent="center">
          {icon}
          {loading ? (
            <Loading center>
              {loadingDescription}
            </Loading>
          ) : (
            <>
              {symbol && (
              <Typography variant="h5" color="primary">
                {symbol}
              </Typography>
            )}
            <Typography variant="h6">
              {title}
            </Typography>
            </>
          )}

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
