# Security re-review of the owner's decisions D1–D4, D6, D7

Date: 2026-11-06
Reviewer: security review agent
Scope: the spec on branch `docs/spec` at cb3f1a6, changes after revision 2 (31a0997).

---

# Security re-review of decisions D1–D4, D6, D7 (spec branch `docs/spec`, HEAD cb3f1a6)

Read-only. Sources: `git -C /home/agent/Projects/credits/bridge/repo show docs/spec:docs/spec.md` (1,252 lines), `docs/spec:docs/reviews/2026-11-06-spec-security-review.md`, and `git log -p 31a0997..docs/spec -- docs/spec.md`. Nothing was checked out, edited or committed. Line numbers below refer to the spec as shown by `git show`.

## Verdict

The six decisions are implementable and none of them needs to be reversed. Two of them, however, leave the spec's own economic statements false unless a precise rule is added:

1. **D3 + D6 together void the post-founder loss bound** (`vault cap ≤ Σ bondCs of the smallest T-set × conservative price`, §3.3 l.183-186). The bound is checked only at cap proposals (§3.3, §11 "Vault cap"); entrants may post their whole bond in USDT ("in any proportion", §5.10 l.509), USDT does not count for the bound, and D3 removed the only discretionary gate. A T-coalition of USDT-bonded entrants can therefore form under an already-raised cap and steal beyond the stated bound. This is fund loss beyond the trust model as written; it is fixed without touching D3 or D6 by checking the bound at activation (finding N1).
2. **D2 removes the pause as a bound on a colluding threshold.** §3.3(1) l.156 still lists "pause" among the things that bound a T-coalition. After D2 the real bound during a pause is the daily cap until the vault cap is drained (5 days at defaults), and the paused-mode claim rule is ambiguous about the 24-h undelayed window, which can make the pause *increase* a non-whitelisted coalition's throughput (N2). This is within the trust model's ultimate bound (vault cap) but the text must say so, and the ambiguity must be closed.

The other findings are Medium/Low: the hourly-slice buyback (D1) is still fully capturable per epoch by a repeated sweep-and-tick (N3); the slash reserve has no exit path on the vault and no bounded reimbursement mechanism (N4); automatic admission can be silently vetoed by abstention and applicants' bonds get stuck (N5); the bootstrap can be hijacked by a Sybil majority of applicants and has a dead end if the vault is never linked (N6, N7). Plus 19 inconsistencies the edits introduced or left behind, mostly in §5.1, §5.4, §5.8, §5.12, §6.3, §9, §11.

## Findings table

| id | sev | decision | section | title |
|---|---|---|---|---|
| N1 | High | D3+D6 | §3.3, §5.4 `activate`, §5.10, §11 | Cap bound checked only at proposals; USDT-only entrants admitted automatically void it |
| N2 | High | D2 | §6.3 `claim`, §8.9, §3.3(1) | Paused-mode claims: undelayed-window test unspecified; pause no longer a bound; the colluder can start the pause itself |
| N3 | Medium | D1 | §8.4, §5.4 `buybackTick` | Sweep-then-tick in the same slot repeats every hour: the whole epoch fund is still capturable; relayers best placed |
| N4 | Medium | D4 | §6.2, §6.3, §8.8 | No vault method moves `reserveUsdt` out; "reimburse users pro rata" has no bounded mechanism on either chain |
| N5 | Medium | D3 | §5.4 `withdrawBond`, §8.5 step 4, §5.8 | Abstention is a free veto; an applicant never attested is stuck in `Applied` with its bond locked; `T` (≤ 7) false attestations reject anyone |
| N6 | Medium | D7 | §5.14 steps 2-3 | Bootstrap hijack: `S ≥ R + 2` Sybil applicants are eligible without the real founders' attestations and exclude them; published address captured |
| N7 | Medium | D7 | §5.14 step 5, §5.12 | `AwaitingVault` dead end: if no vault is ever linked, founders' 100k CS bonds are locked forever |
| N8 | Low | D7×D6 | §5.14 step 4, §6.3 `deposit`, §8.6 | A founder that never pays 50 USDT freezes vault deposits; no Credits rule removes it; vault removal takes 30 days |
| N9 | Low | D2 | §7.4(3), §8.9 | "Never sign while paused" contradicts "relayers keep signing small withdrawals"; automatic `mint-mismatch` pause treated like a single-relayer alarm |
| N10 | Low | D4 | §5.4 `appeal`, §8.8 | "Two thirds" arithmetic undefined; `Slashed` records never compact (64-record bound); prover share purely discretionary |
| N11 | Low | D1 | §5.7.1, §8.1 | Conversion at mint with default `maxCsPrice = 0` (accepted by D1): the T-th approver can time its own ask; UI default needed |
| N12 | Low | D7 | §5.14 step 2-3, §5.9 | With exactly 3 applicants the rule is unanimity (one applicant vetoes); link attestation at `T`; 6-month founder clock runs from deploy, not from `Normal` |

## Details

### N1 (High) — D3 + D6: the cap bound is void for USDT-bonded entrants
Scenario. After the founder phase the cap has been raised (say 100,000 USDT, legitimately backed by founders' CS at the conservative price). Attacker admits 7 relayers (T caps at 7 for N ≥ 13), each with 1M CS of one-year delegations (still theirs, still earning) and a bond posted entirely in USDT on the vault (§5.10 allows "any proportion"; 50 USDT minimum). D3: nobody can object; they are activated after 7 days as long as T relayers attest eligibility (delegations are real). Now the smallest T-set has Σ bondCs = 0, but nothing re-checks the bound: §3.3 l.185 and §11 say it is checked "at every cap proposal and execution". The coalition signs false claims up to the cap at the daily-cap rate. Their USDT bonds are in a separate ledger and, as the earlier review's C2(b) showed, a T-coalition controlling `updateSigners` can recover all but the last two of them (remove members, wait 30 days, `releaseBond` by the remaining members). Cost ≈ 7 × max(1,000, 10 % × userUsdt) USDT at risk of which most is recovered, versus the whole cap. The stated bound is broken, hence fund loss beyond the trust model.
Fix (keeps D3 automatic and D6's two assets):
- Make the bound an admission invariant: `activate(relayerId)` MUST throw (`cap`) if, with the applicant added to the active set, `Σ bondCs of the smallest T-set × conservativePrice < current vault cap` (cap as last attested in `vaultView`). This is deterministic, no human objection, and it forces a cheap-CS applicant to post CS whenever it would become part of the cheapest T-set. Add the same check to I-list as "I18: at every activation the bound of §3.3 holds".
- Also re-evaluate the bound lazily (per the §5 lazy-update rule) and, when it fails for any other reason (conservative price lowered, relayers leaving), auto-create the risk-lowering "lower cap" proposal; it executes at `passedAt` (§8.7) and relayers sign `Cap`.
- Optional, owner's call: a CS floor per entrant (e.g. `bondCs × entryPrice ≥ 50 %` of the requirement). D6 as recorded in §14 says "CS plus USDT for the required value"; the words "in any proportion" were added by the spec author in §5.10 l.509, so a floor would not contradict the decision as written.

### N2 (High) — D2: paused-mode claim path
(a) Ambiguity. §6.3 `claim` l.657: "Not paused, except a kind 0 claim below `delayThreshold` within the daily cap, which is paid also while paused"; §8.9 l.927: "within the rolling daily cap and without the queue". The H3 rule (fewer than a whitelist majority and `undelayedWindow + amount > delayThreshold` → queued 24 h) is not mentioned for the paused path, and §8.9 l.931 says the cost is "up to the daily cap (2,000 per 24 h)", which is only true if the undelayed test is skipped. If skipped: a non-whitelisted T-coalition gets 1,000 undelayed per 24 h in normal mode but 2,000 per 24 h while paused, and any one coalition member can start the pause (single-relayer pause, both chains). The pause would double the coalition's undelayed throughput and stop honest relayers from doing anything further.
(b) Statement. §3.3(1) l.156-157 still lists "pause: any honest relayer can pause during the delay" as a bound on a colluding threshold; §9 "Threshold malicious" and §12.4 "T relayers sign false claims → watchdogs pause" inherit it. After D2 the pause stops only claims ≥ threshold, the queue, deposits and mints. A T-coalition drains the vault cap at the daily-cap rate whatever anyone does (slashing on Credits does not remove them from the vault set when honest signers < `threshold()`). The honest side's only lever becomes the daily cap and the vault cap. Within the trust model's ultimate bound, but the text must say it.
Fix (keeps D2):
- Specify the paused path exactly: paid iff `kind = 0`, `amount < delayThreshold`, the normal H3 test passes (whitelist majority or `undelayedWindow + amount ≤ delayThreshold`), and the rolling daily cap allows it; otherwise the call reverts (not queued, not marked `claimed`). Both windows are updated as in normal mode. Bound during a pause: 1,000/24 h for a non-whitelisted coalition, `dailyCap` for a whitelisted one, same as normal mode.
- Rewrite §3.3(1): replace the pause bullet with "pause: stops deposits, mints, claims ≥ `delayThreshold` and the queue; small claims continue up to the daily cap, so a theft in progress is slowed to `dailyCap` per day, not stopped".
- Optional escalation that does not contradict "a false alarm never locks users out": a second, distinct relayer pausing while a pause is open (each chain) makes it a full pause (small claims stop); both pausers bear the 7-day / unfounded-pause consequences. Likewise the automatic `mint-mismatch` pause (§5.7 step 5), which is T-vs-T disagreement, not one relayer's alarm, should be a full pause on Credits.

### N3 (Medium) — D1: slices do not change the per-epoch bound
Scenario. The slot boundary is public (block time, hour slots). Each hour the attacker (a) `buy(maxCusdt, 0)` sweeps every ask below its own extreme ask (it pays the honest sellers their price, i.e. no loss to them and little to the attacker, who keeps the CS), then (b) calls `buybackTick()`; the tick buys from the attacker's ask. §8.4 l.823 "one manipulated slot can capture at most 1/168" is true but repeatable 168 times: the whole epoch fund for ≈ 336 transactions (≈ 6 CS of fees) plus transient capital. Relayers are best placed because their loop ticks "if no one has yet" and they can order sweep-then-tick themselves. Nothing here touches user funds; it diverts the reward fund from honest relayers and delegators, which is the security budget. The "other sellers have an hour to place lower asks" argument is void because the sweep removes them just before the tick.
Fix (no price limit):
- Execute the slot's buyback as a lazy update at the start of *every* state-changing call (including `buy`, `payable` ask/sell, `cancelAsk`) when a new slot has begun, before the method body; keep `buybackTick()` as an explicit trigger. The attacker's sweep then triggers the tick first, which fills against the honest asks; it must instead sweep in the last block of the previous slot and win the race for the first call of the new slot against every user and relayer. Work stays within the 50-fill bound (the carrying call may do one buyback plus its own ≤ 50 fills: state it, or cap the lazy buyback at 25 fills).
- Specify that a slot is consumed by the first call in it whether or not anything was bought, that `epochFund` is a sub-ledger of `buybackFund` (I5), and when the epoch bookkeeping (fixing `epochFund`, `sliceBudget`) runs if `closeEpoch` is late.
- State the real bound in §8.4 and §3.3: "a persistent manipulator can capture the fund over an epoch; the slices only raise the cost and give honest sellers a chance each hour".

### N4 (Medium) — D4: reserve has no exit on the vault, no bounded reimbursement
§8.8 l.894-896: `BondSlash` moves the USDT bond to `reserveUsdt`, "subject to the same appeal and two-thirds rule". §6.2 has no message type and §6.3 no method that moves anything out of `reserveUsdt` (`BondRelease` pays from `bondUsdt[nodeWallet]`). So a successful appeal cannot return the USDT, users cannot be reimbursed in USDT, and the prover's share is CS-only. On Credits, "reimburse users pro rata" (l.908) has no definition of the payee set or snapshot; iterating `balances` is unbounded (C3), and a claim-based scheme on current balances is Sybil-able by moving cUSDT between wallets.
Fix: add `ReserveUse(uint64 nonce,uint8 purpose,bytes32 nodeWallet,address to,uint256 amount)` to §6.2 and `useReserve(ReserveUse, sigs)` to §6.3 requiring `unpauseThreshold()` signatures (max(T, ceil(2n/3)), mirroring two thirds), signable only after the Credits proposal executed. On Credits, a reserve-use proposal carries the payee list as attested data (`payees`-style, ≤ 100 `wallet:amount`, attested by T, several proposals for more), credited to `csClaimable`; define "pro rata" as pro rata to the unpaid withdrawals (recorded on Credits, unpaid on the vault) at the time of the shortfall, which is both bounded and non-Sybil-able.

### N5 (Medium) — D3: abstention veto, stuck applicants, T-level rejection
- `activate` needs eligibility "attested" (T attest true, §5.8); `Rejected` needs T attest false (§8.5 step 4). If incumbents simply do not attest (free, undetectable), the applicant stays `Applied` forever; `withdrawBond` (§5.4 l.374) is open only for `Exiting`, `Inactive`-and-leaving, `Rejected`, and `cancelApplication` exists only in `Bootstrap` (§5.14). The applicant's bond (≥ 1,000 USDT-equivalent, 100k CS for founders) is locked indefinitely; incumbents keep N small, which M6 was meant to prevent.
- T is at most 7: for N > 13, fewer than half of the relayers can reject any applicant by attesting "ineligible" — a verifiable lie, but attestations get no divergence mark (§7.6 marks digests only) and no proof exists. The one-third veto returns through the attestation channel.
Fix: `cancelApplication()` (W) in every state, 7 days after application while `Applied`, bond to `csClaimable` (USDT via `releaseBond`, no `removedAt` condition since never a signer). Count eligibility attestations for open applications in participation (missing ones lower it toward the < 50 % `Inactive` rule). Rejection requires more than half of active relayers attesting ineligible (governance threshold), acceptance stays at T. An eligibility attestation that differs from one accepted with T identical submitters for the same (period, relayer) earns a divergence mark like a digest.

### N6 (Medium) — D7: bootstrap hijack
Rule (§5.14 step 2): eligible when more than half of the *other* applicants attest it. With S Sybil and R real applicants, a Sybil is eligible without any real attestation iff `S − 1 > (S + R − 1)/2`, i.e. `S ≥ R + 2`; the real founders are then not eligible (they need Sybil attestations) and `activateBootstrap()` (anyone) activates the Sybils only. Cost for R = 3: 5 wallets × (100k CS bond + 1M CS year-delegations from ≥ 2 own wallets); the bonds are recoverable (cancel/leave, the Sybils control the vault they then deploy). Result: the published Credits address has attacker founders who attest an attacker vault; users who trust the on-chain `getRelayers()`/attested vault rather than the release can be phished for up to the founder cap. The project loses only an address and redeploys. No in-contract defence exists without a deployer commitment, which D7 removed.
Fix (operational, respects D7): publish the Credits address only together with the vault and the founders' node wallets, after the link; the release instructs users to verify the three founders against `getRelayers()`. In-contract, owner's call: a hash of the intended founders' node wallets in the deploy transaction's user data (no key, fee or vote for the deployer, but it does reintroduce a deployer choice, so I flag it rather than recommend it). At minimum, make `activateBootstrap()` callable only by an applicant and not before `deployTime + 48 h` so the real founders can at least apply before any activation (D7 says "no 7-day wait"; a short global window is a different rule, still the owner's call).

### N7 (Medium) — D7: `AwaitingVault` dead end
§5.12 l.533: in `Bootstrap`/`AwaitingVault` only bootstrap methods and getters are open; `leave` is not one, and `withdrawBond` requires a vault signer-set nonce attested in `vaultView` (C2). If the vault is never deployed/linked (deployer gone, founders disagree, T attestations never reached), the three founders' 300k CS are locked forever. Fix: in `AwaitingVault`, `leave()` opens and `withdrawBond()` is allowed 7 days after `leave` without the vault conditions (no signer set exists yet); if active founders fall below 3, the state returns to `Bootstrap` (remaining founders back to `Applied`, cancel allowed).

### N8 (Low) — D7 × D6: founder without the 50 USDT bond
§5.14 step 4: the vault "refuses deposits while any founder's 50 USDT bond is missing". A founder that never deposits blocks deposits forever; removing it needs `requestFounderRemoval` by `threshold()` (30 days) plus `updateSigners`; on Credits it stays `Active` (no `updateStatus` rule covers it), so the Credits set and the vault set diverge and the honest watchdogs pause. Fix: vault rule counts only founders that are signers (`foundersInSet()`); Credits `updateStatus` makes a founder `Inactive` when 30 days after `Normal` its `bscBond` attestation is below 50 USDT (this is what the pre-D7 text did); the constructor takes `(signer, nodeWallet)` pairs so `depositBond(nodeWallet, …)` can be matched.

### N9 (Low) — D2: relayer signing rule
§7.4(3) "Never sign while the Credits contract is paused" vs §8.9 l.926 "relayers keep signing those withdrawals". Fix: sign withdrawals with net < `delayThreshold` during a single-relayer pause only if the own watchdog passes; sign nothing during an automatic (`mint-mismatch`) pause or a watchdog failure (§7.5). State that a claim refused while paused is not marked `claimed`.

### N10 (Low) — D4 details
Define "two thirds": `yes ≥ ceil(2N/3)` with N at execution (N = 2 → 2, 4 → 3, 5 → 4). `Slashed` records stay in `relayers` (≤ 64 non-`Exited`, §5.1); define compaction to `signerHistory` 30 days after the slash once no reserve proposal concerning it is open. The prover's 10 % is now a bounty paid at the relayers' discretion; acceptable, but the contract should auto-create the "pay prover" proposal at slash + 30 days when no appeal was filed so only the vote is needed.

### N11 (Low) — D1: conversion at mint (accepted residual)
With `maxCsPrice = 0` (the §8.1 example) and a thin book, the relayer that sends the T-th approval can place its own ask first; loss ≤ `conversionMax` (20) per deposit, ≈ 10 % of a 10 USDT deposit. Accepted by D1; recommend the deposit UI default `maxCsPrice` to a multiple of `lastPrice` read from the contract, and the §8.1 example use a non-zero value.

### N12 (Low) — D7 arithmetic
With exactly 3 applicants, "more than half of the other 2" means both: any single applicant vetoes the other two (bond back after 7 days, so a cheap 7-day DoS; a 4th applicant resolves it). The link attestation at `T = 2` of 3 is a one-off irreversible setting; use "more than half of active relayers" (identical for 3, clearer in general). `founderPhaseEnd` "6 months after deploy" (§5.9) starts counting in `Bootstrap`; count from `Normal`.

## Inconsistencies introduced or left by the edits

1. §5.1 `cfg` (l.266): "vault address, EIP-712 domain separator, … initial relayers" are immutable deployment constants. D7 deploys the vault afterwards and has no initial relayers; the domain separator contains `verifyingContract`. Both must become state set by the link attestation (step 5), and `proveFalseSignature` must use it.
2. §5.8 attestation table has no `link` kind (vault address, chain id, hash of the initial signer set) although §5.14 step 5 requires "T attestations"; `attest` caller is **R** (active relayer) but in `Bootstrap` applicants call it.
3. §5.4 method table lacks `cancelApplication` (named only in §5.14); §5.12 lacks rows for `appeal`, `activateBootstrap`, `cancelApplication`.
4. §5.4 `applyRelayer` and §5.10 require 50 USDT "on the vault attested as `bondUsdtOnBsc`" for founders; in `Bootstrap` there is no vault. `activateBootstrap` "founder bonds paid" must mean the CS part only, with the USDT part enforced by the vault (§5.14 step 4).
5. §5.4 `withdrawBond` (l.374) applies `exitAt + 30 days`, `vaultView` nonce and `removedFromVaultAt + 30 days` to `Rejected` too; §8.5 step 4 (L2) says 7 days. A rejected applicant was never a signer; carve it out.
6. §6.3 `deposit` lists `signers.length ≥ 3` but not the founder-bond condition of §5.14 step 4; §6 constructor lacks founders' node wallets needed to check it.
7. §5.12 `buybackTick` = yes in `Blocked`/`Blocked + migration`, but §8.10(1) says "no new offers, fills" and `buy` is "no". Decide: either the buyback continues against remaining asks after a block (then say so in §8.10) or it stops, in which case the residual `buybackFund` is stranded cUSDT that counts in `totalSupply` for the 1 % end-of-life rule (§8.10 step 5) and can keep bonds locked to the 24-month maximum.
8. §3.3(1) l.156 (pause as a bound), §9 "Threshold malicious", §12.4 "T relayers sign false claims": all pre-D2; see N2.
9. §3.1 actors: no row for "two thirds of active relayers: use the slash reserve" (D4); "Anyone" should include `buybackTick`.
10. §7.4(3) vs §8.9 on signing while paused (N9).
11. §11 is missing: appeal window 30 days; reserve use threshold (two thirds, hard-coded); buyback slot 1 h / 168 slices per epoch; bootstrap minimum 3 founders, mutual-attestation rule, cancel after 7 days; under "Pause limits", that withdrawals < `delayThreshold` continue (D2).
12. §9 lacks rows for: vault never linked after `activateBootstrap`; founder without USDT bond; hijacked bootstrap; slashed relayer's appeal. "Bond slashed" row should cite the reserve/appeal rule; "Price manipulation" row still points to "§14 D1" instead of §8.4.
13. §8.4 numbering: two items are numbered "3." (closeEpoch and participation).
14. §5.1 `epochFund`/`sliceBudget` are listed as separate fields; I5 (`Σ balances + Σ bid escrow + buybackFund = totalSupply`) only holds if `epochFund` is a portion of `buybackFund`, not a separate balance. Say so.
15. §5.3 status list has no outcome for a cancelled application (`Exited`?) and no lifetime for `Slashed` records (N10).
16. §5.12 note: `proveFalseSignature` "every state" (I15) vs "only bootstrap methods and getters" in `Bootstrap`/`AwaitingVault` — harmless (no vault yet), but say "every state once `Normal` has been reached" or list it.
17. §12 test plan: no cases for the bootstrap (eligibility clique, cancel, hijack race), `buybackTick` slot accounting, paused-mode claims (the undelayed test, revert not queue), appeal and reserve votes, `useReserve` on the vault.
18. §15: "L2 rejected applicant → §8.5 step 4" conflicts with §5.4 `withdrawBond` (item 5); "Underspecified 15 → §5.14" fine; D4's reserve mechanics (underspecified 10) are now in §8.8 but the vault side is missing (N4).
19. §2.1 "Admission: … 7-day wait" and §11 "Admission wait 7 days" are correct for `Normal` but should note the `Bootstrap` exception explicitly introduced by D7.

## Positive notes
- D2 has one good property worth stating: a permanent stand-off (honest pauser, coalition < U) leaves every user able to withdraw in pieces below 1,000 within the daily cap, so goal 5 survives a stand-off.
- D4's appeal window plus "removal stays in force" is sound: a stolen-key relayer is out immediately, its bond is not consumed by a hasty vote, and M1 prevents key reuse after re-application.
- D6 removes the C2(a) hole cleanly; the vault's separate `bondUsdt` ledger and I6 are consistent after the edit.
