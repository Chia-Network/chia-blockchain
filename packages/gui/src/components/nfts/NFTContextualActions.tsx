import React, { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
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
  // TODO: Remove these when we have a way to view offers
  DemoViewOfferImported = 1 << 2, // 4
  DemoViewOfferMyOffer = 1 << 3, // 8
  DemoViewOfferCompleted = 1 << 4, // 16
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
/*                     Demo Action - View Offer (Imported)                    */
/* ========================================================================== */

type NFTDemoViewOfferImportedContextualActionProps = NFTContextualActionProps;

function NFTDemoViewOfferImportedContextualAction(
  props: NFTDemoViewOfferImportedContextualActionProps,
) {
  const { onClose, selection } = props;
  const navigate = useNavigate();
  const selectedNft: NFTInfo | undefined = selection?.items[0];
  const disabled = (selection?.items.length ?? 0) !== 1;

  function handleViewOffer() {
    const tradeRecord = undefined;
    const offerData =
      'offer1qqp83w76wzru6cmqvpsxygqqama36ngn6fhxtlen3xthnqm0s83gfww3vu3ld0vat8yt6ukl6tlwnhpswkcxq8dduarwhww30fhtf8sm4hnsdw57qvthkzu2acw5s6hhh9e8n4vwfy9jdfr493ww02xdequ5xnmultpg9dfhhthaeqf24dvxhd8zuj4cyna4c5hsmu505nha4drvvw6gr3h53x86hd4afp2p9ksg94zy066w0ztcuyfzk0qylacvkwnucyt7eklm8fsa2lwtnzhpalp0nv4z8l2xal50489m37n3zegvnyvj6ddqkgswx8l044eqr5750ch3u7fhr2uu4at0rnxha3azsazmz7vzdxzlzzssce9pkrmcv8c0yuj5mxxsmethez78wljutvc2c2lvr0jdel045hp6c8j0nu8wmyh77slxevh54xwzyn9lff699khxf9744t54kusu50ja3jexe67qft9ftaw9njhlr6jm58kw84hmpsgmkma8swzdewkdc8l3gh8a5wvqjhpnx32ffa08mh5yzw0n44w6yaer4tmlwthytkrpw82a88cve3pwt4jysw6nvsxj7nlstwc78yntmhcm6m0mnf72s37uvvkpmc839umk8mlfzktadegatnlelk2l75c6cr4zeng7r8x5kd2anfvurk8svaamavww5x0h7w2yznnhje4atckuj47xl7ls688cm4qd2dhlzlzdvh5eym6jqgdc7qv6l37fr5kywc6tt2thjnhal3ax4j8v3x54hh9wqp2anl6lvze0gqh0jmam6e3nxuhv3kw99mv7dtdjjnaahwu9q5ntk0fmycr3c2qxslngadcd6xnk4t89070meu09u8ntx8jktdj4wvf3ls90744ey03e7klgh3ej650z4anf7w5hhftgyfl4mhlntskjfffuy07gg3l4ndpk96kwtkhax4l5gx49elys5nfcdr8je23v0u7k3lak3wm98ran77hl2td0mdddkqgq8ava5nsluj96e';
    const offerSummary = {
      offered: { [selectedNft.launcherId]: -1 },
      requested: { xch: 6750000000000 },
      infos: {
        [selectedNft.launcherId]: {
          launcherId: selectedNft.launcherId,
          type: 'NFT',
          also: { metadata: '' },
        },
      },
      fees: 5000000000,
    };
    const offerFilePath = '/Users/foo/bar.offer';
    const imported = true;
    const demo = { isValid: true };

    navigate('/dashboard/offers/view-nft', {
      state: {
        tradeRecord,
        offerData,
        offerSummary,
        offerFilePath,
        imported,
        demo,
      },
    });
  }

  return (
    <MenuItem
      onClick={() => {
        onClose();
        handleViewOffer();
      }}
      disabled={disabled}
    >
      <ListItemIcon>
        <OffersIcon />
      </ListItemIcon>
      <Typography variant="inherit" noWrap>
        <Trans>Demo - View Offer (Imported)</Trans>
      </Typography>
    </MenuItem>
  );
}

/* ========================================================================== */
/*                     Demo Action - View Offer (My Offer)                    */
/* ========================================================================== */

type NFTDemoViewOfferMyOfferContextualActionProps = NFTContextualActionProps;

function NFTDemoViewOfferMyOfferContextualAction(
  props: NFTDemoViewOfferMyOfferContextualActionProps,
) {
  const { onClose, selection } = props;
  const navigate = useNavigate();
  const selectedNft: NFTInfo | undefined = selection?.items[0];
  const disabled = (selection?.items.length ?? 0) !== 1;

  function handleViewOffer() {
    const tradeRecord = {
      confirmedAtIndex: 0,
      acceptedAtTime: 1652389989,
      createdAtTime: 1652388989,
      isMyOffer: true,
      sent: 0,
      coinsOfInterest: [],
      tradeId: '0x1234567890',
      status: 'PENDING_ACCEPT',
      sentTo: [],
      summary: {
        offered: { [selectedNft.launcherId]: -1 },
        requested: { xch: 6750000000000 },
        infos: {
          [selectedNft.launcherId]: {
            launcherId: selectedNft.launcherId,
            type: 'NFT',
            also: { metadata: '' },
          },
        },
        fees: 5000000000,
      },
      offerData: undefined,
    };
    const offerData = undefined;
    const offerSummary = undefined;
    const offerFilePath = undefined;
    const imported = false;

    navigate('/dashboard/offers/view-nft', {
      state: { tradeRecord, offerData, offerSummary, offerFilePath, imported },
    });
  }

  return (
    <MenuItem
      onClick={() => {
        onClose();
        handleViewOffer();
      }}
      disabled={disabled}
    >
      <ListItemIcon>
        <OffersIcon />
      </ListItemIcon>
      <Typography variant="inherit" noWrap>
        <Trans>Demo - View Offer (My Offer)</Trans>
      </Typography>
    </MenuItem>
  );
}

/* ========================================================================== */
/*                    Demo Action - View Offer (Completed)                    */
/* ========================================================================== */

type NFTDemoViewOfferCompletedContextualActionProps = NFTContextualActionProps;

function NFTDemoViewOfferCompletedContextualAction(
  props: NFTDemoViewOfferCompletedContextualActionProps,
) {
  const { onClose, selection } = props;
  const navigate = useNavigate();
  const selectedNft: NFTInfo | undefined = selection?.items[0];
  const disabled = (selection?.items.length ?? 0) !== 1;

  function handleViewOffer() {
    const tradeRecord = {
      confirmedAtIndex: 0,
      acceptedAtTime: 1652389989,
      createdAtTime: 1652388989,
      isMyOffer: true,
      sent: 0,
      coinsOfInterest: [],
      tradeId: '0x2234567890',
      status: 'CONFIRMED',
      sentTo: [],
      summary: {
        offered: { [selectedNft.launcherId]: -1 },
        requested: { xch: 6750000000000 },
        infos: {
          [selectedNft.launcherId]: {
            launcherId: selectedNft.launcherId,
            type: 'NFT',
            also: { metadata: '' },
          },
        },
        fees: 5000000000,
      },
      offerData: undefined,
    };
    const offerData = undefined;
    const offerSummary = undefined;
    const offerFilePath = undefined;
    const imported = false;

    navigate('/dashboard/offers/view-nft', {
      state: { tradeRecord, offerData, offerSummary, offerFilePath, imported },
    });
  }

  return (
    <MenuItem
      onClick={() => {
        onClose();
        handleViewOffer();
      }}
      disabled={disabled}
    >
      <ListItemIcon>
        <OffersIcon />
      </ListItemIcon>
      <Typography variant="inherit" noWrap>
        <Trans>Demo - View Offer (Completed)</Trans>
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

  console.log('availableActions:');
  console.log(availableActions);

  const actions = useMemo(() => {
    const actionComponents = {
      [NFTContextualActionTypes.CreateOffer]: NFTCreateOfferContextualAction,
      [NFTContextualActionTypes.Transfer]: NFTTransferContextualAction,
      // TODO: Remove these demo actions
      [NFTContextualActionTypes.DemoViewOfferImported]:
        NFTDemoViewOfferImportedContextualAction,
      [NFTContextualActionTypes.DemoViewOfferMyOffer]:
        NFTDemoViewOfferMyOfferContextualAction,
      [NFTContextualActionTypes.DemoViewOfferCompleted]:
        NFTDemoViewOfferCompletedContextualAction,
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
    NFTContextualActionTypes.CreateOffer |
    NFTContextualActionTypes.Transfer |
    NFTContextualActionTypes.DemoViewOfferImported | // TODO: Remove
    NFTContextualActionTypes.DemoViewOfferMyOffer | // TODO: Remove
    NFTContextualActionTypes.DemoViewOfferCompleted, // TODO: Remove
};
