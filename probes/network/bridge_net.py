#!/usr/bin/env python3
"""Bridge probes on the private Credits network of CreditsCommunity/node (ci/testnet/run.sh).

run.sh has no hook for outside scripts: the CI copies ci/testnet/tokens.py of its node checkout to
node_tokens.py, puts this file in its place and runs run.sh with CONTRACTS=1 TOKENS=1:

    tokens.py <work_dir> <nodes> [--via N] [--json OUT] [--strict-api]

NetProbe.java is read from $BRIDGE_NET_SOURCE. What it records (all through node --via):
- block time: getBlockchainTimeMills() in two calls some seconds apart, against the wall clock,
  and the recorded times read on every node;
- getBalance() of a wallet against WalletBalanceGet;
- a CS payment without user data, which payable() refuses: where the CS end up;
- a CS payment with user data (user field 1), which payable() accepts;
- CS the contract emits with user data: whether the user data reach the chain;
- CS the contract emits to another contract: what the node does with it;
- the contract state on every node.
The run fails only when the probe itself cannot run; the answers are facts for the spec.
"""
import argparse
import hashlib
import json
import os
import struct
import sys
import time

import base58

from contracts import CURRENCY_CS, deploy
from fund import MAX_FEE, Account, Client, api, balance, general, node_account, pack_inner_id, send
from node_tokens import Run, v_str  # the original ci/testnet/tokens.py, copied aside by the CI

UF_TEXT = 1           # cs::trx_uf::ordinary::Text: the user data payable() receives
UF_TYPE_STRING = 2    # csdb::UserField::String
TX_TYPE_TRANSFER = 0


def b58(pk):
    return base58.b58encode(pk).decode()


def transfer_with_text(src, dst_pk, amount_int, text):
    """A CS transfer carrying a string user field 1 (signed as count, u32 size, bytes, as fund.py signs
    its string field)."""
    fields_for_sig = struct.pack("<BI", 1, len(text)) + text
    payload = b"".join([
        pack_inner_id(src.next_inner_id), src.pk, dst_pk, struct.pack("<iQ", amount_int, 0),
        struct.pack("<H", MAX_FEE), struct.pack("<B", CURRENCY_CS), fields_for_sig,
    ])
    t = api.Transaction()
    t.id = src.next_inner_id
    t.source = src.pk
    t.target = dst_pk
    t.amount = general.Amount(integral=amount_int, fraction=0)
    t.balance = general.Amount(integral=0, fraction=0)
    t.currency = CURRENCY_CS
    t.signature = src.sk.sign(payload).signature
    t.fee = api.AmountCommission(commission=MAX_FEE)
    t.timeCreation = int(time.time() * 1000)
    t.userFields = struct.pack("<BBIBI", 0, 1, UF_TEXT, UF_TYPE_STRING, len(text)) + text
    t.type = TX_TYPE_TRANSFER
    t.poolNumber = 0
    return t


def send_text(client, src, dst_pk, amount_int, text):
    last = client.WalletTransactionsCountGet(src.pk).lastTransactionInnerId or 0
    src.next_inner_id = int(last) + 1
    r = client.call("TransactionFlow", transfer_with_text(src, dst_pk, amount_int, text), retry=False)
    return r.status.code == 0, r.status.message


def wait_balance(client, pk, predicate, seconds=180):
    deadline = time.time() + seconds
    value = balance(client, pk)
    while not predicate(value) and time.time() < deadline:
        time.sleep(5)
        value = balance(client, pk)
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("work")
    parser.add_argument("nodes", type=int)
    parser.add_argument("--via", type=int, default=1)
    parser.add_argument("--json", default="")
    parser.add_argument("--strict-api", action="store_true")
    args = parser.parse_args()
    run = Run(args.nodes, False, args.via)
    facts = {}

    master = node_account(args.work, args.nodes)
    alice = Account(hashlib.sha256(master.pk + b"bridge alice").digest())
    port = 9090 if args.via == 1 else 9100 + args.via
    funder = Client(port, 300)
    master.next_inner_id = None
    ok, message = send(funder, master, alice.pk, 300)
    print(f"fund alice: {'ok' if ok else 'FAILED ' + str(message)}", flush=True)
    wait_balance(funder, alice.pk, lambda b: b >= 300)

    with open(os.environ["BRIDGE_NET_SOURCE"]) as f:
        source = f.read()
    probe = deploy(run.client(), master, "NetProbe", source)
    other = deploy(run.client(), master, "NetProbeOther", source.replace("class NetProbe ", "class NetProbeOther ")
                   .replace("public NetProbe()", "public NetProbeOther()"))
    facts["contracts"] = {"probe": b58(probe), "other": b58(other)}

    # ---- block time ---------------------------------------------------------------------------
    samples = []
    for _ in range(2):
        wall = int(time.time() * 1000)
        s, r, m = run.invoke(alice, probe, "now", [], "now()")
        samples.append({"status": s, "contract_ms": r, "wall_ms": wall, "message": m[:200]})
        time.sleep(20)
    facts["block_time"] = samples
    if all(x["status"] == 0 and isinstance(x["contract_ms"], int) for x in samples):
        d_contract = samples[1]["contract_ms"] - samples[0]["contract_ms"]
        d_wall = samples[1]["wall_ms"] - samples[0]["wall_ms"]
        facts["block_time_summary"] = {
            "contract_delta_ms": d_contract, "wall_delta_ms": d_wall,
            "skew_ms": [x["contract_ms"] - x["wall_ms"] for x in samples]}
        run.check(d_contract > 0, f"block time advances between calls ({d_contract} ms vs {d_wall} ms wall)", kind="info")

    # ---- getBalance -----------------------------------------------------------------------------
    s, r, m = run.invoke(alice, probe, "seeBalance", [v_str(b58(alice.pk))], "seeBalance(alice)")
    facts["getBalance"] = {"status": s, "contract": r, "api_after": balance(funder, alice.pk)}

    # ---- payments ---------------------------------------------------------------------------------
    before_alice, before_probe = balance(funder, alice.pk), balance(funder, probe)
    alice.next_inner_id = None
    ok, message = send(funder, alice, probe, 7)
    time.sleep(40)
    facts["payment_without_user_data"] = {
        "api_accepted": ok, "message": str(message)[:200],
        "alice_delta": round(balance(funder, alice.pk) - before_alice, 6),
        "contract_delta": round(balance(funder, probe) - before_probe, 6)}
    print(f"  payment refused by payable(): {facts['payment_without_user_data']}", flush=True)

    before_alice, before_probe = balance(funder, alice.pk), balance(funder, probe)
    ok, message = send_text(funder, alice, probe, 11, b"bond:relayer-1")
    time.sleep(40)
    facts["payment_with_user_data"] = {
        "api_accepted": ok, "message": str(message)[:200],
        "alice_delta": round(balance(funder, alice.pk) - before_alice, 6),
        "contract_delta": round(balance(funder, probe) - before_probe, 6)}
    print(f"  payment accepted by payable(): {facts['payment_with_user_data']}", flush=True)

    # ---- emitted CS with user data ------------------------------------------------------------------
    before_alice = balance(funder, alice.pk)
    s, r, m = run.invoke(master, probe, "refund", [v_str(b58(alice.pk)), v_str("3")], "refund(alice, 3)")
    after_alice = wait_balance(funder, alice.pk, lambda b: b > before_alice + 2)
    emitted = []
    for t in (funder.TransactionsGet(alice.pk, 0, 20).transactions or []):
        if t.trxn.source == probe:
            emitted.append({"amount": t.trxn.amount.integral, "userFields": (t.trxn.userFields or b"").hex(),
                            "type": t.trxn.type})
    facts["emitted_with_user_data"] = {"status": s, "ret": r, "alice_delta": round(after_alice - before_alice, 6),
                                       "transactions_from_contract": emitted}
    print(f"  emitted with user data: {facts['emitted_with_user_data']}", flush=True)

    # ---- emitted CS to another contract --------------------------------------------------------------
    before_probe, before_other = balance(funder, probe), balance(funder, other)
    s, r, m = run.invoke(master, probe, "payContract", [v_str(b58(other)), v_str("2")], "payContract(other, 2)")
    time.sleep(40)
    facts["emitted_to_contract"] = {
        "status": s, "ret": r, "message": m[:200],
        "probe_delta": round(balance(funder, probe) - before_probe, 6),
        "other_delta": round(balance(funder, other) - before_other, 6)}
    print(f"  emitted to a contract: {facts['emitted_to_contract']}", flush=True)

    # ---- the state on every node ---------------------------------------------------------------------
    time.sleep(30)
    summaries, states = {}, {}
    for i in range(1, args.nodes + 1):
        try:
            summaries[i] = run.read(i, master, probe, "summary", [])
            got = run.client(i).SmartContractGet(probe)
            states[i] = hashlib.sha256(got.smartContract.objectState).hexdigest()[:16] if got.status.code == 0 else "error"
        except Exception as e:
            summaries[i] = states[i] = f"unreachable ({type(e).__name__})"
    facts["summary_per_node"] = summaries
    facts["state_hash_per_node"] = states
    run.check(len(set(states.values())) == 1, f"NetProbe state is the same on every node ({states})")

    print(json.dumps(facts, indent=1, default=str), flush=True)
    if args.json:
        with open(args.json, "w") as f:
            json.dump({"facts": facts, "checks": run.log}, f, indent=1, default=str)
    sys.exit(1 if run.failures else 0)


if __name__ == "__main__":
    main()
