npm install electron-installer-dmg -g
npm install electron-packager -g
sudo rm -rf dist
mkdir dist
sudo pyinstaller daemon.spec
cp -r dist/daemon ../electron-react
cd ..
cd electron-react
npm install
npm run build
electron-packager . Chia --overwrite --icon=./src/assets/img/chia.ico
mv Chia-darwin-x64 ../build_scripts/dist/
cd ../build_scripts
electron-installer-dmg dist/Chia-darwin-x64/Chia.app Chia --overwrite
