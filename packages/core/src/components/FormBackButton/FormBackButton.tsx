import React, { ReactNode } from 'react';
import { Trans } from '@lingui/macro';
import { useNavigate } from 'react-router';
import { useFormContext } from 'react-hook-form';
import useOpenDialog from '../../hooks/useOpenDialog';
import Button from '../Button';
import ConfirmDialog from '../ConfirmDialog';

type Props = {
  children?: ReactNode;
};

export default function FormBackButton(props: Props) {
  const { children, ...rest } = props;
  const openDialog = useOpenDialog();
  const { formState } = useFormContext();
  const navigate = useNavigate();

  const { isDirty } = formState;

  async function handleBack() {
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

    if (canGoBack) {
      navigate(-1);
    }
  }

  return (
    <Button onClick={handleBack} {...rest}>
      {children}
    </Button>
  );
}

FormBackButton.defaultProps = {
  children: <Trans>Back</Trans>,
};
