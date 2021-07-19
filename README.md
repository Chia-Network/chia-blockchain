# TadCoin Blockchain network

We've reached mainnet! **At the moment only CLI is supported**, we're working on GUI.

If you'd like to participate in testnet please [join our Discord](https://discord.gg/4dkydqsQ)

**How is this fork different?**

* We support both OG and NFT plots and get you **FULL** reward. Yes, that's right, full reward for any type of plots.
* Get most of the space on the hard drive - we support k28+ plots  
* Open Source and in forked off Chia Network. You can always audit code by diff'ing it with Chia upstream
* You don't need goddamn IP addresses for the nodes. Tad's network discovery works.

                                                         
### Ports used by TadCoin

➡ Full Node: **4044** ⬅

Other ports: 
- harvester: **4448**, RPC: **4458**
- farmer: **4447** , RPC: **4457**
- wallet: **4449**, RPC: **4456**
- timelord_launcher: **4050**
- timelord: **8446**
- node: **4044**, RPC: **4555**
- TAD daemon: **4400**

For unix system you can check if anything is using these ports with this handy command:
```
netstat -tnap | grep -e '4044|4448|4458|4447|4457|4050|8446|4044|4555'
```
                                                              
## Credit

Thanks Chia team!