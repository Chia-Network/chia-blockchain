type PlotSize = {
  label: string;
  value: number;
  workspace: string;
  defaultRam: number;
};

export const defaultPlotSize: PlotSize = {
  label: '101.4GiB',
  value: 32,
  workspace: '332GiB',
  defaultRam: 4608,
};

const plotSizes: PlotSize[] = [
  { label: '600MiB', value: 25, workspace: '1.8GiB', defaultRam: 512 },
  defaultPlotSize,
  { label: '208.8GiB', value: 33, workspace: '589GiB', defaultRam: 9216 },
  // workspace are guesses using 55.35% - rounded up - past here
  { label: '429.8GiB', value: 34, workspace: '1177GiB', defaultRam: 18432 },
  { label: '884.1GiB', value: 35, workspace: '2355GiB', defaultRam: 36864 },
];

export const plotSizeOptions = plotSizes.map((item) => ({
  value: item.value,
  label: `${item.label} (k=${item.value}, temporary space: ${item.workspace})`,
}));

export default plotSizes;
