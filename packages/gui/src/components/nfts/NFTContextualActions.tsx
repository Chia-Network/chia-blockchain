import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import type { NFTInfo } from '@chia/api';
import { AlertDialog, DropdownActions, useOpenDialog } from '@chia/core';
import type { DropdownActionsChildProps } from '@chia/core';
import { Offers as OffersIcon } from '@chia/icons';
import { ListItemIcon, MenuItem, Typography } from '@mui/material';
import { ArrowForward as TransferIcon } from '@mui/icons-material';
import NFTCreateOfferDemoDialog from './NFTCreateOfferDemo';
import { NFTTransferDialog, NFTTransferResult } from './NFTTransferAction';
import NFTSelection from '../../types/NFTSelection';

/* ========================================================================== */
/*                          Common Action Types/Enums                         */
/* ========================================================================== */

enum NFTContextualActionTypes {
  CreateOffer = 1 << 0, // 1
  Transfer = 1 << 1, // 2
}

type NFTContextualActionProps = {
  onClose: () => void;
  selection?: NFTSelection;
};

/* ========================================================================== */
/*                             Create Offer Action                            */
/* ========================================================================== */

type NFTCreateOfferContextualActionProps = NFTContextualActionProps;

function NFTCreateOfferContextualAction(
  props: NFTCreateOfferContextualActionProps,
) {
  const { onClose, selection } = props;
  const openDialog = useOpenDialog();
  const selectedNft: NFTInfo | undefined = selection?.items[0];
  const disabled = (selection?.items.length ?? 0) !== 1;

  function handleCreateOffer() {
    if (!selectedNft) {
      throw new Error('No NFT selected');
    }

    openDialog(
      <NFTCreateOfferDemoDialog
        nft={selectedNft}
        referrerPath={location.hash.split('#').slice(-1)[0]}
      />,
    );
  }

  return (
    <MenuItem
      onClick={() => {
        onClose();
        handleCreateOffer();
      }}
      disabled={disabled}
    >
      <ListItemIcon>
        <OffersIcon />
      </ListItemIcon>
      <Typography variant="inherit" noWrap>
        <Trans>Create Offer</Trans>
      </Typography>
    </MenuItem>
  );
}

/* ========================================================================== */
/*                             Transfer NFT Action                            */
/* ========================================================================== */

type NFTTransferContextualActionProps = NFTContextualActionProps;

function NFTTransferContextualAction(props: NFTTransferContextualActionProps) {
  const { onClose, selection } = props;
  const openDialog = useOpenDialog();
  const selectedNft: NFTInfo | undefined = selection?.items[0];
  const disabled = (selection?.items.length ?? 0) !== 1;

  function handleComplete(result?: NFTTransferResult) {
    if (result) {
      if (result.success) {
        openDialog(
          <AlertDialog title={<Trans>NFT Transfer Complete</Trans>}>
            <Trans>
              The NFT transfer transaction has been successfully submitted to
              the blockchain.
            </Trans>
          </AlertDialog>,
        );
      } else {
        const error = result.error || 'Unknown error';
        openDialog(
          <AlertDialog title={<Trans>NFT Transfer Failed</Trans>}>
            <Trans>The NFT transfer failed: {error}</Trans>
          </AlertDialog>,
        );
      }
    }
  }

  function handleTransferNFT() {
    openDialog(
      <NFTTransferDialog nft={selectedNft} onComplete={handleComplete} />,
    );
  }

  return (
    <MenuItem
      onClick={() => {
        onClose();
        handleTransferNFT();
      }}
      disabled={disabled}
    >
      <ListItemIcon>
        <TransferIcon />
      </ListItemIcon>
      <Typography variant="inherit" noWrap>
        <Trans>Transfer NFT</Trans>
      </Typography>
    </MenuItem>
  );
}

/* ========================================================================== */
/*                             Contextual Actions                             */
/* ========================================================================== */

type NFTContextualActionsProps = {
  selection?: NFTSelection;
  availableActions: NFTContextualActionTypes;
};

export default function NFTContextualActions(props: NFTContextualActionsProps) {
  const { selection, availableActions } = props;

  const actions = useMemo(() => {
    const actionComponents = {
      [NFTContextualActionTypes.CreateOffer]: NFTCreateOfferContextualAction,
      [NFTContextualActionTypes.Transfer]: NFTTransferContextualAction,
    };

    return Object.keys(NFTContextualActionTypes)
      .map(Number)
      .filter(Number.isInteger)
      .filter((key) => actionComponents.hasOwnProperty(key))
      .filter((key) => availableActions & key)
      .map((key) => actionComponents[key]);
  }, [availableActions]);

  return (
    <DropdownActions label={<Trans>Actions</Trans>} variant="outlined">
      {({ onClose }: DropdownActionsChildProps) => (
        <>
          {actions.map((Action) => (
            <Action onClose={onClose} selection={selection} />
          ))}
        </>
      )}
    </DropdownActions>
  );
}

NFTContextualActions.defaultProps = {
  selection: undefined,
  availableActions:
    NFTContextualActionTypes.CreateOffer | NFTContextualActionTypes.Transfer,
};
