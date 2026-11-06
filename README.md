# Credits USDT bridge

A bridge that carries USDT from BNB Smart Chain to the Credits network as **csUSDT** ("Credits
Bridged USDT", 1 to 1) and back, with a CS ↔ csUSDT order book on Credits. No single key or server
controls it: independent relayers, each a Credits full node, must agree before anything is minted
or paid.

**Status: design.** The specification is complete and reviewed; no contract or relayer code is
written yet. Nothing here is deployed on any mainnet.

| What | Where |
|---|---|
| Specification (start with the glossary, §0, and the worked scenarios, §16) | [docs/spec.md](docs/spec.md) |
| Slides: how it works, how to become a relayer, two scenarios | [docs/slides/](docs/slides/) (open `index.html`) |
| Security reviews of the design | [docs/reviews/](docs/reviews/) |
| Runtime probes: what the design needs from the Credits executor, a private Credits network and BSC | [probes/](probes/), CI in [.github/workflows/probes.yml](.github/workflows/probes.yml) |

The Credits node, contract executor and wallet live in the other repositories of
[CreditsCommunity](https://github.com/CreditsCommunity).
