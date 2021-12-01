import type { Plot } from '@chia/api';

export default function combineHarvesters(harvesters): {
  plots: Plot[];
  failedToOpenFilenames: string[];
  notFoundFilenames: string[];
} {
  const plots: Plot[] = [];
  const failedToOpenFilenames: string[] = [];
  const notFoundFilenames: string[] = [];

  harvesters.forEach((harvester) => {
    const {
      plots: harvesterPlots,
      failedToOpenFilenames: harvesterFailedToOpenFilenames,
      noKeyFilenames: harvesterNoKeyFilenames,
    } = harvester;

    harvesterPlots.forEach((plot) => {
      plots.push({
        ...plot,
        harvester: harvester.connection,
      });
    });

    failedToOpenFilenames.push(...harvesterFailedToOpenFilenames);
    notFoundFilenames.push(...harvesterNoKeyFilenames);
  });

  return {
    plots: plots.sort((a, b) => b.size - a.size),
    failedToOpenFilenames,
    notFoundFilenames,
  };
}
