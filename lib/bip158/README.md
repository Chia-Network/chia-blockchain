## BIP158

This implements the compact block filter construction in BIP 158. The code is not used anywhere in the Bitcoin Core code base yet. The next step towards BIP 157 support would be to create an indexing module similar to TxIndex that constructs the basic and extended filters for each validated block.

### Install

```bash
git submodule update --init --recursive
python3 -m venv env
. env/bin/activate
pip3 install .
```

### Run python tests

```bash
python3 python-bindings/test.py
```

### Installation steps on a fresh OSX image

xcode-select install

Install brew:

ruby -e "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install)"

brew install python3  
brew install cmake  
brew install boost  
brew install openssl  

At this point the only error is can’t find boost_thread lib

The issue is the homebrew boost ships libboost_thread-mt libs but doesn’t include plain libboost_thread, so clang can’t find it. Interestingly, homebrew boost does have both plain and -mt files for the libboost_system libraries.

$ find /usr/local/lib/ | grep boost_thread  
libboost_thread-mt.a  
libboost_thread-mt.dylib  

Solution, with no guarantees that this is “the Right Way to do things”, but appears to work fine for the configure stage:

$ cd /usr/local/lib  
$ ln -s libboost_thread-mt.a libboost_thread.a  
$ ln -s libboost_thread-mt.dylib libboost_thread.dylib  

