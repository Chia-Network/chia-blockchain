import React, { useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { Trans, t } from '@lingui/macro';
import { NFTInfo } from '@chia/api';
import type { Wallet } from '@chia/api';
import {
  useGetDIDsQuery,
  useGetNFTWallets,
  useSetNFTDIDMutation,
} from '@chia/api-react';
import {
  AlertDialog,
  Button,
  ButtonLoading,
  ConfirmDialog,
  CopyToClipboard,
  DropdownActions,
  DropdownActionsProps,
  Fee,
  Flex,
  Form,
  TooltipIcon,
  MenuItem,
  chiaToMojo,
  truncateValue,
  useOpenDialog,
  useShowError,
} from '@chia/core';
import { PermIdentity as PermIdentityIcon } from '@mui/icons-material';
import {
  Box,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  ListItemIcon,
  Typography,
} from '@mui/material';
import { stripHexPrefix } from '../../util/utils';
import { didFromDIDId, didToDIDId } from '../../util/dids';
import NFTSummary from './NFTSummary';
import styled from 'styled-components';

/* ========================================================================== */

const StyledValue = styled(Box)`
  word-break: break-all;
`;

/* ========================================================================== */
/*                     Move to Profile Confirmation Dialog                    */
/* ========================================================================== */

type NFTMoveToProfileConfirmationDialogProps = {};

function NFTMoveToProfileConfirmationDialog(
  props: NFTMoveToProfileConfirmationDialogProps,
) {
  const { ...rest } = props;

  return (
    <ConfirmDialog
      title={<Trans>Confirm Move</Trans>}
      confirmTitle={<Trans>Yes, move</Trans>}
      confirmColor="secondary"
      cancelTitle={<Trans>Cancel</Trans>}
      {...rest}
    >
      <Flex flexDirection="column" gap={3}>
        <Typography variant="body1">
          <Trans>
            Are you sure you want to move this NFT to the specified profile?
          </Trans>
        </Typography>
      </Flex>
    </ConfirmDialog>
  );
}

/* ========================================================================== */
/*                            DID Profile Dropdown                            */
/* ========================================================================== */

type DIDProfileDropdownProps = DropdownActionsProps & {
  walletId?: number;
  onChange?: (walletId?: number) => void;
  defaultTitle?: string | React.ReactElement;
  currentDID?: string;
  includeNoneOption?: boolean;
};

export function DIDProfileDropdown(props: DIDProfileDropdownProps) {
  const {
    walletId,
    onChange,
    defaultTitle = t`All Profiles`,
    currentDID = '',
    includeNoneOption = false,
    ...rest
  } = props;
  const { data: allDIDWallets, isLoading } = useGetDIDsQuery();

  const didWallets = useMemo(() => {
    if (!allDIDWallets) {
      return [];
    }

    const excludeDIDs: string[] = [];
    if (currentDID) {
      const did = didFromDIDId(currentDID);
      if (did) {
        excludeDIDs.push(did);
      }
    }

    return allDIDWallets.filter(
      (wallet: Wallet) => !excludeDIDs.includes(wallet.myDid),
    );
  }, [allDIDWallets, currentDID]);

  const label = useMemo(() => {
    if (isLoading) {
      return t`Loading...`;
    }

    const wallet = didWallets?.find((wallet: Wallet) => wallet.id === walletId);

    return wallet?.name || defaultTitle;
  }, [defaultTitle, didWallets, isLoading, walletId]);

  function handleWalletChange(newWalletId?: number) {
    onChange?.(newWalletId);
  }

  return (
    <DropdownActions
      onSelect={handleWalletChange}
      label={label}
      variant="text"
      color="secondary"
      size="large"
      {...rest}
    >
      {(didWallets ?? []).map((wallet: Wallet, index: number) => (
        <MenuItem
          key={wallet.id}
          onClick={() => handleWalletChange(wallet.id)}
          selected={wallet.id === walletId}
          divider={index === didWallets?.length - 1 && includeNoneOption}
          close
        >
          <ListItemIcon>
            <PermIdentityIcon />
          </ListItemIcon>
          {wallet.name}
        </MenuItem>
      ))}
      {includeNoneOption && (
        <MenuItem
          key={'<none>'}
          onClick={() => handleWalletChange()}
          selected={!walletId && !currentDID}
          close
        >
          <ListItemIcon>
            <PermIdentityIcon />
          </ListItemIcon>
          <Trans>None</Trans>
        </MenuItem>
      )}
    </DropdownActions>
  );
}

/* ========================================================================== */
/*                         NFT Move to Profile Action                         */
/* ========================================================================== */

type NFTMoveToProfileFormData = {
  destination: string;
  fee: string;
};

type NFTMoveToProfileActionProps = {
  nft: NFTInfo;
  destination?: string;
  onComplete?: () => void;
};

export function NFTMoveToProfileAction(props: NFTMoveToProfileActionProps) {
  const { nft, destination: defaultDestination, onComplete } = props;
  const [isLoading, setIsLoading] = useState(false);
  const [setNFTDID] = useSetNFTDIDMutation();
  const openDialog = useOpenDialog();
  const errorDialog = useShowError();
  const methods = useForm<NFTMoveToProfileFormData>({
    shouldUnregister: false,
    defaultValues: {
      destination: defaultDestination || '',
      fee: '',
    },
  });
  const destination = methods.watch('destination');
  const { data: didWallets, isLoading: isLoadingDIDs } = useGetDIDsQuery();
  const { wallets: nftWallets, isLoading: isLoadingNFTWallets } =
    useGetNFTWallets();
  const currentDIDId = nft.ownerDid
    ? didToDIDId(stripHexPrefix(nft.ownerDid))
    : undefined;

  const inbox: Wallet | undefined = useMemo(() => {
    if (isLoadingDIDs || isLoadingNFTWallets) {
      return undefined;
    }

    const nftWalletIds: number[] = nftWallets.map(
      (nftWallet: Wallet) => nftWallet.walletId,
    );
    const didWalletIds = new Set(
      didWallets.map((wallet: Wallet) => wallet.nftWalletId),
    );
    const inboxWalletId = nftWalletIds.find(
      (nftWalletId) => !didWalletIds.has(nftWalletId),
    );
    return nftWallets.find(
      (wallet: Wallet) => wallet.walletId === inboxWalletId,
    );
  }, [didWallets, nftWallets, isLoadingDIDs, isLoadingNFTWallets]);

  const currentDID = useMemo(() => {
    if (!didWallets || !currentDIDId) {
      return undefined;
    }

    return didWallets.find((wallet: Wallet) => wallet.myDid === currentDIDId);
  }, [didWallets, currentDIDId]);

  const newDID = destination
    ? didWallets.find((wallet: Wallet) => wallet.myDid === destination)
    : undefined;

  let newProfileName = undefined;
  if (newDID) {
    newProfileName = newDID.name;

    if (!newProfileName) {
      newProfileName = truncateValue(newDID.myDid, {});
    }
  } else if (destination === '<none>') {
    newProfileName = t`None`;
  }

  function handleProfileSelected(walletId?: number) {
    if (!walletId) {
      methods.setValue('destination', '<none>');
    } else {
      const selectedWallet = didWallets.find(
        (wallet: Wallet) => wallet.id === walletId,
      );
      methods.setValue('destination', selectedWallet?.myDid || '');
    }
  }

  async function handleClose() {
    if (onComplete) {
      onComplete();
    }
  }

  async function handleSubmit(formData: NFTMoveToProfileFormData) {
    const { destination, fee } = formData;
    const feeInMojos = chiaToMojo(fee || 0);
    let isValid = true;

    if (!destination || destination === currentDIDId) {
      errorDialog(new Error(t`Please select a profile to move the NFT to.`));
      isValid = false;
    }

    if (!isValid) {
      return;
    }

    const destinationDID = destination === '<none>' ? undefined : destination;

    const confirmation = await openDialog(
      <NFTMoveToProfileConfirmationDialog />,
    );

    if (confirmation) {
      try {
        setIsLoading(true);

        const { error, data: response } = await setNFTDID({
          walletId: nft.walletId,
          nftLauncherId: stripHexPrefix(nft.launcherId),
          nftCoinId: stripHexPrefix(nft.nftCoinId),
          did: destinationDID,
          fee: feeInMojos,
        });
        const success = response?.success ?? false;
        const errorMessage = error ?? undefined;

        if (success) {
          openDialog(
            <AlertDialog title={<Trans>NFT Move Pending</Trans>}>
              <Trans>
                The NFT move transaction has been successfully submitted to the
                blockchain.
              </Trans>
            </AlertDialog>,
          );
        } else {
          const error = errorMessage || 'Unknown error';
          openDialog(
            <AlertDialog title={<Trans>NFT Move Failed</Trans>}>
              <Trans>The NFT move failed: {error}</Trans>
            </AlertDialog>,
          );
        }
      } finally {
        setIsLoading(false);

        if (onComplete) {
          onComplete();
        }
      }
    }
  }

  return (
    <Form methods={methods} onSubmit={handleSubmit}>
      <Flex flexDirection="column" gap={3}>
        <Flex flexDirection="column" gap={1}>
          <NFTSummary launcherId={nft.launcherId} />
        </Flex>
        <Flex
          sx={{
            overflow: 'hidden',
            wordBreak: 'break-all',
            textOverflow: 'ellipsis',
          }}
        >
          <DIDProfileDropdown
            walletId={currentDID ? currentDID.id : undefined}
            onChange={handleProfileSelected}
            defaultTitle={<Trans>Select Profile</Trans>}
            currentDID={currentDIDId}
            includeNoneOption={
              inbox !== undefined && currentDIDId !== undefined
            }
            variant="outlined"
            color="primary"
            disabled={isLoading || isLoadingDIDs || isLoadingNFTWallets}
          />
        </Flex>
        <Flex flexDirection="column" gap={2}>
          <Flex flexDirection="row" alignItems="center" gap={1}>
            <Flex>
              <Typography variant="body1" color="textSecondary" noWrap>
                Current Profile:
              </Typography>
            </Flex>
            <Flex
              flexShrink={1}
              sx={{
                overflow: 'hidden',
                wordBreak: 'break-all',
                textOverflow: 'ellipsis',
              }}
            >
              <Typography variant="body1" noWrap>
                {currentDID ? (
                  currentDID.name ? (
                    currentDID.name
                  ) : (
                    currentDID.myDid
                  )
                ) : currentDIDId ? (
                  currentDIDId
                ) : (
                  <Trans>None</Trans>
                )}
              </Typography>
            </Flex>
            {currentDIDId && (
              <TooltipIcon>
                <Flex alignItems="center" gap={1}>
                  <StyledValue>{currentDIDId}</StyledValue>
                  <CopyToClipboard
                    value={currentDIDId}
                    fontSize="small"
                    invertColor
                  />
                </Flex>
              </TooltipIcon>
            )}
          </Flex>
          {newProfileName && (
            <Flex flexDirection="row" alignItems="center" gap={1}>
              <Flex>
                <Typography variant="body1" color="textSecondary" noWrap>
                  New Profile:
                </Typography>
              </Flex>
              <Flex
                flexShrink={1}
                sx={{
                  overflow: 'hidden',
                  wordBreak: 'break-all',
                  textOverflow: 'ellipsis',
                }}
              >
                <Typography variant="body1" noWrap>
                  {newProfileName}
                </Typography>
              </Flex>
              {newDID && (
                <TooltipIcon>
                  <Flex alignItems="center" gap={1}>
                    <StyledValue>{newDID.myDid}</StyledValue>
                    <CopyToClipboard
                      value={newDID.myDid}
                      fontSize="small"
                      invertColor
                    />
                  </Flex>
                </TooltipIcon>
              )}
            </Flex>
          )}
        </Flex>
        <Fee
          id="filled-secondary"
          variant="filled"
          name="fee"
          color="secondary"
          label={<Trans>Fee</Trans>}
          disabled={isLoading}
        />
        <DialogActions>
          <Flex flexDirection="row" gap={3}>
            <Button
              onClick={handleClose}
              color="secondary"
              variant="outlined"
              autoFocus
            >
              <Trans>Close</Trans>
            </Button>
            <ButtonLoading
              type="submit"
              autoFocus
              color="primary"
              variant="contained"
              loading={isLoading}
            >
              <Trans>Move</Trans>
            </ButtonLoading>
          </Flex>
        </DialogActions>
      </Flex>
    </Form>
  );
}

/* ========================================================================== */
/*                         NFT Move to Profile Dialog                         */
/* ========================================================================== */

type NFTMoveToProfileDialogProps = {
  open: boolean;
  onClose: (value: any) => void;
  nft: NFTInfo;
  destination?: string;
};

export default function NFTMoveToProfileDialog(
  props: NFTMoveToProfileDialogProps,
) {
  const { open, onClose, nft, destination, ...rest } = props;

  function handleClose() {
    onClose(false);
  }

  function handleCompletion() {
    onClose(true);
  }

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      aria-labelledby="nft-move-dialog-title"
      aria-describedby="nft-move-dialog-description"
      maxWidth="sm"
      fullWidth
      {...rest}
    >
      <DialogTitle id="nft-move-dialog-title">
        <Flex flexDirection="row" gap={1}>
          <Typography variant="h6">
            <Trans>Move NFT to Profile</Trans>
          </Typography>
        </Flex>
      </DialogTitle>
      <DialogContent>
        <Flex flexDirection="column" gap={3}>
          <DialogContentText id="nft-move-dialog-description">
            <Trans>
              Would you like to move the specified NFT to a profile?
            </Trans>
          </DialogContentText>
          <NFTMoveToProfileAction
            nft={nft}
            destination={destination}
            onComplete={handleCompletion}
          />
        </Flex>
      </DialogContent>
    </Dialog>
  );
}
