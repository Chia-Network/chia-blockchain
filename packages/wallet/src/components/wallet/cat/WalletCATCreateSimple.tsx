import React from 'react';
import { useRouteMatch, useHistory } from 'react-router-dom';
import { Trans, t } from '@lingui/macro';
import { Grid } from '@material-ui/core';
import { Add as AddIcon } from '@material-ui/icons';
import { Back, Flex, Loading, useShowError } from '@chia/core';
import { useGetWalletsQuery, useAddCATTokenMutation } from '@chia/api-react';
import WalletCreateCard from '../create/WalletCreateCard';
import Tokens from '../../../constants/Tokens';
import isCATWalletPresent from '../../../util/isCATWalletPresent';
import type CATToken from '../../../types/CATToken';

export default function WalletCATCreateSimple() {
  const history = useHistory();
  const { url } = useRouteMatch();
  const showError = useShowError();
  const { data: wallets, isLoading } = useGetWalletsQuery();
  const [addCATToken, { isLoading: isAddCATTokenLoading }] = useAddCATTokenMutation();
  
  function handleCreateExisting() {
    history.push(`/dashboard/wallets/create/cat/existing`);
  }

  async function handleCreateNewToken(token: CATToken) {
    if (isAddCATTokenLoading) {
      return;
    }

    try {
      console.log('token', token);
      const { name, tail } = token;

      if (!name) {
        throw new Error(t`Token has empty name`);
      }
    
      if (!tail) {
        throw new Error(t`Token has empty tail`);
      }

      console.log('creating cat', tail, name);
      const walletId = await addCATToken({
        tail,
        name,
        fee: '0',
      }).unwrap();

      console.log('createCATWalletForExisting response', walletId);

      history.push(`/dashboard/wallets/${walletId}`);
    } catch(error: any) {
      console.log('error', error);
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
      <Grid spacing={3} alignItems="stretch" container>
        {Tokens.map((token) => {
          const isPresent = isCATWalletPresent(wallets, token);

          function handleSelect() {
            if (!isPresent) {
              handleCreateNewToken(token);
            }
          }

          return (
            <Grid key={token.tail} xs={12} sm={6} md={4} item>
              <WalletCreateCard
                key={token.symbol}
                onSelect={handleSelect}
                title={token.name}
                symbol={token.symbol}
                disabled={isPresent}
                description={token.description}
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
    </Flex>
  );
}