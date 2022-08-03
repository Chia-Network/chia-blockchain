import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { orderBy } from 'lodash';
import { useNavigate, useParams } from 'react-router';
import { Box, Typography, Button } from '@mui/material';
import {
  Flex,
  CardListItem,
  useOpenDialog,
  Link,
  useColorModeValue,
  useOpenExternal,
  FormatLargeNumber,
} from '@chia/core';
import {
  useGetLoggedInFingerprintQuery,
  useGetPrivateKeyQuery,
  useGetWalletsQuery,
} from '@chia/api-react';
import { WalletType } from '@chia/api';
import styled from 'styled-components';
import WalletIcon from './WalletIcon';
import getWalletPrimaryTitle from '../utils/getWalletPrimaryTitle';
import WalletsManageTokens from './WalletsManageTokens';
import useHiddenWallet from '../hooks/useHiddenWallet';
import WalletEmptyDialog from './WalletEmptyDialog';

const StyledRoot = styled(Box)`
  min-width: 390px;
  height: 100%;
  display: flex;
  padding-top: ${({ theme }) => `${theme.spacing(3)}`};
`;

const StyledContent = styled(Box)`
  padding-left: ${({ theme }) => theme.spacing(3)};
  padding-right: ${({ theme }) => theme.spacing(3)};
  margin-right: ${({ theme }) => theme.spacing(2)};
  min-height: ${({ theme }) => theme.spacing(5)};
  overflow-y: overlay;
`;

const StyledBody = styled(Box)`
  flex-grow: 1;
  position: relative;
`;

const TokensInfo = styled.div`
  float: right;
  border: ${({ theme }) => `1px solid ${useColorModeValue(theme, 'border')}`};
  height: 30px;
  padding: 0px 5px;
  border-radius: 5px;
  cursor: pointer;
`;

const StyledItemsContainer = styled(Flex)`
  flex-direction: column;
  height: 100%;
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  padding-bottom: ${({ theme }) => theme.spacing(6)};
`;

const ContentStyled = styled.div`
  max-width: 500px;
  text-align: center;
  padding: 5px 20px;
`;

const ActionsStyled = styled.div`
  margin: 25px;
  display: inline-block;
`;

export default function WalletsSidebar() {
  const navigate = useNavigate();
  const { walletId } = useParams();
  const { data: wallets, isLoading } = useGetWalletsQuery();
  const {
    isHidden,
    hidden,
    isLoading: isLoadingHiddenWallet,
  } = useHiddenWallet();

  const openDialog = useOpenDialog();

  const openExternal = useOpenExternal();

  const { data: fingerprint, isLoading: isLoadingFingerprint } =
    useGetLoggedInFingerprintQuery();

  const { data: privateKey, isLoading: isLoadingPrivateKey } =
    useGetPrivateKeyQuery(
      {
        fingerprint,
      },
      {
        skip: !fingerprint,
      }
    );

  function handleOpenBlogPost() {
    openExternal('https://www.chia.net/cat2blog');
  }

  function openTokensInfoDialog() {
    openDialog(
      <WalletEmptyDialog>
        <ContentStyled>
          <Typography variant="h5" textAlign="center" color="grey">
            <Trans>Your CAT tokens have been upgraded!</Trans>
          </Typography>
          <br />
          <Typography textAlign="center" color="grey">
            <Trans>
              We've made an upgrade to the CAT standard which requires all CATs
              to be re-issued. You will be airdropped your new tokens as they
              are re-issued by the original issuers. The airdropped tokens will
              be based on the balance as of block height:
              <br />
              <FormatLargeNumber value={2311760} />
              <br />
              (Approximate time: July 26th, 2022 @ 17:00 UTC)
            </Trans>
          </Typography>
          <ActionsStyled>
            <Flex gap={3} flexDirection="column" width="100%">
              <Button
                variant="outlined"
                size="large"
                onClick={() =>
                  openExternal(
                    'https://cat1.chia.net/#publicKey=' +
                      privateKey.pk +
                      '&fingerprint=' +
                      fingerprint
                  )
                }
                disabled={isLoadingFingerprint || isLoadingPrivateKey}
              >
                <Trans>Check my snapshot balance</Trans>
              </Button>
              <Button
                variant="outlined"
                size="large"
                onClick={handleOpenBlogPost}
              >
                <Trans>Read the blog post for details</Trans>
              </Button>
            </Flex>
          </ActionsStyled>
          <p>
            <Trans>Want to see your old balance for yourself?</Trans>
          </p>
          <Link target="_blank" href="https://www.chia.net/download/">
            <Trans>Click here to download an older version of the wallet</Trans>
          </Link>
        </ContentStyled>
      </WalletEmptyDialog>
    );
  }

  function handleSelectWallet(walletId: number) {
    navigate(`/dashboard/wallets/${walletId}`);
  }

  const items = useMemo(() => {
    if (isLoading || isLoadingHiddenWallet) {
      return [];
    }

    const orderedWallets = orderBy(wallets, ['type', 'name'], ['asc', 'asc']);

    return orderedWallets
      .filter(
        wallet =>
          [WalletType.STANDARD_WALLET, WalletType.CAT].includes(wallet.type) &&
          !isHidden(wallet.id)
      )
      .map(wallet => {
        const primaryTitle = getWalletPrimaryTitle(wallet);

        function handleSelect() {
          handleSelectWallet(wallet.id);
        }

        return (
          <CardListItem
            onSelect={handleSelect}
            key={wallet.id}
            selected={wallet.id === Number(walletId)}
          >
            <Flex flexDirection="column">
              <Typography>{primaryTitle}</Typography>
              <WalletIcon
                wallet={wallet}
                color="textSecondary"
                variant="caption"
              />
            </Flex>
          </CardListItem>
        );
      });
  }, [wallets, walletId, isLoading, hidden, isLoadingHiddenWallet]);

  return (
    <StyledRoot>
      <Flex gap={3} flexDirection="column" width="100%">
        <StyledContent>
          <Typography variant="h5">
            <Trans>Tokens</Trans>
            <TokensInfo onClick={() => openTokensInfoDialog()}>
              <svg
                width="20"
                height="20"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
              >
                <path
                  d="M9 5h2v2H9V5Zm0 4h2v6H9V9Zm1-9C4.48 0 0 4.48 0 10s4.48 10 10 10 10-4.48 10-10S15.52 0 10 0Zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8Z"
                  fill="currentColor"
                  fillOpacity={0.54}
                  stroke="transparent"
                />
              </svg>
            </TokensInfo>
          </Typography>
        </StyledContent>
        <StyledBody>
          <StyledItemsContainer>
            <StyledContent>
              <Flex gap={1} flexDirection="column">
                {items}
              </Flex>
            </StyledContent>
          </StyledItemsContainer>
          <WalletsManageTokens />
        </StyledBody>
      </Flex>
    </StyledRoot>
  );
}
