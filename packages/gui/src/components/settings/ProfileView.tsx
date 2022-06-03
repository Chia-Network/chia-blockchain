import React, { useState, useEffect } from 'react';
import { Trans } from '@lingui/macro';
import {
  Flex,
  Suspender,
  Truncate,
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
  useSetDIDNameMutation,
} from '@chia/api-react';

const StyledCard = styled(Card)(({ theme }) => `
  width: 100%;
  padding: ${theme.spacing(3)};
  border-radius: ${theme.spacing(1)};
  background-color: ${theme.palette.background.paper};
`);

const InlineEdit = ({ text, walletId }) => {
  const [editedText, setEditedText] = useState(text);
  const [setDid, { isLoading: isSetDidLoading }] = useSetDIDNameMutation();

  useEffect(() => {
    setEditedText(text);
  }, [text]);

  const handleChange = (event) => setEditedText(event.target.value);

  const handleKeyDown = (event) => {
    if (event.key === "Enter" || event.key === "Escape") {
      event.target.blur();
    }
  }

  const handleBlur = (event) => {
    if (event.target.value.trim() === "") {
      setEditedText(text);
    } else {
      setDid({ walletId: walletId, name: event.target.value});
    }
  }

  return (
    <input
      type="text"
      style={{
          width: "100%",
          paddingLeft: "8px",
          paddingTop: "6px",
          paddingBottom: "6px",
          fontSize: "20px",
          fontWeight: "bold",
        }}
      value={editedText || ''}
      onChange={handleChange}
      onKeyDown={handleKeyDown}
      onBlur={handleBlur}
    />
  );
};

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
            <InlineEdit text={nameText} walletId={walletId}/>
          </Flex>
          <Flex flexDirection="row" paddingBottom={1}>
            <Flex flexGrow={1}>
              <Trans>My DID</Trans>
            </Flex>
            <Flex>
              <Truncate tooltip copyToClipboard>{myDidText}</Truncate>
            </Flex>
          </Flex>
          <Flex flexDirection="row" paddingBottom={1}>
            <Flex flexGrow={1}>
              <Trans>Token Standard</Trans>
            </Flex>
            <Flex>
              DID1
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
