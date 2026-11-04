# Runtime probes

Measurements of the Credits contract runtime that the bridge design depends on.

`executor/run_probes.py` drives `BridgeProbe.java` (a probe, not the real cUSDT contract) on a
contract executor with no node, through the executor harness of the community node
(`ci/contracts/executor_harness.py` in CreditsCommunity/node):

```sh
python3 probes/executor/run_probes.py --node ../node --jar csnode/contract-executor.jar \
    --jdk csnode/ojdkbuild/java-11-openjdk-11.0.4 --deposits 2000 --relayers 13 --json out.json
```

It checks approval counting and minting at a threshold, conflicts, a bounded record of minted
ids, sequential withdrawal ids, failed calls, a CS bond received through `payable()` and refunded
with an emitted transaction, and it measures the time of each approval and the state size.
Block time and CS balances come from the harness stub here; the private network checks them
against a real node.
