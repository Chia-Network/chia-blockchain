import React, { ReactNode } from 'react';
import { Typography, IconButton } from '@mui/material';
import { Trans } from '@lingui/macro';
import { ArrowBackIosNew } from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import { useFormContext } from 'react-hook-form';
import useOpenDialog from '../../hooks/useOpenDialog';
import Flex from '../Flex';
import ConfirmDialog from '../ConfirmDialog';

export type BackProps = {
  children?: ReactNode;
  goBack?: boolean;
  to?: string;
  variant?: string;
  form?: boolean;
  iconStyle?: any;
};

export default function Back(props: BackProps) {
  const { children, variant, to, goBack, form = false, iconStyle } = props;
  const navigate = useNavigate();
  const openDialog = useOpenDialog();
  const formContext = useFormContext();

  const isDirty = formContext?.formState?.isDirty;

  async function handleGoBack() {
    if (form) {
      const canGoBack =
        !isDirty ||
        (await openDialog<boolean>(
          <ConfirmDialog
            title={<Trans>Unsaved Changes</Trans>}
            confirmTitle={<Trans>Discard</Trans>}
            confirmColor="danger"
          >
            <Trans>You have made changes. Do you want to discard them?</Trans>
          </ConfirmDialog>,
        ));

      if (!canGoBack) {
        return;
      }
    }

    if (goBack) {
      navigate(-1);
      return;
    }

    if (to) {
      navigate(to);
    }
  }

  return (
    <Flex gap={1} alignItems="center">
      <IconButton onClick={handleGoBack} sx={iconStyle}>
        <ArrowBackIosNew />
      </IconButton>

      <Typography variant={variant}>{children}</Typography>
    </Flex>
  );
}

Back.defaultProps = {
  children: undefined,
  variant: "body2",
  goBack: true,
  to: undefined,
};
