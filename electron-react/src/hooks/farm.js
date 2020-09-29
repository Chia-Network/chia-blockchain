import { useEffect, useState } from "react";
import { useSelector } from "react-redux";

import { big_int_to_array, arr_to_hex, sha256 } from "../util/utils";

/* global BigInt */

/**
 * Retrieves total farmed chia & last farmed height from redux state.
 */
export const useFarmedChiaInfo = () => {
  const [totalChiaFarmed, setTotalChiaFarmed] = useState(BigInt(0));
  const [lastHeightFarmed, setLastHeightFarmed] = useState(0);
  const wallets = useSelector((state) => state.wallet_state.wallets);

  useEffect(() => {
    (async () => {
      let totalChia = BigInt(0);
      let biggestHeight = 0;
      for (let wallet of wallets) {
        if (!wallet) {
          continue;
        }
        for (let tx of wallet.transactions) {
          if (tx.additions.length < 1) {
            continue;
          }
          // Height here is filled into the whole 256 bits (32 bytes) of the parent
          let hexHeight = arr_to_hex(
            big_int_to_array(BigInt(tx.confirmed_at_index), 32)
          );
          // Height is a 32 bit int so hashing it requires serializing it to 4 bytes
          let hexHeightHashBytes = await sha256(
            big_int_to_array(BigInt(tx.confirmed_at_index), 4)
          );
          let hexHeightDoubleHashBytes = await sha256(hexHeightHashBytes);
          let hexHeightDoubleHash = arr_to_hex(hexHeightDoubleHashBytes);

          if (
            hexHeight === tx.additions[0].parent_coin_info ||
            hexHeight === tx.additions[0].parent_coin_info.slice(2) ||
            hexHeightDoubleHash === tx.additions[0].parent_coin_info ||
            hexHeightDoubleHash === tx.additions[0].parent_coin_info.slice(2)
          ) {
            totalChia += BigInt(tx.amount);
            if (tx.confirmed_at_index > biggestHeight) {
              biggestHeight = tx.confirmed_at_index;
            }
            continue;
          }
        }
      }
      if (totalChia !== totalChiaFarmed) {
        setTotalChiaFarmed(totalChia);
        setLastHeightFarmed(biggestHeight);
      }
    })();
  }, [wallets]);

  return [totalChiaFarmed, lastHeightFarmed];
};

/**
 * Retrieves plot info necessary for the Farm page.
 *
 */
export const usePlotsInfo = () => {
  const plots = useSelector((state) => state.farming_state.harvester.plots);
  plots.sort((a, b) => b.size - a.size);

  /* const not_found_filenames = useSelector(
    (state) => state.farming_state.harvester.not_found_filenames
  );
  const failed_to_open_filenames = useSelector(
    (state) => state.farming_state.harvester.failed_to_open_filenames
  ); */

  const totalSize = plots.reduce((prev, cur) => prev + cur.file_size, 0);

  return [plots, totalSize];
};

export const useTotalNetworkSpace = () => {
  const totalNetworkSpace = useSelector((state) =>
    BigInt(state.full_node_state.blockchain_state.space)
  );

  const formattedTotalNetworkSpace =
    (totalNetworkSpace / BigInt(Math.pow(1024, 4))).toString() + "TiB";

  return [totalNetworkSpace, formattedTotalNetworkSpace];
};

export const useExpectedTimeToWin = (farmerSpace, totalNetworkSpace) => {
  const proportion = parseFloat(farmerSpace) / parseFloat(totalNetworkSpace);
  const totalHours = 5.0 / proportion / 60;

  return [totalHours, proportion];
};

export const useLatestBlockChallenges = () => {
  let latestChallenges = useSelector(
    (state) => state.farming_state.farmer.latest_challenges
  );

  if (!latestChallenges) {
    latestChallenges = [];
  }

  return [latestChallenges];
};
