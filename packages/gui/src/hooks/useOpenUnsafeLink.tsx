import React from 'react';
import { Trans } from '@lingui/macro';
import { useLocalStorage } from '@rehooks/local-storage';
import {
  ConfirmDialog,
  CopyToClipboard,
  Flex,
  useOpenDialog,
  useOpenExternal,
} from '@chia/core';
import {
  Checkbox,
  FormControlLabel,
  InputAdornment,
  TextField,
  Typography,
} from '@mui/material';

/* ========================================================================== */

const SuppressUnsafeLinkWarningLocalStorageKey = 'suppressUnsafeLinkWarning';

/* ========================================================================== */

type OpenUnsafeLinkConfirmationDialogProps = {
  url: string;
};

function OpenUnsafeLinkConfirmationDialog(
  props: OpenUnsafeLinkConfirmationDialogProps,
) {
  const { url, ...rest } = props;
  const [suppressUnsafeLinkWarning, setSuppressUnsafeLinkWarning] =
    useLocalStorage<boolean>(SuppressUnsafeLinkWarningLocalStorageKey, false);

  function toggleSuppression(value: boolean) {
    setSuppressUnsafeLinkWarning(value);
  }

  return (
    <ConfirmDialog
      title={<Trans>Warning: You're about to visit a website</Trans>}
      confirmTitle={<Trans>Open Link</Trans>}
      confirmColor="primary"
      cancelTitle={<Trans>Cancel</Trans>}
      {...rest}
    >
      <Flex flexDirection="column" gap={2}>
        <Typography>
          <Trans>
            Please check the following link to verify the site you are going to
            visit. Proceed at your own risk.
          </Trans>
        </Typography>
        <TextField
          label={<Trans>URL</Trans>}
          value={url}
          variant="filled"
          InputProps={{
            readOnly: true,
            endAdornment: (
              <InputAdornment position="end">
                <CopyToClipboard value={url} />
              </InputAdornment>
            ),
          }}
          fullWidth
        />
        <FormControlLabel
          control={
            <Checkbox
              name="suppressUnsafeLinkWarning"
              checked={!!suppressUnsafeLinkWarning}
              onChange={(event) => toggleSuppression(event.target.checked)}
            />
          }
          label={<Trans>Do not show this dialog again</Trans>}
        />
      </Flex>
    </ConfirmDialog>
  );
}

/* ========================================================================== */

export default function useOpenUnsafeLink() {
  const openDialog = useOpenDialog();
  const openExternal = useOpenExternal();
  const [suppressUnsafeLinkWarning] = useLocalStorage<boolean>(
    SuppressUnsafeLinkWarningLocalStorageKey,
    false,
  );

  async function openUnsafeLink(url: string) {
    let openUrl = false;

    if (suppressUnsafeLinkWarning) {
      openUrl = true;
    } else {
      openUrl = await openDialog(
        <OpenUnsafeLinkConfirmationDialog url={url} />,
      );
    }

    if (openUrl) {
      openExternal(url);
    }
  }

  return openUnsafeLink;
}
