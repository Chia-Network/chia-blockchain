import React from 'react';
import { Trans } from '@lingui/macro';
import {
  CopyToClipboard,
  Flex,
  Suspender,
} from '@chia/core';
import {
  Card,
  Typography,
} from '@mui/material';
import styled from 'styled-components';
import { useParams } from 'react-router-dom';
import {
  useGetDIDQuery,
  useGetDIDNameQuery,
} from '@chia/api-react';

const StyledCard = styled(Card)(({ theme }) => `
  width: 100%;
  padding: ${theme.spacing(3)};
  border-radius: ${theme.spacing(1)};
  background-color: ${theme.palette.background.paper};
`);

export default function ProfileView() {
  const { walletId } = useParams();
  const { data: did, isLoading } = useGetDIDQuery({ walletId: walletId });
  const { data: didName, loading } = useGetDIDNameQuery({ walletId: walletId });
  let myDidText: JSX.Element | null = null;
  let nameText: JSX.Element | null = null;

  if (isLoading || loading) {
    return (
      <Suspender />
    );
  }

  if (did && didName) {
    const nameText = didName.name;
    const myDidText = did.myDid;

    return (
      <div style={{width:"100%"}}>
        <StyledCard>
          <Flex flexDirection="column" gap={2.5} paddingBottom={3}>
            <Typography variant="h6">
              <Trans><strong>{nameText}</strong></Trans>
            </Typography>
          </Flex>
          <Flex flexDirection="row" paddingBottom={1}>
            <Flex flexGrow={1}>
              <Trans>My DID</Trans>
            </Flex>
            <Flex>
              <Trans>{myDidText}</Trans>
              <CopyToClipboard value={myDidText} fontSize="small"/>
            </Flex>
          </Flex>
          <Flex flexDirection="row" paddingBottom={1}>
            <Flex flexGrow={1}>
              <Trans>Token Standard</Trans>
            </Flex>
            <Flex>
              <Trans>DID1</Trans>
            </Flex>
          </Flex>
        </StyledCard>
      </div>
    );
  } else {
    return (
      null
    )
  }
}
