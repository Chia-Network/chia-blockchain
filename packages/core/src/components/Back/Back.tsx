import React, { ReactNode } from 'react';
import { Typography } from '@mui/material';
import { Trans } from '@lingui/macro';
import { ArrowBackIos as ArrowBackIosIcon } from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import styled from 'styled-components';
import { useFormContext } from 'react-hook-form';
import useOpenDialog from '../../hooks/useOpenDialog';
import Flex from '../Flex';
import ConfirmDialog from '../ConfirmDialog';

const BackIcon = styled(ArrowBackIosIcon)`
  cursor: pointer;
`;

export type BackProps = {
  children?: ReactNode;
  goBack?: boolean;
  to?: string;
  variant?: string;
  fontSize?: string;
  form?: boolean;
};

export default function Back(props: BackProps) {
  const { children, variant, to, goBack, fontSize, form = false } = props;
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
      <BackIcon onClick={handleGoBack} fontSize={fontSize} />
      <Typography variant={variant}>{children}</Typography>
    </Flex>
  );
}

Back.defaultProps = {
  children: undefined,
  variant: "body2",
  goBack: true,
  to: undefined,
  fontSize: "medium",
};
