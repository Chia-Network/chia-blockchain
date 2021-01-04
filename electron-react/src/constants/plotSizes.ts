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
  defaultRam: 3584,
};

const plotSizes: PlotSize[] = [
  { label: '600MiB', value: 25, workspace: '1.8GiB', defaultRam: 500 },
  { label: '1.3GiB', value: 26, workspace: '3.6GiB', defaultRam: 500 },
  { label: '2.7GiB', value: 27, workspace: '9.2GiB', defaultRam: 500 },
  { label: '5.6GiB', value: 28, workspace: '19GiB', defaultRam: 500 },
  { label: '11.5GiB', value: 29, workspace: '38GiB', defaultRam: 500 },
  { label: '23.8GiB', value: 30, workspace: '83GiB', defaultRam: 1000 },
  { label: '49.1GiB', value: 31, workspace: '165GiB', defaultRam: 2000 },
  defaultPlotSize,
  { label: '208.8GiB', value: 33, workspace: '589GiB', defaultRam: 7168 },
  // workspace are guesses using 55.35% - rounded up - past here
  { label: '429.8GiB', value: 34, workspace: '1177GiB', defaultRam: 14336 },
  { label: '884.1GiB', value: 35, workspace: '2355GiB', defaultRam: 28672 },
];

export const plotSizeOptions = plotSizes.map((item) => ({
  value: item.value,
  label: `${item.label} (k=${item.value}, temporary space: ${item.workspace})`,
}));

export default plotSizes;
