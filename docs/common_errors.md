# Common Errors

### Depends: node-gyp (>= 3.6.2~) but it is not going to be installed

#### Ubuntu

`sudo rm <Node List Name(s) from> /etc/apt/sources.list.d`

```
sudo apt remove --purge nodejs npm node-gyp nodejs-legacy
sudo apt clean
sudo apt autoclean
sudo apt install -f
sudo apt autoremove
rm -rf ~/.nvm/
rm -rf ~/.npm/
```
[Source](https://askubuntu.com/questions/1057737/ubuntu-18-04-lts-server-npm-depends-node-gyp-0-10-9-but-it-is-not-going)
[Node Source](https://github.com/nodesource/distributions#debinstall)

---