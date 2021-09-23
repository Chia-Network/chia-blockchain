type PlotSize = {
  label: string;
  value: number;
  workspace: string;
  defaultRam: number;
};

export const defaultPlotSize: PlotSize = {
  label: '101.4GiB',
  value: 32,
  workspace: '239GiB',
  defaultRam: 3390,
};

const plotSizes: PlotSize[] = [
  { label: '600MiB', value: 25, workspace: '1.8GiB', defaultRam: 512 },
  defaultPlotSize,
  { label: '208.8GiB', value: 33, workspace: '521GiB', defaultRam: 7400 },
  // workspace are guesses using 55.35% - rounded up - past here
  { label: '429.8GiB', value: 34, workspace: '1041GiB', defaultRam: 14800 },
  { label: '884.1GiB', value: 35, workspace: '2175GiB', defaultRam: 29600 },
];

export const plotSizeOptions = plotSizes.map((item) => ({
  value: item.value,
  label: `${item.label} (k=${item.value}, temporary space: ${item.workspace})`,
}));

export default plotSizes;
