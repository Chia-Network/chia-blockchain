import React, { useEffect } from 'react';
import { Trans, t } from '@lingui/macro';
import {
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  Alert,
  Typography,
} from '@mui/material';
import { useForm } from 'react-hook-form';
import {
  useCheckDeleteKeyMutation,
  useDeleteKeyMutation,
  useGetKeyringStatusQuery,
} from '@chia/api-react';
import useSkipMigration from '../../hooks/useSkipMigration';
import useKeyringMigrationPrompt from '../../hooks/useKeyringMigrationPrompt';
import Flex from '../../components/Flex';
import Loading from '../../components/Loading';
import Form from '../../components/Form';
import TextField from '../../components/TextField';
import ButtonLoading from '../../components/ButtonLoading';
import DialogActions from '../../components/DialogActions';

type FormData = {
  fingerprint: string;
};

export type WalletDeleteDialogProps = {
  fingerprint: number;
  open?: boolean;
  onClose?: () => void;
};

export default function WalletDeleteDialog(props: WalletDeleteDialogProps) {
  const { fingerprint, onClose = () => ({}), open = false } = props;

  const { data: keyringState, isLoading: isLoadingKeyringStatus } =
    useGetKeyringStatusQuery();

  const [deleteKey] = useDeleteKeyMutation();
  const [checkDeleteKey, { data: checkDeleteKeyData }] =
    useCheckDeleteKeyMutation();
  const [skippedMigration] = useSkipMigration();
  const [promptForKeyringMigration] = useKeyringMigrationPrompt();

  const methods = useForm<FormData>({
    defaultValues: {
      fingerprint: '',
    },
  });

  const { isSubmitting } = methods.formState;

  async function handleKeyringMutator() {
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

  async function initialize() {
    const canModifyKeyring = await handleKeyringMutator();
    if (!canModifyKeyring) {
      onClose();
      return;
    }

    await checkDeleteKey({
      fingerprint,
    });
  }

  useEffect(() => {
    initialize();
  }, []);

  const isInitializing = !checkDeleteKeyData;
  const canSubmit = !isInitializing && !isSubmitting;

  const { usedForFarmerRewards, walletBalance, usedForPoolRewards } =
    checkDeleteKeyData ?? {};
  const hasWarning =
    usedForFarmerRewards || walletBalance || usedForPoolRewards;

  async function handleSubmit(values: FormData) {
    if (values.fingerprint !== fingerprint.toString()) {
      throw new Error(t`Fingerprint does not match`);
    }

    await deleteKey({ fingerprint }).unwrap();

    onClose?.();
  }

  function handleCancel() {
    onClose?.();
  }

  return (
    <Dialog open={open} onClose={onClose}>
      <Form methods={methods} onSubmit={handleSubmit}>
        <DialogTitle>
          <Trans>Delete key {fingerprint}</Trans>
        </DialogTitle>
        <DialogContent>
          {isInitializing ? (
            <Loading center />
          ) : (
            <>
              <Flex flexDirection="column" gap={2}>
                {hasWarning && (
                  <Alert severity="warning">
                    <Flex flexDirection="column" gap={1}>
                      {usedForFarmerRewards && (
                        <Typography>
                          <Trans>
                            This key is used for your farming rewards address.
                            By deleting this key you may lose access to any
                            future farming rewards
                          </Trans>
                        </Typography>
                      )}

                      {usedForPoolRewards && (
                        <Typography>
                          <Trans>
                            This key is used for your pool rewards address. By
                            deleting this key you may lose access to any future
                            pool rewards
                          </Trans>
                        </Typography>
                      )}

                      {walletBalance && (
                        <Typography>
                          <Trans>
                            This key is used for a wallet that may have a
                            non-zero balance. By deleting this key you may lose
                            access to this wallet
                          </Trans>
                        </Typography>
                      )}
                    </Flex>
                  </Alert>
                )}

                <Flex flexDirection="column" gap={2}>
                  <Typography>
                    <Trans>
                      This will permanently remove the key from your computer,
                      make sure you have your mnemonic phrase backed up.
                    </Trans>
                  </Typography>
                  <Typography>
                    <Trans>
                      Are you sure you want to continue? Type in the fingerprint
                      of this wallet key to confirm deletion.
                    </Trans>
                  </Typography>

                  <TextField
                    name="fingerprint"
                    label={<Trans>Wallet Fingerprint</Trans>}
                    autoFocus
                    fullWidth
                  />
                </Flex>
              </Flex>
            </>
          )}
        </DialogContent>
        <DialogActions>
          <Button variant="outlined" onClick={handleCancel} color="secondary">
            <Trans>Back</Trans>
          </Button>
          <ButtonLoading
            type="submit"
            variant="contained"
            color="danger"
            disabled={!canSubmit}
            loading={isSubmitting}
            autoFocus
          >
            <Trans>Delete</Trans>
          </ButtonLoading>
        </DialogActions>
      </Form>
    </Dialog>
  );
}
