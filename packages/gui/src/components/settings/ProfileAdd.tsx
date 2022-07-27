import React from 'react';
import { Trans, t } from '@lingui/macro';
import {
  ButtonLoading,
  chiaToMojo,
  Fee,
  Flex,
  Form,
  mojoToChiaLocaleString,
} from '@chia/core';
import {
  Card,
  Typography,
} from '@mui/material';
import styled from 'styled-components';
import {
  useCreateNewWalletMutation,
  useGetWalletBalanceQuery,
} from '@chia/api-react';
import { useForm } from 'react-hook-form';
import { useNavigate } from 'react-router';
import useOpenExternal from '../../hooks/useOpenExternal';
import isNumeric from 'validator/es/lib/isNumeric';

const StyledCard = styled(Card)(({ theme }) => `
  width: 100%;
  padding: ${theme.spacing(3)};
  border-radius: ${theme.spacing(1)};
  background-color: ${theme.palette.background.paper};
`);

type CreateProfileData = {
  backup_dids: [],
  num_of_backup_ids_needed: '0',
  amount: int;
  fee: string;
};

export default function ProfileAdd() {
  const methods = useForm<CreateProfileData>({
    defaultValues: {
      backup_dids: [],
      num_of_backup_ids_needed: '0',
      amount: 1,
      fee: '',
    },
  });

  const [createProfile, { isLoading: isCreateProfileLoading }] = useCreateNewWalletMutation();
  const { data: balance } = useGetWalletBalanceQuery({
    walletId: 1,
  });
  const navigate = useNavigate();
  const openExternal = useOpenExternal();

  function handleClick() {
    openExternal('https://faucet.chia.net/');
  }

  async function handleSubmit(data: CreateProfileData) {

    const fee = data.fee.trim() || '0';
    if (!isNumeric(fee)) {
      throw new Error(t`Please enter a valid numeric fee`);
    }

    if (isCreateProfileLoading) {
      return;
    }

    const walletId = await createProfile({
      walletType: 'did_wallet',
      options: {did_type: 'new', backup_dids: [], num_of_backup_ids_needed: '0', amount: 1, fee: chiaToMojo(fee)},
    }).unwrap();

    navigate(`/dashboard/settings/profiles/${walletId}`);
  }

  const standardBalance = mojoToChiaLocaleString(balance?.confirmedWalletBalance);

  return (
    <div style={{width:"70%"}}>
      <Form methods={methods} onSubmit={handleSubmit}>
        <Flex flexDirection="column" gap={2.5} paddingBottom={3}>
          <Typography variant="h6">
            <Trans>Create a new profile</Trans>
          </Typography>
        </Flex>
        <StyledCard>
          <Flex flexDirection="column" gap={2.5} paddingBottom={1}>
            <Trans><strong>Need some XCH?</strong></Trans>
          </Flex>
          <div style={{cursor: "pointer"}}>
            <Flex paddingBottom={5}>
              <Typography onClick={handleClick} sx={{ textDecoration: "underline" }}>Get Mojos from the Chia Faucet</Typography>
            </Flex>
          </div>
          <Flex flexDirection="column" gap={2.5} paddingBottom={1}>
            <Trans><strong>Use one (1) mojo to create a Profile.</strong></Trans>
          </Flex>
          <Flex flexDirection="column" gap={2.5} paddingBottom={3}>
            <Typography variant="caption">
              <Trans>Balance: {standardBalance} XCH</Trans>
            </Typography>
          </Flex>
          <Flex flexDirection="column" gap={2.5} paddingBottom={1}>
            <Fee
              id="filled-secondary"
              variant="filled"
              name="fee"
              color="secondary"
              label={<Trans>Fee</Trans>}
              fullWidth
            />
          </Flex>
          <Flex flexDirection="column" gap={2.5} paddingBottom={3}>
            <Typography variant="caption">
              <Trans>Recommended: 0.000005 XCH</Trans>
            </Typography>
          </Flex>
          <Flex justifyContent="flex-end">
            <ButtonLoading
              type="submit"
              variant="contained"
              color="primary"
              loading={isCreateProfileLoading}
            >
              <Trans>Create</Trans>
            </ButtonLoading>
          </Flex>
        </StyledCard>
      </Form>
    </div>
  );
}
