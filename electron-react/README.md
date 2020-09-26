# The React UI

The Chia Blockchain UI is built with [React](https://reactjs.org/) and can be run either as an [Electron](https://www.electronjs.org/) app or in the browser.

## Running the Electron UI

```bash
npm install
npm run build
npm run electron
````

## Running in the Browser

### Debug

```bash
npm install
npm run build
npm start
````

Navigate to http://localhost:3000.

### Production

On the machine hosting a full node, wallet, and farmer, first install [pm2](https://pm2.keymetrics.io/) to manage the nodejs web service: `npm install pm2 -g`.

```bash
npm run build
cd build
pm2 serve . 3000
pm2 startup
pm2 save
````

The node service will host the UI on port 3000 of the farmer machine and will restart on boot. **Firewall rules should be set to restrict access to just those mahcines you want to allow. In [ufw](https://help.ubuntu.com/community/UFW) this looks like `ufw allow from <ip of machine to allow> to any port 3000 proto tcp`.
