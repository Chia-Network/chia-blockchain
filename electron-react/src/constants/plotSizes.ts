const plotSizes = [
  { label: '600MiB', value: 25, workspace: '1.8GiB', default_ram: 200 },
  { label: '1.3GiB', value: 26, workspace: '3.6GiB', default_ram: 200 },
  { label: '2.7GiB', value: 27, workspace: '9.2GiB', default_ram: 200 },
  { label: '5.6GiB', value: 28, workspace: '19GiB', default_ram: 200 },
  { label: '11.5GiB', value: 29, workspace: '38GiB', default_ram: 500 },
  { label: '23.8GiB', value: 30, workspace: '83GiB', default_ram: 1000 },
  { label: '49.1GiB', value: 31, workspace: '165GiB', default_ram: 2000 },
  { label: '101.4GiB', value: 32, workspace: '331GiB', default_ram: 3072 },
  { label: '208.8GiB', value: 33, workspace: '660GiB', default_ram: 6000 },
  // workspace are guesses using 55.35% - rounded up - past here
  { label: '429.8GiB', value: 34, workspace: '1300GiB', default_ram: 12000 },
  { label: '884.1GiB', value: 35, workspace: '2600GiB', default_ram: 24000 },
];

export const plotSizeOptions = plotSizes.map((item) => ({
  value: item.value,
  label: `${item.label} (k=${item.value}, temporary space: ${item.workspace})`,
}));

export default plotSizes;
