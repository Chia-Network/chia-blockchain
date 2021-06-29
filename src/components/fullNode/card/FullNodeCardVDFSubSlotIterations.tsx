import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import FarmCard from "../../farm/card/FarmCard";
import { FormatLargeNumber } from '@chia/core';

export default function FullNodeCardVDFSubSlotIterations() {
  const value = useSelector(
    (state) => state.full_node_state.blockchain_state.sub_slot_iters,
  );

  return (
    <FarmCard
      valueColor="textPrimary"
      title={<Trans>VDF Sub Slot Iterations</Trans>}
      value={<FormatLargeNumber value={value} />}
    />
  );
}
