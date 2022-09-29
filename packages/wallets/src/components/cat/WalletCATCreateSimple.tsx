import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Trans, t } from '@lingui/macro';
import { Grid } from '@mui/material';
import { Add as AddIcon } from '@mui/icons-material';
import { Back, Flex, Loading, useShowError } from '@chia/core';
import { useGetWalletsQuery, useAddCATTokenMutation, useGetCatListQuery } from '@chia/api-react';
import WalletCreateCard from '../create/WalletCreateCard';
import isCATWalletPresent from '../../utils/isCATWalletPresent';
import type { CATToken } from '@chia/api';
import useWalletState from '../../hooks/useWalletState';
import { SyncingStatus } from '@chia/api';

export default function WalletCATCreateSimple() {
  const navigate = useNavigate();
  const showError = useShowError();
  const { data: wallets, isWalletsLoading } = useGetWalletsQuery();
  const [addCATToken, { isLoading: isAddCATTokenLoading }] = useAddCATTokenMutation();
  const { data: catList, isCatListLoading } = useGetCatListQuery();
  const { state } = useWalletState();

  const isLoading = isWalletsLoading || isCatListLoading;

  function handleCreateExisting() {
    navigate(`/dashboard/wallets/create/cat/existing`);
  }

  async function handleCreateNewToken(token: CATToken) {
    try {
      const { name, assetId } = token;

      if (isAddCATTokenLoading) {
        return;
      }

      if (state !== SyncingStatus.SYNCED) {
        throw new Error(t`Please wait for wallet synchronization`);
      }

      if (!name) {
        throw new Error(t`Token has empty name`);
      }

      if (!assetId) {
        throw new Error(t`Token has empty asset id`);
      }

      const walletId = await addCATToken({
        assetId,
        name,
        fee: '0',
      }).unwrap();

      navigate(`/dashboard/wallets/${walletId}`);
    } catch(error: any) {
      showError(error);
    }
  }

  if (isLoading) {
    return (
      <Loading center />
    );
  }

  return (
    <Flex flexDirection="column" gap={3}>
      <Flex flexGrow={1}>
        <Back variant="h5" to="/dashboard/wallets">
          <Trans>Add Token</Trans>
        </Back>
      </Flex>
      {isLoading ? (
        <Loading center />
      ) : (
        <Grid spacing={3} alignItems="stretch" container>
          {catList?.map((token) => {
            const isPresent = isCATWalletPresent(wallets, token);

            async function handleSelect() {
              if (!isPresent) {
                await handleCreateNewToken(token);
              }
            }

            return (
              <Grid key={token.assetId} xs={12} sm={6} md={4} item>
                <WalletCreateCard
                  key={token.symbol}
                  onSelect={handleSelect}
                  title={token.name}
                  symbol={token.symbol}
                  disabled={isPresent}
                  loadingDescription={<Trans>Adding {token.symbol} token</Trans>}
                />
              </Grid>
            );
          })}
          <Grid xs={12} sm={6} md={4} item>
            <WalletCreateCard
              onSelect={() => handleCreateExisting()}
              title={<Trans>Custom</Trans>}
              icon={<AddIcon fontSize="large" color="primary" />}
            />
          </Grid>
        </Grid>
      )}
    </Flex>
  );
}
