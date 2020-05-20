npm install electron-installer-dmg -g
npm install electron-packager -g
sudo rm -rf dist
mkdir dist
sudo pyinstaller daemon.spec
cp -r dist/daemon ../electron-react
cd ..
cd electron-react
npm run build
electron-packager . chia --overwrite
mv chia-darwin-x64 ../build_scripts/dist/
cd ../build_scripts
electron-installer-dmg dist/chia-darwin-x64/chia.app Chia