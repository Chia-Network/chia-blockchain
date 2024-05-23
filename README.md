# chia-blockchain

[![Chia Network logo][logo-chia]][link-chia]

| Releases | Repo Stats | Socials |
| -------- | ---------- | ------- |
[![Latest Release][badge-release]][link-latest] <br /> [![Latest RC][badge-rc]][link-release] <br /> [![Latest Beta][badge-beta]][link-release] | [![Coverage][badge-coverage]][link-coverage] <br /> [![Downloads][badge-downloads]][link-downloads] <br /> [![Commits][badge-commits]][link-commits] <br /> [![Contributers][badge-contributers]][link-contributers] | [![Discord][badge-discord]][link-discord] <br /> [![YouTube][badge-youtube]][link-youtube] <br /> [![Reddit][badge-reddit]][link-reddit] <br /> [![Twitter][badge-twitter]][link-twitter]

Chia represents a contemporary digital currency developed from the ground up, aiming for efficiency, decentralization, and robust security. Here's an overview of its key attributes and advantages:

- Utilizes a Proof of Space and Time consensus mechanism, enabling farming with standard hardware.
- Boasts user-friendly full node and farmer interfaces, with thousands of nodes active on the mainnet.
- Incorporates the Chia seeder, which maintains a roster of dependable nodes via an integrated DNS server.
- Features a streamlined UTXO-based transaction model, minimizing on-chain state.
- Employs a Lisp-style Turing-complete functional programming language tailored for financial applications.
- Implements BLS keys and aggregate signatures, ensuring one signature per block.
- Introduces a pooling protocol, granting farmers control over block production.
- Offers support for light clients, facilitating swift and objective syncing.
- Flourishes with a global community of farmers and developers continually expanding its ecosystem.

Please check out the [Chia website][link-chia], the [Intro to Chia][link-intro], and [FAQ][link-faq] for information on this project.

Python 3.8.1+ is required. Make sure your default python version is >=3.8.1 by typing `python3`.

If you are behind a NAT, it can be difficult for peers outside your subnet to reach you when they start up. You can enable [UPnP][link-upnp]
on your router or add a NAT (for IPv4 but not IPv6) and firewall rules to allow TCP port 8444 access to your peer.
These methods tend to be router make/model specific.

Most users should only install harvesters, farmers, plotter, full nodes, and wallets.
Setting up a seeder is best left to more advanced users.
Building Timelords and VDFs is for sophisticated users, in most environments.
Chia Network and additional volunteers are running sufficient Timelords for consensus.

## Installing

Install instructions are available in the [Installation Details][link-install] section of the [Chia Docs][link-docs].

## Running

Once installed, an [Intro to Chia][link-intro] guide is available in the [Chia Docs][link-docs].

[badge-beta]:         https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fdownload.chia.net%2Flatest%2Fbadge-data-beta.json&query=%24.message&logo=chianetwork&logoColor=black&label=Latest%20Beta&labelColor=%23e9fbbc&color=%231e2b2e
[badge-beta2]:        https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fdownload.chia.net%2Flatest%2Fbadge-data-beta.json&query=%24.message&logo=chianetwork&logoColor=%23e9fbbc&label=Latest%20Beta&labelColor=%23474748&color=%231e2b2e&link=https%3A%2F%2Fgithub.com%2FChia-Network%2Fchia-blockchain%2Freleases&link=https%3A%2F%2Fgithub.com%2FChia-Network%2Fchia-blockchain%2Freleases
[badge-commits]:      https://img.shields.io/github/commit-activity/w/Chia-Network/chia-blockchain?logo=GitHub
[badge-contributers]: https://img.shields.io/github/contributors/Chia-Network/chia-blockchain?logo=GitHub
[badge-coverage]:     https://img.shields.io/coverallsCoverage/github/Chia-Network/chia-blockchain?logo=Coveralls&logoColor=red&labelColor=%23212F39
[badge-discord]:      https://dcbadge.vercel.app/api/server/chia?style=flat-square&theme=full-presence
[badge-discord2]:     https://img.shields.io/discord/1034523881404370984.svg?label=Discord&logo=discord&colorB=1e2b2f
[badge-downloads]:    https://img.shields.io/github/downloads/Chia-Network/chia-blockchain/total?logo=GitHub
[badge-rc]:           https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fdownload.chia.net%2Flatest%2Fbadge-data-rc.json&query=%24.message&logo=chianetwork&logoColor=white&label=Latest%20RC&labelColor=%230d3349&color=%23474748
[badge-reddit]:       https://img.shields.io/reddit/subreddit-subscribers/chia?style=flat-square&logo=reddit&labelColor=%230b1416&color=%23222222
[badge-release]:      https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fdownload.chia.net%2Flatest%2Fbadge-data.json&query=%24.message&logo=chianetwork&label=Latest%20Release&labelColor=%231e2b2e&color=%230d3349
[badge-twitter]:      https://img.shields.io/twitter/follow/chia_project?style=flat-square&logo=x.org&logoColor=white&labelColor=black
[badge-youtube]:      https://img.shields.io/youtube/channel/subscribers/UChFkJ3OAUvnHZdiQISWdWPA?style=flat-square&logo=youtube&logoColor=%23ff0000&labelColor=%230f0f0f&color=%23272727

[link-chia]:          https://www.chia.net/
[link-chialisp]:      https://chialisp.com/
[link-commits]:       https://github.com/Chia-Network/chia-blockchain/commits/main/
[link-consensus]:     https://docs.chia.net/consensus-intro/
[link-contributers]:  https://github.com/Chia-Network/chia-blockchain/graphs/contributors
[link-coverage]:      https://coveralls.io/github/Chia-Network/chia-blockchain
[link-discord]:       https://discord.gg/chia
[link-docs]:          https://docs.chia.net/docs-home/
[link-downloads]:     https://www.chia.net/downloads/
[link-faq]:           https://docs.chia.net/faq/
[link-install]:       https://docs.chia.net/installation/
[link-intro]:         https://docs.chia.net/introduction/
[link-latest]:        https://github.com/Chia-Network/chia-blockchain/releases/latest
[link-pool]:          https://docs.chia.net/pool-farming/
[link-reddit]:        https://www.reddit.com/r/chia/
[link-release]:       https://github.com/Chia-Network/chia-blockchain/releases
[link-seeder]:        https://docs.chia.net/guides/seeder-user-guide/
[link-twitter]:       https://twitter.com/chia_project
[link-upnp]:          https://www.homenethowto.com/ports-and-nat/upnp-automatic-port-forward/
[link-youtube]:       https://www.youtube.com/chianetwork

[logo-chia]:          https://www.chia.net/wp-content/uploads/2022/09/chia-logo.svg "Chia logo"
