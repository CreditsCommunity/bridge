#!/usr/bin/env python3
"""Probe the Credits contract runtime for the bridge design, on a contract executor without a node.

Usage: run_probes.py --node NODE_CHECKOUT --jar contract-executor.jar [--jar other.jar] --jdk JDK_DIR
                     [--deposits N] [--relayers R] [--json OUT]

Uses the executor harness of the community node (ci/contracts/executor_harness.py): the node's
APIEXEC service is a stub there, so block time and CS balances are fixed values. What only a real
node can answer (time from blocks, balances while syncing, how the API reports a failed call) is
probed on the private network instead.
"""
import argparse
import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", required=True)
    parser.add_argument("--jar", action="append", required=True)
    parser.add_argument("--jdk", required=True)
    parser.add_argument("--deposits", type=int, default=2000)
    parser.add_argument("--relayers", type=int, default=7)
    parser.add_argument("--work", default="probe-run")
    parser.add_argument("--json", default="")
    args = parser.parse_args()

    sys.path.insert(0, os.path.join(os.path.abspath(args.node), "ci", "contracts"))
    import executor_harness as h

    with open(os.path.join(HERE, "BridgeProbe.java")) as f:
        source = f.read()

    owner = h.key("owner")
    alice = h.key("alice")
    relayers = [h.key(f"relayer{i}") for i in range(args.relayers)]
    threshold = min(args.relayers // 2 + 1, 7)

    def v_long(i):
        return h.general.Variant(v_long=i)

    results = []
    for n, jar in enumerate(args.jar):
        ex = h.Executor(jar, args.jdk, os.path.join(os.path.abspath(args.work), f"executor{n}"))
        ex.start()
        rec = h.Recorder()
        rec.scenario = "bridge"
        out = {"jar": jar, "relayers": args.relayers, "threshold": threshold}
        try:
            c = h.Contract(ex, "BridgeProbe", source, owner, rec)
            r = c.deploy()
            out["deploy"] = {"ok": r and r["ok"], "error": r and r["error"]}
            if not (r and r["ok"]):
                results.append(out)
                continue
            r = c.call(owner, "setup", h.v_str(",".join(h.b58(x) for x in relayers)), h.v_int(threshold))
            out["setup"] = r["ok"]

            # platform: time and CS balance as the stub gives them
            ex.stub.balances[relayers[0]] = (500000, 0)
            r = c.call(alice, "now")
            out["now"] = {"ok": r["ok"], "ret": r["ret"], "error": r["error"]}
            r = c.call(alice, "csBalance", h.v_str(h.b58(relayers[0])))
            out["csBalance"] = {"ok": r["ok"], "ret": r["ret"], "error": r["error"]}

            # failed call: a write before the throw
            r = c.call(alice, "failAfterWrite")
            out["failAfterWrite"] = {"ok": r["ok"], "status": r["status"], "error": r["error"],
                                     "supply_after": c.get("totalSupply")["ret"]}

            # a non-relayer approval
            r = c.call(alice, "approveMint", v_long(0), h.v_str(h.b58(alice)), h.v_dec("1"))
            out["nonRelayer"] = {"ok": r["ok"], "error": r["error"]}

            # conflict: same id, different amount
            c.call(relayers[0], "approveMint", v_long(10 ** 9), h.v_str(h.b58(alice)), h.v_dec("5"))
            r = c.call(relayers[1], "approveMint", v_long(10 ** 9), h.v_str(h.b58(alice)), h.v_dec("6"))
            out["conflict"] = r["ret"]

            # deposits, approved out of order by threshold + 1 relayers; time and state size per call
            times, sizes, rets = [], [], {}
            order = list(range(args.deposits))
            order = order[1::2] + order[0::2]          # odd ids first, so mintedAbove grows then drains
            for i, dep in enumerate(order):
                for k in range(threshold + 1):
                    t0 = time.perf_counter()
                    r = c.call(relayers[k], "approveMint", v_long(dep), h.v_str(h.b58(alice)), h.v_dec("1.5"))
                    times.append((time.perf_counter() - t0) * 1000)
                    rets[r["ret"].split(" ")[0] if r["ok"] else "error"] = rets.get(r["ret"].split(" ")[0] if r["ok"] else "error", 0) + 1
                sizes.append(len(c.state))
                if i in (args.deposits // 2 - 1, args.deposits - 1):
                    out.setdefault("stats_at", []).append([i + 1, c.get("stats")["ret"], len(c.state)])
            out["approvals"] = rets
            out["approve_ms"] = {"median": round(statistics.median(times), 2),
                                 "p95": round(sorted(times)[int(len(times) * 0.95)], 2), "max": round(max(times), 2)}
            out["state_bytes"] = {"first": sizes[0], "peak": max(sizes), "last": sizes[-1]}
            out["supply"] = c.get("totalSupply")["ret"]

            # burns: sequential withdrawal ids
            ids = [c.call(alice, "burnForBsc", h.v_dec("1"), h.v_str("0x" + "ab" * 20))["ret"] for _ in range(3)]
            out["withdrawal_ids"] = ids
            r = c.call(alice, "burnForBsc", h.v_dec("1000000"), h.v_str("0x" + "ab" * 20))
            out["burnTooMuch"] = {"ok": r["ok"], "error": r["error"]}

            # bond in CS through payable, refund through an emitted transaction
            out["bond"] = c.call(relayers[0], "payable", h.v_dec("500000.25"), h.v_bytes(b""))["ret"]
            r = c.call(relayers[0], "refundBond")
            out["refund"] = {"ok": r["ok"], "ret": r["ret"], "emitted": r["emitted"]}
        finally:
            ex.stop()
        out["findings"] = rec.findings
        results.append(out)

    print(json.dumps(results, indent=1, default=str))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(results, f, indent=1, default=str)


if __name__ == "__main__":
    main()
