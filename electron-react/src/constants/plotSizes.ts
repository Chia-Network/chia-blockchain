type PlotSize = {
  label: string;
  value: number;
  workspace: string;
  defaultRam: number;
};

export const defaultPlotSize: PlotSize = {
  label: '101.4GiB',
  value: 32,
  workspace: '331GiB',
  defaultRam: 3072,
};

const plotSizes: PlotSize[] = [
  { label: '600MiB', value: 25, workspace: '1.8GiB', defaultRam: 200 },
  { label: '1.3GiB', value: 26, workspace: '3.6GiB', defaultRam: 200 },
  { label: '2.7GiB', value: 27, workspace: '9.2GiB', defaultRam: 200 },
  { label: '5.6GiB', value: 28, workspace: '19GiB', defaultRam: 200 },
  { label: '11.5GiB', value: 29, workspace: '38GiB', defaultRam: 500 },
  { label: '23.8GiB', value: 30, workspace: '83GiB', defaultRam: 1000 },
  { label: '49.1GiB', value: 31, workspace: '165GiB', defaultRam: 2000 },
  defaultPlotSize,
  { label: '208.8GiB', value: 33, workspace: '660GiB', defaultRam: 6000 },
  // workspace are guesses using 55.35% - rounded up - past here
  { label: '429.8GiB', value: 34, workspace: '1300GiB', defaultRam: 12000 },
  { label: '884.1GiB', value: 35, workspace: '2600GiB', defaultRam: 24000 },
];

export const plotSizeOptions = plotSizes.map((item) => ({
  value: item.value,
  label: `${item.label} (k=${item.value}, temporary space: ${item.workspace})`,
}));

export default plotSizes;
