import React from 'react';
import { useRouteMatch, useHistory } from 'react-router-dom';
import { Trans } from '@lingui/macro';
import { Grid } from '@material-ui/core';
import { Add as AddIcon } from '@material-ui/icons';
import { Back, Flex, Loading } from '@chia/core';
import { useDispatch, useSelector } from 'react-redux';
import WalletCreateCard from '../create/WalletCreateCard';
import { createCATWalletFromToken } from '../../../modules/message';
import Tokens from '../../../constants/Tokens';
import useShowError from '../../../hooks/useShowError';
import isCATWalletPresent from '../../../util/isCATWalletPresent';
import type { RootState } from '../../../modules/rootReducer';
import type CATToken from '../../../types/CATToken';

export default function WalletCATCreateSimple() {
  const history = useHistory();
  const dispatch = useDispatch();
  const { url } = useRouteMatch();
  const showError = useShowError();
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);
  const isLoading = !wallets;

  function handleCreateExisting() {
    history.push(`/dashboard/wallets/create/cat/existing`);
  }

  async function handleCreateNewToken(token: CATToken) {
    try {
      const walletId = await dispatch(createCATWalletFromToken(token));
      history.push(`/dashboard/wallets/${walletId}`);
    } catch (error) {
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
            <Grid xs={12} sm={6} md={4} item>
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