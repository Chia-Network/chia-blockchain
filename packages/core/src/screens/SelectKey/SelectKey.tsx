import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import styled from 'styled-components';
import { Alert, Typography, Container } from '@mui/material';
import { useNavigate } from 'react-router';
import {
  useGetKeyringStatusQuery,
  useDeleteAllKeysMutation,
  useLogInAndSkipImportMutation,
  useGetKeysQuery,
} from '@chia/api-react';
import type { KeyData } from '@chia/api';
import SelectKeyItem from './SelectKeyItem';
import Button from '../../components/Button';
import Flex from '../../components/Flex';
import Logo from '../../components/Logo';
import Loading from '../../components/Loading';
import TooltipIcon from '../../components/TooltipIcon';
import ConfirmDialog from '../../components/ConfirmDialog';
import useOpenDialog from '../../hooks/useOpenDialog';
import useShowError from '../../hooks/useShowError';
import useSkipMigration from '../../hooks/useSkipMigration';
import useKeyringMigrationPrompt from '../../hooks/useKeyringMigrationPrompt';

const StyledContainer = styled(Container)`
  padding-bottom: 1rem;
`;

export default function SelectKey() {
  const openDialog = useOpenDialog();
  const navigate = useNavigate();
  const [deleteAllKeys] = useDeleteAllKeysMutation();
  const [logIn, { isLoading: isLoadingLogIn }] =
    useLogInAndSkipImportMutation();
  const {
    data: publicKeyFingerprints,
    isLoading: isLoadingPublicKeys,
    error,
    refetch,
  } = useGetKeysQuery();
  const { data: keyringState, isLoading: isLoadingKeyringStatus } =
    useGetKeyringStatusQuery();
  const hasFingerprints = !!publicKeyFingerprints?.length;
  const [selectedFingerprint, setSelectedFingerprint] = useState<
    number | undefined
  >();

  const [skippedMigration] = useSkipMigration();
  const [promptForKeyringMigration] = useKeyringMigrationPrompt();
  const showError = useShowError();

  const isLoading = isLoadingPublicKeys || isLoadingLogIn;

  async function handleSelect(fingerprint: number) {
    if (selectedFingerprint) {
      return;
    }

    try {
      setSelectedFingerprint(fingerprint);
      await logIn({
        fingerprint,
      }).unwrap();

      navigate('/dashboard/wallets');
    } catch (error) {
      showError(error);
    } finally {
      setSelectedFingerprint(undefined);
    }
  }

  async function handleDeleteAllKeys() {
    const canModifyKeyring = await handleKeyringMutator();

    if (!canModifyKeyring) {
      return;
    }

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
      </ConfirmDialog>
    );
  }

  async function handleKeyringMutator(): Promise<boolean> {
    // If the keyring requires migration and the user previously skipped migration, prompt again
    if (
      isLoadingKeyringStatus ||
      (keyringState?.needsMigration && skippedMigration)
    ) {
      await promptForKeyringMigration();

      return false;
    }

    return true;
  }

  async function handleNavigationIfKeyringIsMutable(url: string) {
    const canModifyKeyring = await handleKeyringMutator();

    if (canModifyKeyring) {
      navigate(url);
    }
  }

  return (
    <StyledContainer maxWidth="xs">
      <Flex flexDirection="column" alignItems="center" gap={3}>
        <Logo width={130} />
        {isLoadingPublicKeys ? (
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
            <TooltipIcon>{error.message}</TooltipIcon>
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
            <Typography variant="subtitle1" align="center">
              <Trans>
                Welcome to Chia. Please log in with an existing key, or create a
                new key.
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
            <Flex gap={2} flexDirection="column" width="100%">
              {publicKeyFingerprints.map((keyData: KeyData, index: number) => (
                <SelectKeyItem
                  key={keyData.fingerprint}
                  index={index}
                  keyData={keyData}
                  onSelect={handleSelect}
                  loading={keyData.fingerprint === selectedFingerprint}
                  disabled={
                    !!selectedFingerprint &&
                    keyData.fingerprint !== selectedFingerprint
                  }
                />
              ))}
            </Flex>
          )}
          <Button
            onClick={() => handleNavigationIfKeyringIsMutable('/wallet/add')}
            variant="contained"
            color="primary"
            size="large"
            disabled={isLoading}
            data-testid="SelectKey-create-new-key"
            fullWidth
          >
            <Trans>Create a new private key</Trans>
          </Button>
          <Button
            onClick={() => handleNavigationIfKeyringIsMutable('/wallet/import')}
            type="submit"
            variant="outlined"
            size="large"
            disabled={isLoading}
            data-testid="SelectKey-import-from-mnemonics"
            fullWidth
          >
            <Trans>Import from Mnemonics (24 words)</Trans>
          </Button>
          <Button
            onClick={handleDeleteAllKeys}
            variant="outlined"
            color="danger"
            size="large"
            disabled={isLoading}
            data-testid="SelectKey-delete-all-keys"
            fullWidth
          >
            <Trans>Delete all keys</Trans>
          </Button>
        </Flex>
      </Flex>
    </StyledContainer>
  );
}
