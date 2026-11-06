#!/usr/bin/env python3
"""Check that SigProbe.java recovers secp256k1 signers like Ethereum's ecrecover, on a contract
executor without a node, and time it.

Usage: sig_probe.py --node NODE_CHECKOUT --jar contract-executor.jar [--jar other.jar] --jdk JDK_DIR
                    [--count N] [--json OUT]
Needs eth-account to make the reference signatures.
"""
import argparse
import json
import os
import secrets
import statistics
import sys
import time

from eth_account import Account
from eth_utils import keccak

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", required=True)
    parser.add_argument("--jar", action="append", required=True)
    parser.add_argument("--jdk", required=True)
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--work", default="sig-probe-run")
    parser.add_argument("--json", default="")
    args = parser.parse_args()

    sys.path.insert(0, os.path.join(os.path.abspath(args.node), "ci", "contracts"))
    import executor_harness as h

    with open(os.path.join(HERE, "SigProbe.java")) as f:
        source = f.read()

    cases = []
    for _ in range(args.count):
        acct = Account.create()
        digest = keccak(secrets.token_bytes(64))
        sig = Account.unsafe_sign_hash(digest, acct.key).signature
        cases.append((digest.hex(), bytes(sig).hex(), acct.address.lower()))

    results = []
    for n, jar in enumerate(args.jar):
        ex = h.Executor(jar, args.jdk, os.path.join(os.path.abspath(args.work), f"executor{n}"))
        ex.start()
        rec = h.Recorder()
        out = {"jar": jar}
        try:
            c = h.Contract(ex, "SigProbe", source, h.key("owner"), rec)
            r = c.deploy()
            out["deploy"] = {"ok": bool(r and r["ok"]), "error": r and r["error"]}
            if not (r and r["ok"]):
                results.append(out)
                continue
            r = c.call(h.key("alice"), "keccak", h.v_str(""))
            out["keccak_empty_ok"] = r["ret"] == keccak(b"").hex()
            times, wrong, errors = [], [], []
            for digest, sig, addr in cases:
                t0 = time.perf_counter()
                r = c.call(h.key("alice"), "recover", h.v_str(digest), h.v_str(sig))
                times.append((time.perf_counter() - t0) * 1000)
                if not r["ok"]:
                    errors.append(r["error"])
                elif r["ret"] != addr:
                    wrong.append([digest, sig, addr, r["ret"]])
            out["recovered"] = len(cases) - len(wrong) - len(errors)
            out["wrong"] = wrong[:3]
            out["errors"] = errors[:3]
            out["call_ms"] = {"median": round(statistics.median(times), 1), "max": round(max(times), 1)}
            # a tampered digest must give another address, a high-s signature none
            digest, sig, addr = cases[0]
            r = c.call(h.key("alice"), "recover", h.v_str("00" + digest[2:]), h.v_str(sig))
            out["tampered_digest_rejected"] = r["ok"] and r["ret"] != addr
            n_order = 0xfffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd0364141
            s = int(sig[64:128], 16)
            high = sig[:64] + format(n_order - s, "064x") + format(1 - (int(sig[128:], 16) - 27) + 27, "02x")
            r = c.call(h.key("alice"), "recover", h.v_str(digest), h.v_str(high))
            out["high_s_rejected"] = r["ok"] and r["ret"] == ""
        finally:
            ex.stop()
        results.append(out)

    print(json.dumps(results, indent=1))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(results, f, indent=1)
    ok = all(o.get("recovered") == len(cases) and o.get("keccak_empty_ok") and o.get("high_s_rejected")
             and o.get("tampered_digest_rejected") for o in results)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
