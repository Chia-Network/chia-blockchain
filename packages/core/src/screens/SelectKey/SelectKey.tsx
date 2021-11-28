import React from 'react';
import { Trans } from '@lingui/macro';
import styled from 'styled-components';
import { Button, ConfirmDialog, Flex, Logo, Loading, useOpenDialog, TooltipIcon } from '@chia/core';
import {
  Card,
  Typography,
  Container,
  List,
} from '@material-ui/core';
import { Alert, AlertTitle } from '@material-ui/lab';
import {
  useGetPublicKeysQuery,
  useDeleteAllKeysMutation,
  useGetStateQuery,
} from '@chia/api-react';
import LayoutHero from '../../components/LayoutHero';
import SelectKeyItem from './SelectKeyItem';

const StyledContainer = styled(Container)`
  padding-bottom: 1rem;
`;

export default function SelectKey() {
  const openDialog = useOpenDialog();
  const [deleteAllKeys] = useDeleteAllKeysMutation();
  const { data: publicKeyFingerprints, isLoading, error, refetch } = useGetPublicKeysQuery();
  const hasFingerprints = !!publicKeyFingerprints?.length;
  
  async function handleDeleteAllKeys() {
    await openDialog(
      <ConfirmDialog
        title={<Trans>Delete all keys</Trans>}
        confirmTitle={<Trans>Delete</Trans>}
        cancelTitle={<Trans>Back</Trans>}
        confirmColor="danger"
        onConfirm={() => deleteAllKeys().unwrap()}
      >
        <Trans>
          Deleting all keys will permanently remove the keys from your computer,
          make sure you have backups. Are you sure you want to continue?
        </Trans>
      </ConfirmDialog>,
    );
  }

  return (
    <LayoutHero>
      <StyledContainer maxWidth="xs">
        <Flex flexDirection="column" alignItems="center" gap={3}>
          <Logo width={130} />
          {isLoading ? (
            <Loading center>
              <Trans>Loading list of the keys</Trans>
            </Loading>
          ) : error ? (
            <Alert 
              severity="error"
              action={
                <Button onClick={refetch} color="inherit" size="small">
                  <Trans>Try Again</Trans>
                </Button>
              }
            >
              <Trans>Unable to load the list of the keys</Trans>
              &nbsp;
              <TooltipIcon>
                {error.message}
              </TooltipIcon>
            </Alert>
          ) : hasFingerprints ? (
            <Typography variant="h5" component="h1">
              <Trans>Select Key</Trans>
            </Typography>
          ) : (
            <>
              <Typography variant="h5" component="h1">
                <Trans>Sign In</Trans>
              </Typography>
              <Typography variant="subtitle1">
                <Trans>
                  Welcome to Chia. Please log in with an existing key, or create
                  a new key.
                </Trans>
              </Typography>
            </>
          )}
          <Flex
            flexDirection="column"
            gap={3}
            alignItems="stretch"
            alignSelf="stretch"
          >
            {hasFingerprints && (
              <Card>
                <List>
                  {publicKeyFingerprints.map((fingerprint: number) => (
                    <SelectKeyItem
                      key={fingerprint}
                      fingerprint={fingerprint} 
                    />
                  ))}
                </List>
              </Card>
            )}
            <Button
              to="/wallet/add"
              variant="contained"
              color="primary"
              size="large"
              fullWidth
            >
              <Trans>Create a new private key</Trans>
            </Button>
            <Button
              to="/wallet/import"
              type="submit"
              variant="outlined"
              size="large"
              fullWidth
            >
              <Trans>Import from Mnemonics (24 words)</Trans>
            </Button>
            <Button
              onClick={handleDeleteAllKeys}
              variant="outlined"
              color="danger"
              size="large"
              fullWidth
            >
              <Trans>Delete all keys</Trans>
            </Button>
          </Flex>
        </Flex>
      </StyledContainer>
    </LayoutHero>
  );
}
