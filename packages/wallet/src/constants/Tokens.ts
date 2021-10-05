import { BubbleChart as AsteroidIcon, LocalDrink as WaterIcon, WbSunny as EnergyIcon } from '@material-ui/icons';
import CATToken from '../types/CATToken';

const Tokens: CATToken = [{
  icon: AsteroidIcon,
  symbol: 'AST',
  name: 'Asteroid',
  tail: 'ff02ffff01ff02ffff03ff2fffff01ff0880ffff01ff02ffff03ffff21ff0bffff09ff2dff028080ffff015fffff01ff088080ff018080ff0180ffff04ffff01a0716525483ce568e51dd1a2708838eccc2347efcc0268a6d007ec0a84308e3fcdff018080',
  description: 'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.',
}, {
  icon: WaterIcon,
  symbol: 'WAT',
  name: 'Water',
  tail: 'ff02ffff01ff02ffff03ff2fffff01ff0880ffff01ff02ffff03ffff21ff0bffff09ff2dff028080ffff015fffff01ff088080ff018080ff0180ffff04ffff01a0a557cbf053d3efb62ce8d4acf9ed82cdca260593466c62fcdb19902d47518e1cff018080',
  description: 'Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.',
}, {
  icon: EnergyIcon,
  symbol: 'ENG',
  name: 'Energy',
  tail: 'ff02ffff01ff02ffff03ff2fffff01ff0880ffff01ff02ffff03ffff21ff0bffff09ff2dff028080ffff015fffff01ff088080ff018080ff0180ffff04ffff01a0ded7745e3502d18a08fdfcd5fce275ea985803fd2a24ca06d9a17aaa09a6d957ff018080',
  description: 'Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur.',
}];

export default Tokens;
