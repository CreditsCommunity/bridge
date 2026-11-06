# USDT bridge for Credits: specification

Status: draft, revision 2 (2026-11-06), after the security review in
[reviews/2026-11-06-spec-security-review.md](reviews/2026-11-06-spec-security-review.md).
Not approved. No code is written against it yet. Decisions still open are in
[§14](#14-open-decisions); until they are taken, the text follows the user's current decision.

This document specifies a bridge that carries USDT from BNB Smart Chain (BSC) to the Credits
network as cUSDT, 1 to 1, and back; a CS ↔ cUSDT order book on Credits; and the relayer network
that connects the two chains. It replaces the design analysis of 2026-10-14 ("USDT bridge for
Credits: analysis") where the two differ: the decisions taken after it are listed in
[§2.3](#23-decisions-that-changed-since-the-analysis).

Words in capitals (MUST, MUST NOT, SHOULD) carry their usual meaning. "TO VERIFY" marks a fact
that the design depends on and that has not yet been confirmed on a real Credits network
([§13](#13-runtime-facts-and-what-is-still-to-verify)). Review finding ids (C1, H3, …) are
cited where a rule exists because of a finding.

---

## Contents

1. [Overview and goals](#1-overview-and-goals)
2. [Decisions](#2-decisions)
3. [Trust model](#3-trust-model)
4. [Architecture](#4-architecture)
5. [Credits contract `CusdtBridge`](#5-credits-contract-cusdtbridge)
6. [BSC contract `UsdtVault`](#6-bsc-contract-usdtvault)
7. [Relayer process](#7-relayer-process)
8. [Flows](#8-flows)
9. [Failure cases](#9-failure-cases)
10. [Invariants](#10-invariants)
11. [Parameters](#11-parameters)
12. [Test plan](#12-test-plan)
13. [Runtime facts and what is still to verify](#13-runtime-facts-and-what-is-still-to-verify)
14. [Open decisions](#14-open-decisions)
15. [Review findings and where they are addressed](#15-review-findings-and-where-they-are-addressed)

---

## 1. Overview and goals

**What it does.**

- A user deposits USDT into `UsdtVault` on BSC. Independent relayers see the deposit in a
  finalized BSC block and approve it on Credits. When enough of them agree, the Credits contract
  `CusdtBridge` mints the same amount of cUSDT to the user, minus a fixed fee, and converts a small
  part into CS from the sell offers, so the user can pay Credits transaction fees.
- A user burns cUSDT on Credits. The relayers sign the withdrawal for BSC. The user collects the
  signatures on a static claim page and claims the USDT from `UsdtVault`, paying the BSC gas.
- On Credits, holders of CS and cUSDT trade through an order book inside `CusdtBridge`: atomic, no
  arbiter, no capital from the team.

**Goals.**

1. No single key, server or person can take user funds.
2. No team liquidity: the bridge holds only what users deposit; prices come from users' offers.
3. No consensus change on Credits: everything runs as an ordinary contract and as processes next
   to ordinary nodes. The relayer is never part of the C++ node.
4. No admin and no upgradable code. Settings change only by the relayers' rules in this
   document, within hard caps fixed in the code.
5. Users can always get out: after any failure short of a colluding threshold of relayers, every
   cUSDT holder can still withdraw, including after a permanent block ([§8.10](#810-permanent-block-migration-and-end-of-life)).
6. Losses in the worst case are bounded by caps that grow only as the guarantees grow.
7. The contract state stays bounded: no user action can grow it without limit (C3).

**Non-goals.** Bridging CS to BSC; any asset other than USDT in this version; making a colluding
threshold of relayers unable to steal (see [§3](#3-trust-model)).

---

## 2. Decisions

### 2.1 Summary

| Topic | Decision |
|---|---|
| Asset | BSC USDT (BEP-20, 18 decimals) ↔ cUSDT on Credits, 1 to 1, amounts in multiples of 10⁻⁸ USDT |
| Credits contracts | One contract, `CusdtBridge`: token, bridge, relayer registry, bonds, order book, buyback, governance |
| BSC contract | `UsdtVault`: deposits, claims with EIP-712 threshold signatures, signer set, founders, whitelist, caps, bonds |
| Relayer eligibility | Credits full node whose wallet holds ≥ 1,000,000 CS of incoming 1-year delegations from at least 2 wallets other than the owner's |
| Admission | Automatic: eligibility attested by the relayers' software, 7-day wait, no sponsors (objection rule: [§14](#14-open-decisions) D3) |
| Operational threshold | `T = max(2, min(floor(N/2) + 1, 7))`, `N` = active relayers |
| Governance threshold | more than half of all active relayers, no cap of 7 |
| Bonds | Founders: 100,000 CS + 50 USDT. Later entrants: value ≥ max(1,000 USDT, 10 % of user USDT in the vault), fixed at entry |
| Slashing | Automatic, by proof of a false withdrawal signature, verified in the Credits contract, callable in every state |
| Fees | Bridge fee 0.05 cUSDT each way; swap fee 0.1 % paid by the taker; both fund a CS buyback for relayers and their delegators |
| CS for new users | 2 % of each deposit (min 1, max 20 cUSDT) bought as CS from the lowest asks at mint |
| Prices | Free market: no price limit imposed by the contract, also on automated purchases; the depositor MAY set a maximum CS price for their own conversion; the buyback is spread in hourly slices over the epoch ([§8.4](#84-fees-buyback-and-rewards)) |
| Large claims | Above 1,000 USDT per rolling 24 h (cumulative, not per claim), 24-hour delay unless the signatures include a majority of the whitelist |
| Exit | Permanent block → withdraw-only on both chains; each user withdraws, or migrates their own funds to new contracts registered by vote, with a fallback to their own BSC address |

### 2.2 Rejected alternatives

| Alternative | Why it is not used |
|---|---|
| Contract-to-contract calls (`invokeExternalContract`), a separate swap contract | Refused on mainnet: the node rejects `@UsingContract` methods (`Violations::SubsequentCall`) and executor 1518 fails every `invokeExternalContract` |
| CS transfers from one contract to another | Refused by the node: a contract-emitted transaction whose target is a contract is a violation (`Violations::SourceIsContract`, `solver/src/smartcontracts.cpp`) |
| Checking a CS balance with `getBalance` | Reads the wallet's current balance, not the balance at the executed block, and the balance can move right after the check |
| CS bonds locked as the eligibility criterion | Locking CS takes them out of the node's stake; 1-year delegations keep them earning (staking is on on mainnet, [§13.1](#131-verified)) |
| Sponsors, manual approval | The user requires automatic admission |
| ed25519 checked inside Java, classic multisigs, price oracle, CS minted by the protocol, fixed price | As in the analysis of 2026-10-14 |
| Contract-imposed maximum or minimum price on user orders | The user wants a free market |
| Fee in BNB | Would need a DEX conversion on BSC before buying CS |
| A new reward token | Value would have to come from the fees anyway; CS paid directly is simpler |
| Mass transfer of funds for upgrades | The most valuable target for an attack; replaced by per-user migration |
| Memo/tag on CS returns | The node drops user data on contract-emitted transactions ([§13.1](#131-verified)) |
| cUSDT as bond collateral counted in the loss bound | A thief recovers it by draining the vault (C2); cUSDT and USDT bonds count for entry only, not for the cap bound |

### 2.3 Decisions that changed since the analysis

- Relayers: delegations instead of a 500k CS balance; no sponsors; bond in CS + USDT with
  founders' terms; the threshold majority cannot raise founders' bonds.
- The swap is inside the bridge contract from the first version, because contracts cannot call
  each other and contracts cannot be upgraded.
- Conversion to CS at mint is always on (2 %), not an option.
- Fees go to a CS buyback rather than being paid to relayers in USDT.
- A 24-hour delay and a trusted whitelist for large claims; a founder phase.

---

## 3. Trust model

### 3.1 Actors

| Actor | Can | Cannot |
|---|---|---|
| User | Deposit, withdraw, trade, migrate own funds, set own return address | Move anyone else's funds |
| A single relayer | Approve, sign, pause both contracts within the pause limits ([§8.9](#89-pause-and-unpause)), propose, vote | Mint, pay a claim, unpause or change a setting alone |
| A threshold `T` of relayers | Mint for a deposit, sign a claim, update the vault's signer set, attest values to the contract | Change a hard cap; move user USDT other than through claims; raise founders' bonds; release a bond of a relayer still in the vault's signer set; unpause alone (needs `U`, [§8.9](#89-pause-and-unpause)) |
| More than half of active relayers | Change parameters within hard caps (7-day delay), admit versions, block permanently, register migration targets | Change code; exceed hard caps |
| Majority of active founders | Change the trusted whitelist on the vault | Anything else beyond a normal relayer |
| Anyone | Submit signatures to the vault, trigger epoch closes and status updates, submit a fraud proof, deliver claimable CS | — |

### 3.2 What is protected

- **One relayer, or fewer than `T`, misbehaving:** cannot mint or pay anything. A false
  withdrawal signature loses its CS bond by proof, in any contract state. A wrong mint approval
  only marks the approver; it cannot block the mint (H1).
- **Lost or duplicated events, restarts, BSC reorganisations:** deposits are read by sequential
  id from finalized blocks only; mints and claims are once per id ([§9](#9-failure-cases)).
- **Operator key theft of one relayer:** same as one malicious relayer.
- **Contract growth:** every collection in the contract state has a bound in code ([§5.11](#511-bounded-state-and-work)).

### 3.3 What is NOT protected

1. **A colluding threshold of relayers.** The vault cannot see Credits. If `T` relayers agree,
   they can sign claims for withdrawals that never happened, and the vault pays them. Equally,
   `T` relayers can approve a mint for a deposit that never happened. Nothing in the contracts
   prevents this. What actually bounds it (H3):
   - **the vault cap**: user USDT in the vault never exceeds it, so a theft never exceeds it;
   - **the rolling daily claim cap**: increases take 7 days and the daily cap is at most 20 % of
     the vault cap, so draining the full cap takes at least 5 days;
   - **the 24-hour delay**: claims not signed by a whitelist majority wait 24 h once their
     cumulative amount in a rolling 24 h exceeds 1,000 USDT, whatever the size of each claim;
   - **pause**: any honest relayer can pause during the delay; lifting a pause needs
     `U = max(T, ceil(2N/3))` approvals, more than `T`;
   - **slashing by proof**: the CS bonds of every signer of a false claim are confiscated, and
     a signer cannot recover its bond while it is still in the vault's signer set (C1, C2).

   When the colluders include a majority of the whitelist, the delay does not apply: the bound
   is then the daily cap, the vault cap and the bonds.
2. **Colluding founders during the founder phase.** With `F` founders, they reach `T` alone while
   `F ≥ T`, that is while `N ≤ 2F − 1` (M10): with 3 founders up to 5 relayers, with 5 up to 9.
   A majority of founders also controls the whitelist, so their large claims are not delayed.
   While founders can reach `T` alone, the vault itself enforces a cap of at most 20,000 USDT
   (H4): users trust a known group for a limited amount.
3. **A majority of all relayers** can change parameters within the hard caps, admit a relayer
   version, block the bridge permanently and register a migration target. Users who disagree
   have 7 days to withdraw before a change applies; migration is never forced.
4. **Value of slashed bonds.** CS has no reliable market price; slashed CS may be worth less than
   the loss. Bonds held as cUSDT or USDT are recovered by a thief who drains the vault (C2), so
   they count toward the entry requirement but not toward the cap bound.
5. **Sybil relayers.** Disjoint-wallet rules raise the cost of one person running several
   relayers; they cannot prove that two wallets belong to different people. The founder-phase
   trade rule ([§5.9](#59-order-matching)) can be met by one person with two wallets.
6. **Relayer code.** Nobody can prove remotely which program a relayer runs. The design checks
   what relayers produce, not what they claim to run ([§7.7](#77-code-verification)).
7. **Credits reorganisations deeper than the signing depth** ([§7.4](#74-withdrawal-loop)) can make
   an honest signature look false; the proof rules give honest relayers a defence (M2), but a
   claim already paid for a burn that a reorganisation removed breaks I1 by its amount.

The bound on the loss from (1), after the founder phase:
`vault cap ≤ Σ bondCs of the smallest set of active relayers able to reach T × conservative price`,
checked by the Credits contract at every cap proposal and execution and attested to the vault
([§6.3](#63-methods) `setCap`).

---

## 4. Architecture

```
            BSC                                   Credits
 ┌───────────────────────┐                 ┌──────────────────────────────┐
 │ UsdtVault             │                 │ CusdtBridge (one contract)    │
 │  deposit()  ── Deposit(id) ──┐          │  token cUSDT (v1 standard)    │
 │  claim(sigs) ◄─────────────┐ │          │  approveMint / burnForBsc     │
 │  signers, founders,        │ │          │  relayer registry, bonds      │
 │  whitelist, caps, delay    │ │          │  order book CS ↔ cUSDT        │
 └───────────────────────────┘ │ │          │  buyback, rewards, governance │
            ▲                  │ │          └──────────────────────────────┘
            │ claim tx         │ │ finalized reads        ▲ approvals, digests
            │ (user pays gas)  │ ▼                        │ (each relayer, own node)
 ┌──────────┴─────────┐   ┌────┴───────────────────┐      │
 │ static claim page   │◄──│ relayer 1..N            │──────┘
 │ collects signatures │   │  own Credits node       │
 └────────────────────┘   │  ≥ 2 BSC RPC sources    │
                           │  signatures over HTTPS  │
                           └────────────────────────┘
```

- **`UsdtVault`** (Solidity, BSC): holds user USDT, relayers' USDT bonds and the slash reserve
  in separate ledgers. Not upgradable, no owner.
- **`CusdtBridge`** (Java, Credits, `SmartContract` v3, `ExtensionTokenStandard` v1): the only
  Credits contract. Everything that must interact atomically lives in it, because contracts
  cannot call or pay each other.
- **Relayer**: a separate process next to a Credits full node, never inside the node. Reads
  both chains, sends approvals and digests to Credits, publishes withdrawal signatures at its
  own HTTPS URL. Relayers do not coordinate with each other.
- **Claim page**: static HTML/JS. Reads the withdrawal from Credits (through any public node
  API or a relayer's published copy), fetches signatures from the relayers' URLs registered in
  the contract, orders them, and lets the user send `claim` from their own wallet.

### 4.1 Identities of a relayer

| Identity | Chain | Used for |
|---|---|---|
| Node wallet | Credits | Receives the delegations; owns the bond; registers the relayer; can be kept offline |
| Operator key | Credits | Sends approvals, digests, votes, pauses. MAY equal the node wallet. Rotated by the node wallet |
| Signer key | BSC (secp256k1) | Signs EIP-712 messages for the vault. Never sends BSC transactions in normal operation. A key is registered once in the contract's lifetime (M1) |
| Owner wallet | Credits | Receives the owner share of rewards; its delegations do not count for eligibility |

### 4.2 Units and encodings

| Quantity | Representation |
|---|---|
| USDT on BSC | `uint256`, 18 decimals; every amount MUST be a multiple of 10¹⁰ (8 decimals) |
| cUSDT | `BigDecimal`, scale 8; `units = USDT_wei / 10¹⁰`; `amountWei = units × 10¹⁰` |
| CS amounts kept by the contract | `BigDecimal`, scale 6 |
| One emitted CS transfer | ≤ 10⁸ CS (L1: a `double` holds 15 significant digits; 10⁸ with 6 decimals is 15); larger amounts are paid in several calls |
| Prices | cUSDT per 1 CS, `BigDecimal` scale 8, tick 10⁻⁸ |
| Time | Credits: `getBlockchainTimeMills()` (block time, ms); BSC: `block.timestamp` (s) |
| Credits address | Contract: base58 string of the 32-byte ed25519 public key; BSC data: `bytes32` of the same key |
| BSC address | Contract: lowercase hex with `0x`, 42 characters, checked; BSC data: `address` |

Rounding rule: every division rounds in favour of the contract (amounts paid out round down,
amounts charged round up), and every rounding difference is kept in a dust account so that
[§10](#10-invariants) holds exactly.

---

## 5. Credits contract `CusdtBridge`

Java 11, one top-level class (nested static classes allowed), `extends
com.credits.scapi.v3.SmartContract implements com.credits.scapi.v1.ExtensionTokenStandard`.
Token name "Credits USDT", symbol `cUSDT`, 8 decimals. No owner field, no admin method.

Every method that changes state reads time once with `getBlockchainTimeMills()` and runs the
lazy updates that are due (governance applications, status updates, epoch bookkeeping, record
compaction), bounded in work per call ([§5.11](#511-bounded-state-and-work)).

### 5.1 State

| Field | Content | Bound |
|---|---|---|
| `cfg` | Immutable deployment constants: BSC chain id, vault address, EIP-712 domain separator, hard caps ([§11](#11-parameters)), deploy time, initial relayers | fixed |
| `params` | Current governable parameters | fixed size |
| `balances: Map<String, BigDecimal>` | cUSDT balances (free); a zero balance is removed | one per holder (each costs its creator a mint or transfer) |
| `allowed` | Allowances, ERC-20 semantics; zero removed | per holder |
| `totalSupply` | All cUSDT in existence, including escrowed, fund and locked | — |
| `pendingMints: Map<Long, PendingMint>` | Per deposit id: approvals grouped by data hash, first-approval time | ids in `[mintedBelow, attestedNextDepositId + 256)`; expire after 30 days |
| `mintedBelow: long`, `mintedAbove: TreeSet<Long>` | Minted deposit ids | `mintedAbove` ≤ 1,024 entries: approvals for ids ≥ `mintedBelow + 1024` are refused (C3) |
| `withdrawals` | Recent records by id: kind, from, BSC recipient, fallback, net amount, time, `hashStruct(Claim)` | the last 1,024 ids in full; older ids only in bucket roots |
| `withdrawalRoots: List<bytes32>` | Merkle root of each completed bucket of 1,024 withdrawal hashes | 32 bytes per 1,024 withdrawals (C3) |
| `nextWithdrawalId: long` | Sequential | — |
| `relayers: Map<Long, Relayer>` | Relayer records ([§5.3](#53-relayer-record)) | ≤ 64 non-`Exited` records; `Exited` records compacted to `signerHistory` |
| `signerHistory: Map<String, SignerUse>` | Every BSC signer key ever registered → relayer id, valid from/until (M1) | one per key; keys cannot be reused |
| `signerSets: List<SignerSetRecord>` | Every vault signer set by nonce: signers, founders to add, freeze flag, hash (underspecified 3) | the last 64 sets in full, older as hashes |
| `asks`, `bids: TreeMap<PriceKey, Order>` | Order book, price then id | ≤ 2,000 open orders in total, ≤ 20 per wallet, minimum size 10 CS and 0.10 cUSDT (C3) |
| `lastPrice`, `dailyStats[8]` | Last fill price; per-day CS and cUSDT volumes for the 7-day VWAP | fixed |
| `buybackFund: BigDecimal` | cUSDT from fees, not yet spent | — |
| `epochFund`, `sliceBudget`, `lastTickSlot` | Fund fixed at the epoch start, its 1/168 hourly slice, last hour slot spent | fixed |
| `csClaimable: Map<String, BigDecimal>` | CS owed to wallets (conversions, rewards, refunds) | one per wallet; claims below 0.001 CS stay in dust |
| `returnAddress: Map<String, String>` | Wallet → its return address for CS | one per wallet that set one |
| `csLiabilities` | Sum of all CS the contract owes | — |
| `epoch` | Current reward epoch: participation counters per relayer | fixed per relayer |
| `rewardLists: Map<Long, List<Payee>>` | Per relayer, the attested payee list of the closing epoch | ≤ 100 payees per relayer, replaced each epoch |
| `snapshots` | Contract values at the start of the current and previous digest periods (M7) | 2 entries |
| `digests` | Per relayer, digest of the current and previous period | 2 per relayer |
| `proposals: Map<Long, Proposal>` | Governance | ≤ 32 open; closed ones removed after 21 days |
| `admittedVersions: Map<String, Long>` | Version hash → retirement time (or max) | ≤ 16 |
| `founderPhase`, `founderPhaseEnd` | | — |
| `pause` | none / paused(by relayer, reason, nonce, since) | — |
| `pauseHistory: Map<Long, Long>` | Relayer id → time of its last pause | per relayer |
| `blocked`, `blockedAt`, `blockDepositLimit` | Permanent block; `blockDepositLimit` attested after the vault block (H6) | — |
| `migration` | New contract, new vault, effective time | — |
| `slashReserveCs` | Confiscated CS | — |
| `vaultView` | Last values attested by `T` relayers: `userUsdt`, `nextDepositId`, signer-set nonce applied, block flag, bond ledger | fixed |

`PendingMint` data = `(to, amount, maxCsPrice, bscTxHash)`; its hash is
`keccak256(depositId, to, amount, maxCsPrice, bscTxHash)` over a fixed encoding.

### 5.2 Records instead of events

Credits has no event log. Every action that relayers or the claim page must read is recorded in
contract state under a sequential id and exposed by `@Getter` methods:

- withdrawals by id (`getWithdrawal(id)`, `getWithdrawalsFrom(id, count)`) while in the recent
  window; afterwards relayers' published copies and `getWithdrawalRoot(bucket)`;
- relayer records and the active set (`getRelayers()`, `getSignerSet(nonce)`);
- proposals, pause state, epochs, the order book (`getAsks(count)`, `getBids(count)`).

### 5.3 Relayer record

| Field | Meaning |
|---|---|
| `id` | Sequential |
| `nodeWallet`, `operator`, `ownerWallet` | [§4.1](#41-identities-of-a-relayer) |
| `bscSigner` | Current signer key; every past key stays in `signerHistory` |
| `signatureUrl` | HTTPS base URL where it publishes signatures and digests |
| `status` | `Applied`, `Active`, `Inactive`, `Exiting`, `Exited`, `Slashed`, `Rejected` |
| `founder` | Applied while the founder phase was open |
| `bondCs` | CS held by this contract |
| `bondCusdt` | cUSDT locked in this contract (entry requirement only) |
| `bondUsdtOnBsc` | USDT on the vault attested by `T` relayers (entry requirement only) |
| `bondRequired` | Value required at entry, fixed |
| `appliedAt`, `activatedAt`, `exitAt`, `removedFromVaultAt` | Times; `removedFromVaultAt` set from the attested vault signer-set nonce (C2) |
| `exitNonce` | Signer-set nonce of the first set without this relayer |
| `eligibleSince`, `ineligibleSince` | Delegation status from attestations |
| `version` | Last version hash used |
| `participation`, `orphans`, `divergences` | Counters for the current windows |

### 5.4 Methods

Caller column: **U** any wallet, **R** operator of an active relayer, **W** node wallet of the
relayer concerned, **A** anyone. All amounts are `BigDecimal` (Variant `v_big_decimal`), ids are
`long`, addresses and hashes are `String`. The state in which each method is open is in
[§5.12](#512-methods-by-contract-state).

#### Token (standard v1)

| Method | Caller | Rules |
|---|---|---|
| `getName()`, `getSymbol()`, `getDecimal()`, `totalSupply()`, `balanceOf(owner)`, `allowance(owner, spender)` | A | `@Getter` |
| `transfer(to, amount)` | U | Positive, ≤ 8 decimals, ≤ balance; `to` a valid Credits address ≠ this contract |
| `transferFrom(from, to, amount)` | U | As `transfer`, within allowance |
| `approve(spender, amount)` | U | Sets the allowance (not additive) |
| `burn(amount)` | U | Always throws "use burnForBsc" |
| `setFrozen(frozen)` | U | Always throws: no admin |
| `register()` | U | No-op |
| `payable(amount, userData)` | U | [§5.5](#55-incoming-cs-payable) |

#### Bridge

| Method | Caller | Rules |
|---|---|---|
| `approveMint(depositId, to, amount, maxCsPrice, bscTxHash, version)` | R | [§5.7](#57-mint-approval-counting); `depositId < vaultView.nextDepositId + 256` and `< mintedBelow + 1024`; if blocked and `blockDepositLimit` is attested, `depositId < blockDepositLimit`. Returns `pending k`, `minted`, `done`, `mismatch` |
| `deliverCs(wallet)` | A | Sends `csClaimable[wallet]` to `returnAddress(wallet)` in one emitted transfer (≤ 10⁸ CS); the caller pays the emitted transfer's fee through its `max_fee` (M8) |
| `claimCs()` | U | `deliverCs(initiator)` |
| `burnForBsc(amount, bscAddress)` | U | Not paused; `amount ≥ minWithdrawal`; `bscAddress` valid, not zero, not the vault. `bridgeFee` to the fund, burns `amount − bridgeFee`, records withdrawal `kind=0`. Returns the id |
| `migrate(amount, newCreditsAddress, fallbackBscAddress)` | U | Migration target effective; as `burnForBsc` with `kind=1`, recipient = registered new vault, `creditsTo` = `newCreditsAddress`, `fallback` = the user's own BSC address (H7); no bridge fee |
| `getWithdrawal(id)`, `getWithdrawalsFrom(id, n)`, `getWithdrawalRoot(bucket)` | A | `@Getter` |

#### Relayers

| Method | Caller | Rules |
|---|---|---|
| `applyRelayer(operator, ownerWallet, bscSigner, signatureUrl, version)` | W | Not blocked; not already a relayer; `bscSigner` never registered before (M1); ≤ 64 non-exited relayers; bond already paid by the same wallet ([§5.5](#55-incoming-cs-payable) `bond`, and `lockCusdt`) covering `bondRequired` computed now ([§5.10](#510-bond-required-at-entry)); founder if the founder phase is open. Status `Applied` |
| `lockCusdt(amount)` | W | Moves cUSDT from the caller's balance into its `bondCusdt` |
| `attest(period, kind, payload, version)` | R | Attestations of facts the contract cannot read ([§5.8](#58-attestations)): eligibility, payee lists, vault view, signer set applied, block limit, bond on BSC |
| `objectApplication(relayerId)` | R | Per [§14](#14-open-decisions) D3; current text: during the 7-day wait, one third of active relayers (rounded up) reject the application; the bond is then withdrawable after 7 days (L2) |
| `activate(relayerId)` | A | After 7 days, eligibility and bond attested, not rejected, `N < 64`. Status `Active`; a new signer set is recorded |
| `setOperator(op)`, `setSignatureUrl(url)`, `setOwnerWallet(w)`, `setReturnAddress(addr)` | W | Immediate |
| `rotateSigner(bscSigner)` | W | New key never registered before; the old key stays in `signerHistory` and stays provable while any bond of this relayer is held; a new signer set is recorded |
| `leave()` | W | Not paused (C1); status `Exiting`; a new signer set is recorded; `exitAt = now`, `exitNonce` = its nonce |
| `withdrawBond()` | W | Not paused (C1); status `Exiting`, `Inactive`-and-leaving or `Rejected`; `now ≥ exitAt + 30 days + Σ pauses it started`; `vaultView` shows a signer set with nonce ≥ `exitNonce` applied on the vault and `now ≥ removedFromVaultAt + 30 days` (C2); if blocked, the end-of-life rule of [§8.10](#810-permanent-block-migration-and-end-of-life). Credits `bondCs` to `csClaimable`, `bondCusdt` to the balance; marks `Exited` |
| `submitDigest(period, digestHash, version)` | R | Once per relayer per period ([§7.6](#76-state-digests)) |
| `updateStatus(relayerId)` | A | Applies inactivity, delegation-drop and divergence rules ([§8.6](#86-inactivity-delegation-drop-divergence)) |
| `proveFalseSignature(id, kind, to, amount, creditsTo, fallback, sigHex, merklePath)` | A | Every state (C1); [§8.8](#88-slashing-by-proof) |

#### Order book

| Method | Caller | Rules |
|---|---|---|
| (`payable`, command `ask`) | U | Places an ask: CS escrowed |
| `placeBid(cusdtAmount, price)` | U | Escrows cUSDT from the caller's balance; minimum 0.10 cUSDT and the order limits of [§5.1](#51-state) |
| `cancelAsk(id)`, `cancelBid(id)` | owner of the offer | CS to `csClaimable` of the owner; cUSDT back to the balance |
| `buy(maxCusdt, maxPrice)` | U | Takes asks from the lowest price, then oldest; spends at most `maxCusdt` including the swap fee; `maxPrice` 0 = no limit (the caller's own choice); stops after 50 fills and returns the unspent rest. CS to the caller's `csClaimable` |
| (`payable`, command `sell`) | U | Sells the CS paid into bids from the highest price; see [§5.5](#55-incoming-cs-payable) |

#### Rewards and governance

| Method | Caller | Rules |
|---|---|---|
| `buybackTick()` | A | At most once per hour slot; spends at most the slot budget ([§8.4](#84-fees-buyback-and-rewards)) |
| `closeEpoch()` | A | After the epoch end; allocates the CS bought in the epoch; resumable ([§8.4](#84-fees-buyback-and-rewards)) |
| `propose(kind, key, value)` | R | Kinds: parameter, admit/retire version, conservative CS price, vault cap, permanent block, migration target, conflict resolution. Rejected if outside the hard caps |
| `vote(proposalId, yes)` | R | One vote per active relayer; changeable until the voting end |
| `execute(proposalId)` | A | [§8.7](#87-governance) timing; pass condition re-checked at execution |
| `pause(reason)` | R | Within the pause limits of [§8.9](#89-pause-and-unpause) |
| `approveUnpause(nonce, unfounded)` | R | At `U` approvals the pause ends; `unfounded` true from at least `U` marks the pauser ([§8.9](#89-pause-and-unpause)) |

### 5.5 Incoming CS (`payable`)

`payable(amount, userData)` runs when a wallet transfers CS to the contract. `userData` is the
transaction's text user field (`cs::trx_uf::ordinary::Text`, id 1) passed as bytes. A `payable`
that throws makes the node return the CS to the sender ([§13.1](#131-verified)), so every invalid
payment MUST throw.

Grammar (UTF-8, at most 128 bytes, fields separated by `|`, decimals with `.` and no exponent,
addresses base58):

| Command | Meaning |
|---|---|
| `bond` | Adds `amount` to the sender's relayer bond (`bondCs`) |
| `ask|<price>` | Places an ask of `amount` CS at `price`; minimum 10 CS |
| `sell|<minPrice>` | Sells into bids from the highest price, not below `minPrice` (0 = any), at most 50 fills; the unsold CS go to the sender's `csClaimable` |

Rules: `amount` positive with at most 6 decimals and at most 10⁸ CS; the contract not paused
(except `bond`, refused while paused too: C1) and not blocked; anything else MUST throw.

### 5.6 Outgoing CS

CS leaves only through `deliverCs`, in one emitted `sendTransaction(contractAddress, to,
amount)` per call, to the wallet's return address. Mints, purchases, sells, cancels, rewards and
bond releases only credit `csClaimable` (M8): a failing emitted transfer can never block a mint
or a trade.

- The emitted transfer's fee is charged to the caller of `deliverCs` through the `max_fee` of its
  call (`solver/src/smartcontracts.cpp` prevalidation, `walletscache.cpp`). Relayers call
  `deliverCs` for new depositors, who have no CS yet, with `max_fee` ≥ 0.03 CS.
- A return address that is a contract makes the emitted transfer a violation and the call fails;
  the CS stay claimable and the owner sets another return address.
- Amounts are rounded down to 6 decimals and to at most 10⁸ CS before the `double` conversion;
  after the conversion the contract checks `BigDecimal.valueOf(d) ≤ intended` and otherwise
  lowers by one unit (L1). The difference stays claimable.
- **No memo**: the node drops user data on contract-emitted transactions
  ([§13.1](#131-verified)). Return addresses MUST be wallets the owner controls; the UI MUST
  warn against exchange deposit addresses that need a memo.

### 5.7 Mint approval counting

At each `approveMint` by relayer `r` for `(depositId, data)` (H1):

1. Ignore if `depositId` is minted (`done`, counted for participation within 10 minutes of the
   mint).
2. Record `r`'s approval under `hash(data)`. A relayer approving two different hashes for one id
   gets an orphan mark; only its first approval counts.
3. Count, for that hash, approvals from relayers that are `Active` at this call (approvals of
   relayers that became `Inactive`, `Exiting` or `Slashed` since are dropped).
4. When the count reaches `T` (evaluated now): mint ([§5.7.1](#571-mint-and-conversion)).
   Approvals for other hashes of that id become orphans for their approvers.
5. If, for an id already minted, another hash later collects `T` approvals: automatic pause with
   reason `mint-mismatch`, since `T` relayers disagree with `T` others.
6. Pending entries older than 30 days without reaching `T` are dropped lazily; their approvers
   get no mark (the deposit may still be minted later by fresh approvals).

#### 5.7.1 Mint and conversion

For deposit `(id, to, A, maxCsPrice)`:

1. `fee = bridgeFee`; `net = A − fee` (the vault's `minDeposit` keeps `net > 0`).
2. `budget = min(conversionRate × net, conversionMax)`; if `budget < conversionMin` and
   `net ≥ 10 × conversionMin`, `budget = conversionMin`; for smaller deposits the budget is the
   rate alone (M3).
3. Take asks from the lowest price, oldest first, not above `maxCsPrice` if set (no other price
   limit, decision D1), spending at most `budget`
   including the swap fee, at most 50 fills.
4. Mint `A`: `fee` and the swap fee to `buybackFund`, the cUSDT paid to the sellers' balances,
   the rest to `to`; CS bought to `csClaimable[to]`.
5. Mark the id minted; update `mintedBelow`/`mintedAbove`.

The mint never fails because of the order book or of a CS delivery.

### 5.8 Attestations

The contract cannot read BSC nor delegations. Facts it needs are attested by relayers with
`attest(period, kind, payload, version)`; a fact is accepted when `T` active relayers have
submitted the same `(period, kind, payload)` (underspecified 2, 7):

| Kind | Payload | Period |
|---|---|---|
| `vault` | `userUsdt`, `nextDepositId`, applied signer-set nonce, `withdrawOnly`, `nextDepositId` at block, bond ledger hash | digest period; values at the BSC finalized block with the greatest timestamp ≤ period start |
| `eligibility` | relayer id, eligible (bool) | the day; delegations read at the Credits block with the greatest time ≤ day start |
| `payees` | relayer id, list of ≤ 100 `wallet:amount` of the largest counted delegators, rounded down to whole CS | the epoch; read at the epoch start block |
| `bscBond` | node wallet, USDT bond on the vault | when it changes |

If `T` identical payee lists are not reached by the epoch close, the relayer's whole share goes
to its owner wallet for that epoch. Payloads are capped at 4 KB.

### 5.9 Order matching

- Asks by price ascending then id; bids by price descending then id. Tick 10⁻⁸ cUSDT.
- A buyer pays `qty × price` per fill, rounded up to 8 decimals, plus `swapFee` of the total,
  rounded up. CS quantities are rounded down to 6 decimals. A fill that would give less than
  0.000001 CS stops the order.
- A seller into bids receives `qty × price − swapFee`, rounded down.
- `lastPrice` = price of the last fill; `dailyStats` roll at UTC day boundaries of block time;
  the 7-day VWAP uses the last 7 complete days.
- At most 50 fills per call; the rest of the order is returned unspent.
- The founder phase closes at the first single `buy` (not a conversion, not the buyback) in which
  the buyer paid ≥ 100 cUSDT in total and the buyer differs from every seller filled; or 6 months
  after deploy; or when there are 7 active relayers; whichever comes first.

### 5.10 Bond required at entry

Computed when `applyRelayer` is called and fixed for that relayer:

- founder phase open: 100,000 CS in `bondCs` **and** 50 USDT on the vault;
- otherwise: 50 USDT on the vault, plus CS, cUSDT and/or more USDT such that
  `bondCs × entryPrice + bondCusdt + bondUsdtOnBsc ≥ max(1000, newBondRate × vaultView.userUsdt)`,
  where `entryPrice = min(conservativePrice, 7-day VWAP)` (H5).

A later rise of the requirement never applies to existing relayers. For the cap bound
([§3.3](#33-what-is-not-protected)) only `bondCs` counts, at the current conservative price.

### 5.11 Bounded state and work

- Every collection has a bound in [§5.1](#51-state); a call that would exceed it throws.
- Work per call: at most 50 fills, 50 lazy updates, 100 reward allocations, one emitted transfer.
- Long jobs (an epoch close with many relayers) are resumable: a second call continues.
- Withdrawal records: when 2,048 records are kept, the oldest bucket of 1,024 is compacted into
  its Merkle root (leaves = `hashStruct(Claim)` in id order, keccak256, sorted-pair-free binary
  tree, odd leaf promoted). Relayers and the claim page keep and publish the full records.
- Hard invariant: the serialised state stays below 1 MB, and a call at maximum state completes in
  under 1 s on the reference machine, well below the 4 s the node waits for the executor
  ([§13.1](#131-verified)). Measured before the design is frozen ([§12.1](#121-executor-harness-no-node)).

### 5.12 Methods by contract state

(underspecified 4)

| Method | Normal | Paused | Blocked | Blocked + migration |
|---|---|---|---|---|
| `transfer`, `transferFrom`, `approve` | yes | yes | yes | yes |
| `approveMint` | yes | no | yes, ids < `blockDepositLimit` once attested | same |
| `burnForBsc` | yes | only net amounts below `delayThreshold` (D2) | yes | yes |
| `migrate` | — | no | — | yes |
| `deliverCs`, `claimCs`, `setReturnAddress` | yes | yes | yes | yes |
| `payable` `ask`/`sell`, `placeBid`, `buy` | yes | no | no | no |
| `payable` `bond`, `applyRelayer`, `activate` | yes | no | no | no |
| `cancelAsk`, `cancelBid` | yes | yes | yes | yes |
| `leave`, `withdrawBond` | yes | no | yes (end-of-life rule) | yes |
| `proveFalseSignature` | yes | yes | yes | yes |
| `attest`, `submitDigest`, `updateStatus` | yes | yes | yes | yes |
| `propose`, `vote`, `execute` | yes | yes (only risk-lowering kinds execute) | yes | yes |
| `buybackTick` | yes | no | yes | yes |
| `closeEpoch` | yes | allocation of what was bought | yes | yes |
| `pause`, `approveUnpause` | yes | yes | yes | yes |

### 5.13 Errors

Methods throw `IllegalStateException` with a stable message prefix (`paused`, `blocked`,
`not relayer`, `version`, `mismatch`, `amount`, `address`, `bond`, `cap`, `time`, `proof`,
`limit`). A failed call keeps the previous state and emits nothing (verified in the executor
harness).

### 5.14 Bootstrap

(underspecified 15) The constructor takes the initial relayers (node wallet, operator, owner
wallet, BSC signer, URL), all founders, `Active` from deploy, with bonds due within 30 days: a
founder whose bond is not paid by then becomes `Inactive`. The vault is deployed with the same
signers and founders. Both deploy transactions and the initial list are published with the
release.

---

## 6. BSC contract `UsdtVault`

Solidity ≥ 0.8.24, no proxy, no owner. Uses OpenZeppelin `SafeERC20`, `ECDSA`, `EIP712`,
`ReentrancyGuard`. Constructor: USDT token address, initial signers and founders, initial cap and
daily cap, Credits contract address (informational).

### 6.1 State

| Field | Meaning |
|---|---|
| `usdt` | Token |
| `signers: address[]`, `isSigner`, `signerNonce` | Current signer set, sorted; nonce of the last applied set |
| `removedAt[address]` | Time a signer left the set (C2) |
| `threshold()` | `max(2, min(n/2 + 1, 7))` |
| `unpauseThreshold()` | `max(threshold(), ceil(2n/3))` |
| `founders`, `isFounder`, `foundersFrozen` | Founder set; only shrinks once frozen |
| `foundersInSet()` | Founders that are signers |
| `whitelist`, `isWhitelisted` | Trusted signers for immediate large claims |
| `foundersBelowTwoSince` | Time `foundersInSet()` fell below 2 (0 otherwise) |
| `nextDepositId` | Sequential |
| `userUsdt` | User funds: deposits − claims − migrations |
| `bondUsdt[bytes32 nodeWallet]`, `bondSigner[bytes32]` | Relayer bonds apart from user funds, and the signer key of each bond |
| `reserveUsdt` | Slashed bonds |
| `claimed[uint64]` | Withdrawal ids paid or queued |
| `queue` | FIFO of queued claims `(id, to, amount, kind, creditsTo, fallback, unlockTime)` |
| `cap`, `pendingCap`, `pendingCapTime` | Vault cap on `userUsdt` |
| `dailyCap`, `pendingDailyCap`, `pendingDailyCapTime` | Rolling 24-h claim cap |
| `window` | Claims of the last 24 h, as hourly buckets (L4) |
| `undelayedWindow` | Claims without a whitelist majority in the last 24 h, hourly buckets (H3) |
| `paused`, `pausedBy`, `lastPauseBy[address]`, `withdrawOnly`, `blockedDepositId` | |
| `migrationTarget`, `migrationTime` | New vault, effective time |
| `nonces[kind]` | Replay protection per message kind |

### 6.2 EIP-712

Domain: `EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)` with
`name = "CreditsUsdtVault"`, `version = "1"`. Type strings, exactly (underspecified 1):

| Type string |
|---|
| `Claim(uint64 withdrawalId,uint8 kind,address to,uint256 amount,bytes32 creditsTo,address fallback)` |
| `SignerSet(uint64 nonce,address[] signers,address[] foundersToAdd,bool freezeFounders)` |
| `FounderRemoval(uint64 nonce,address founder)` |
| `Whitelist(uint64 nonce,address[] whitelist)` |
| `Cap(uint64 nonce,uint256 cap,uint256 dailyCap)` |
| `BondRelease(uint64 nonce,bytes32 nodeWallet,address to,uint256 amount)` |
| `BondSlash(uint64 nonce,bytes32 nodeWallet)` |
| `Pause(uint64 nonce,uint64 deadline)` |
| `Unpause(uint64 nonce,bool unfounded)` |
| `Block(uint64 nonce)` |
| `Migration(uint64 nonce,address target)` |

Java encoding of `hashStruct(Claim)` (used for the stored hash and in proofs):
`keccak256(typeHash ‖ pad32(withdrawalId) ‖ pad32(kind) ‖ pad32(to) ‖ pad32(amountWei) ‖
creditsTo ‖ pad32(fallback))`, each `pad32` big-endian left-padded to 32 bytes, `to` and
`fallback` the 20-byte address (zero for `kind 0` fallback), `creditsTo` the 32-byte key (zero for
`kind 0`), `amountWei = units × 10¹⁰`. The digest is `keccak256(0x19 0x01 ‖ domainSeparator ‖
hashStruct)`. Test vectors are generated from the Solidity contract and checked in Java.

Signatures are 65-byte `(r, s, v)`, low-`s` only, passed sorted by signer address with no
duplicates; every signer MUST be in the current signer set.

### 6.3 Methods

| Method | Who | Rules |
|---|---|---|
| `deposit(amount, creditsTo, maxCsPrice)` | user | Not paused, not `withdrawOnly`; `signers.length ≥ 3` (L5); `amount` multiple of 10¹⁰ and ≥ `minDeposit`; `creditsTo ≠ 0`; `userUsdt + amount ≤ cap`. Pulls USDT measuring the balance delta. Emits `Deposit(id, from, amount, creditsTo, maxCsPrice)` |
| `claim(Claim, sigs)` | anyone | Not paused, except a `kind 0` claim below `delayThreshold` within the daily cap, which is paid also while paused (D2); not claimed; `threshold()` valid signatures; `kind 1` rules below. If the rolling daily cap would be exceeded, the claim is queued (M4) instead of reverting. If the signatures include fewer than `floor(W/2)+1` whitelisted signers (`W` = whitelisted members of the signer set; `W = 0` always counts as fewer) and `undelayedWindow + amount > delayThreshold`, it is queued for 24 h (H3). Else paid. Marks `claimed[id]` |
| `executeQueued(count)` | anyone | Not paused; pays queued claims in FIFO order whose unlock time has passed, within the daily cap |
| `updateSigners(SignerSet, sigs)` | anyone | `threshold()` of the current signers; `nonce = signerNonce + 1`; new set non-empty, sorted, ≤ 64; sets `removedAt` for removed signers; `foundersToAdd` only while not `foundersFrozen`, each in the new set; `freezeFounders` sets `foundersFrozen`. Founders leave the founder set only by their own `FounderRemoval` or a matured removal |
| `requestFounderRemoval(FounderRemoval, sigs)` | anyone | Signed by the founder alone: immediate. Signed by `threshold()` instead: effective after 30 days unless cancelled by a majority of founders |
| `setWhitelist(Whitelist, sigs)` | anyone | Normal mode: a majority of `foundersInSet()`, immediate. Fallback mode (`foundersBelowTwoSince` older than 30 days): more than half of all signers, effective after 7 days |
| `setCap(Cap, sigs)` | anyone | `threshold()` signatures. Decreases immediate. Increases after 7 days, at most ×2 per step, for `cap` and `dailyCap` both. Always `dailyCap ≤ cap / 5`. While `foundersInSet() ≥ threshold()`: `cap ≤ 20,000 USDT` (H4) |
| `depositBond(nodeWallet, signer, amount)` | relayer | Adds to `bondUsdt[nodeWallet]`, records `bondSigner`; not counted in `userUsdt` or the cap |
| `releaseBond(BondRelease, sigs)` | anyone | `threshold()` signatures; `bondSigner[nodeWallet]` not a signer and `removedAt + 30 days` passed (C2, L9); pays `to` |
| `slashBond(BondSlash, sigs)` | anyone | `threshold()` signatures; moves the bond to `reserveUsdt` |
| `pause(Pause, sig)` / `pauseDirect()` | one signer | `deadline` not passed (L6); limits of [§8.9](#89-pause-and-unpause) |
| `unpause(Unpause, sigs)` | anyone | `unpauseThreshold()` signatures |
| `block(Block, sigs)` | anyone | `threshold()` signatures. Sets `withdrawOnly` forever; records `blockedDepositId = nextDepositId` |
| `setMigration(Migration, sigs)` | anyone | `threshold()` signatures; only while `withdrawOnly`; effective after 7 days; target a contract |

`kind 1` claims (migration): paid to `migrationTarget` through
`IUsdtVault(target).depositFromMigration(amount, creditsTo)` after `migrationTime`. If the target
is unset, paused, reverts, or the claim has not been executed 30 days after it became claimable,
it is paid to `fallback` as a normal claim (H7). The new vault's `depositFromMigration` MUST
accept calls only from its registered predecessor and MUST pull the USDT with `transferFrom`
measuring the balance delta (M9).

No function transfers user USDT except `claim`/`executeQueued`.

### 6.4 Reentrancy and tokens

USDT on BSC (`0x55d3…7955`) has no transfer fee and no callbacks; the vault still uses
`nonReentrant` on every external function that moves tokens, and checks balance deltas on
deposits.

---

## 7. Relayer process

### 7.1 Components

- Credits client: Thrift API of the operator's own node (never a shared gateway).
- BSC client: at least 2 independent RPC providers, queried for the same `finalized` block; a
  disagreement on a block hash or a log stops the cycle and raises an alarm.
- Signer: holds the operator key and the BSC signer key ([§7.8](#78-keys)).
- Publisher: writes signed withdrawals, full withdrawal records and digests as static JSON under
  `signatureUrl`.
- Store: a local database with cursors and the history of what was signed.

### 7.2 Cursors

| Cursor | Meaning |
|---|---|
| `nextDepositToRead` | Next BSC deposit id to process |
| `nextWithdrawalToSign` | Next Credits withdrawal id to sign |
| `signedWithdrawals[id] = (data hash, Credits block)` | Never sign two different data for one id |
| `approvedDeposits[id] = data hash` | Never approve two different data for one id |
| `digestPeriod`, `attestations` | Last digest and attestations submitted |

Every cursor and record is written to the store before the corresponding action is sent
("submitted" first), so a restart never repeats an action with different data.

### 7.3 Deposit loop

1. Read `finalized` from each BSC source; use the lowest common block whose hash all sources agree on.
2. Read `Deposit` logs of the vault up to that block; index by `id`; require ids to be
   contiguous from `nextDepositToRead`. A gap means a source is incomplete: retry, never skip.
3. For each new id, check on Credits that it is not minted, then call `approveMint` with
   `max_fee` ≥ 0.03 CS. If the call fails for a reason other than `done`, retry later.
4. Advance the cursor only after the approval is recorded on Credits or the id is minted.
5. After a mint, call `deliverCs(to)` for the depositor if `csClaimable[to] > 0` and the
   depositor has no CS.

### 7.4 Withdrawal loop

1. Read withdrawals from Credits by id, starting at `nextWithdrawalToSign`, only from blocks at
   least `creditsConfirmations` deep (initial 30, to be set from measured Credits reorganisation
   depths: TO VERIFY), only while the node is in sync (last block time within 60 s of the wall
   clock) and not in an uncertain or fork state (M2). The block of a `burnForBsc` is found with
   `TransactionsGet` on the contract and the transaction's `poolNumber`.
2. Check the record against the contract's stored hash; build `Claim`; sign; store with the
   block; publish `/<chainId>/<vault>/claims/<id>.json` with the data, the signature, the block
   and the version.
3. Never sign while the Credits contract is paused, or if the watchdog fails.

### 7.5 Watchdog, every cycle

Invariant I1: `cUSDT totalSupply + Σ net amounts of withdrawals not claimed on the vault ≤
userUsdt`. Bonds and the reserve are counted apart. Also: no mint without a matching finalized
deposit; no claimed withdrawal id without a Credits record with the same hash; vault signer set
equal to the Credits active set (after the latest update); queued claims on the vault match
Credits records. On any failure: pause both contracts, publish the evidence, stop signing.

### 7.6 State digests

(M7) Every digest period (1 hour), the contract takes at the first call of the period a snapshot
of its own `totalSupply`, `nextWithdrawalId`, signer-set nonce and mint watermark. Each relayer
submits `hash(period, snapshot values, BSC values at the finalized block with the greatest
timestamp ≤ period start, invariantOk)` and publishes the clear values. The contract counts the
most common digest; a relayer whose digest differs from one that has at least `T` submitters
gets a divergence mark.

In the same loop each relayer calls `buybackTick()` once per hour slot if no one has yet (a
second call in the slot is refused cheaply), and `closeEpoch()` after the epoch end.

### 7.7 Code verification

1. **Admitted versions.** The relayer is published as source with reproducible builds; the hash
   of each release is admitted by governance. Approvals, attestations and digests carry the
   version hash; the contract refuses unadmitted versions. A retired version stays valid for
   14 days. An urgent version is admitted immediately when more than half of active relayers
   vote yes and `T` of them already run it (L7). This coordinates upgrades; it does not prove
   what runs.
2. **Consensus on outputs.** Honest relayers compute the same data from the same chains; the
   contract mints on identical approvals and compares digests.
3. **Automatic consequences.** Divergence in 3 of the last 24 digest periods, or more than 3
   orphan approvals in 7 days → `Inactive` until back in line. A relayer made `Inactive` by
   divergence keeps its pause right and stays in the vault signer set for 7 days (M7). No
   slashing without proof.
4. **Later option.** Remote attestation of the binary on TEE hardware (Intel TDX, AMD SEV).

### 7.8 Keys

- Keys never appear in code, repositories or logs. Files mode `0600`, owned by the relayer user.
- The BSC signer key is used only for EIP-712 signatures; the relayer needs no BNB.
- The operator key MAY differ from the node wallet; the node wallet only registers, rotates and
  withdraws bonds and can be kept offline.

### 7.9 Restarts

On start: reload cursors; re-read every withdrawal signed in the last 24 hours and check the
published file matches the stored hash and that its Credits block is still in the chain;
re-check pending approvals. A crash between storing and sending repeats the same data, which the
contracts treat as a duplicate.

---

## 8. Flows

### 8.1 Deposit (BSC → Credits)

1. User approves USDT and calls `deposit(100 USDT, creditsTo, maxCsPrice=0)` on the vault.
2. Each relayer, after finality (≈ 1 s), calls `approveMint(id, to, 100, 0, txHash, version)`.
3. At `T` approvals for the same data: fee 0.05 to the fund; conversion budget = 2 % × 99.95 =
   1.999 cUSDT; CS bought from the lowest asks to `csClaimable[to]`; the rest credited as cUSDT.
4. A relayer calls `deliverCs(to)`: the CS reach the user's wallet.
5. Approvals after the mint return `done` and count for participation within 10 minutes.

### 8.2 Withdrawal (Credits → BSC)

1. User calls `burnForBsc(100, 0xBob)`: 0.05 to the fund, 99.95 burned, withdrawal `id` recorded.
2. Relayers sign `Claim(id, 0, 0xBob, 99.95e18, 0, 0)` once its block is deep enough, and publish.
3. The claim page fetches `T` signatures and Bob sends `claim`. Without a whitelist majority among
   the signatures and above the rolling 1,000 USDT, it is queued for 24 hours, then
   `executeQueued`. Above the daily cap it is queued until the window allows it.

### 8.3 Swap

- Ask: Carol sends 10,000 CS with user data `ask|0.01` → ask id.
- Buy: Alice calls `buy(101, 0)`; she pays 100 cUSDT to Carol's balance plus 0.1 fee to the fund;
  10,000 CS go to her `csClaimable`; she calls `claimCs()`.
- Bid and sell are the mirror image, with the fee taken from the seller's proceeds.

### 8.4 Fees, buyback and rewards

1. Bridge fees and swap fees accumulate in `buybackFund` (cUSDT).
2. The buyback is spread over the epoch (decision D1: no price limit, small slices). At the start
   of an epoch (7 days = 168 hour slots) the contract fixes `epochFund = buybackFund` and
   `sliceBudget = epochFund / 168`; fees arriving during the epoch wait for the next one.
   `buybackTick()`, callable by anyone at most once per hour slot (by block time), buys CS from
   the lowest asks, oldest first, for at most `sliceBudget` (no fee on the buyback), at most 50
   fills; an unspent slice (no asks, or fewer asks) stays in `buybackFund`. Relayers call it as
   part of their loop ([§7](#7-relayer-process)). One manipulated slot can capture at most 1/168
   of the epoch's fund, and other sellers have an hour to place lower asks.
3. At `closeEpoch()` (every 7 days) the contract splits the CS bought during the epoch equally
   among relayers active for the whole epoch with ≥ 80 % participation.
3. Participation (underspecified 6) = approvals of the epoch's minted deposits within 10 minutes
   of the mint, plus digests submitted, over the number of both; an epoch without deposits
   counts digests only.
4. Each relayer's share: `ownerShare` (20 %) to its owner wallet, the rest to the payees attested
   for that epoch ([§5.8](#58-attestations)) pro rata; the remainder to the owner. Credited to
   `csClaimable`.
5. Whatever the slices did not spend carries over to the next epoch's fund.

### 8.5 Relayer admission

1. Node wallet pays the CS bond (`bond` command), and on BSC `depositBond(nodeWallet, signer, 50)`.
2. Node wallet calls `applyRelayer(...)`.
3. Each relayer's software reads the candidate's delegations from its own node at the day's
   reference block (`DelegatedItem`: `wallet`, `sum`, `validUntil`, `fromTime`, `coeff`) and
   attests eligibility:
   - counted: incoming delegations with `coeff = 4` (`Anni`, a term of at least ≈ 364 days,
     [§13.1](#131-verified)), `validUntil > now + 30 days`, from wallets other than the node
     wallet and the declared owner wallet;
   - total counted ≥ 1,000,000 CS; at least 2 distinct donors; no donor above 70 % of the total;
   - warning only (not blocking): donors linked to each other or to the owner by direct
     transfers in the last 6 months.
4. 7-day wait (objection: [§14](#14-open-decisions) D3).
5. `activate`. The relayers sign the new `SignerSet`; anyone submits it to the vault.

### 8.6 Inactivity, delegation drop, divergence

- Participation below 50 % over 14 days → `Inactive`.
- Eligibility attested false for 30 consecutive days → `Inactive`. Back above → `Active` again
  with the same bond.
- Divergence and orphan rule of [§7.7](#77-code-verification).
- `Inactive` relayers are out of `N` and `T`; they leave the vault signer set at the next
  `SignerSet` (7 days after the change for divergence); they may `leave()` and recover the bond
  under the rules of `withdrawBond`, or return to `Active` when the condition clears.

### 8.7 Governance

(M5)

- `votingEnd = created + 14 days`. `passedAt` is recorded at the first call (vote or execute)
  where yes > half of the active relayers at that moment.
- Executable in `[max(passedAt, votingEnd) + 7 days, + 21 days]`, re-checking yes > half of the
  active relayers at execution. A change of `N` during the vote is taken into account at
  execution only.
- Immediate when it only lowers risk: lowering the vault cap, the daily cap or the conservative
  price, retiring a version (with its 14-day grace), a permanent block. These execute as soon as
  `passedAt` is set.
- Hard caps are checked at proposal and at execution.
- Changes needing the vault (cap, block, migration) are then signed by `T` relayers.
- Conflict resolution (a deposit id whose mint is in `mint-mismatch`): the proposal must carry the
  data attested by `T` relayers; it cannot introduce data no relayer approved.

### 8.8 Slashing by proof

`proveFalseSignature(id, kind, to, amount, creditsTo, fallback, sig, merklePath)`, callable in every
state (C1):

1. Compute the EIP-712 digest of `Claim` with the vault's domain; recover the signer
   (pure-Java secp256k1, low-`s`).
2. The signer must be a key in `signerHistory` whose relayer still holds any bond on Credits
   (M1).
3. The signature is false if:
   - `id ≥ nextWithdrawalId + 64` (a margin beyond any plausible reorganisation, M2); or
   - `id` is in the recent window and `hashStruct` differs from the stored hash, and the stored
     record is older than `creditsConfirmations` blocks; or
   - `id` is in a compacted bucket and `merklePath` proves a different leaf for `id`.
4. Then: status `Slashed`, out of the active set, a new signer set recorded; `bondCs` to the
   slash reserve minus `proverShare` (10 %) to the prover's `csClaimable`; `bondCusdt` burned
   from supply and, since it is backed by vault USDT, the matching USDT moved to the vault reserve
   by `T` signatures; the relayers sign `BondSlash` for the BSC bond. The prover's wallet must
   not be the slashed relayer's.

An honest relayer whose signed record was removed by a reorganisation deeper than
`creditsConfirmations` defends with the published file and block; such an event pauses the
bridge through the watchdogs. Other signed messages (`SignerSet`, `Cap`, `BondRelease`) are not
provable this way in version 1.

### 8.9 Pause and unpause

Decision D2 (2026-11-06): a pause started by one relayer stops everything except small
withdrawals, so a false alarm never locks users out.

- Any relayer pauses Credits (`pause`) and BSC (`Pause` signature with a deadline of at most 1
  hour, or `pauseDirect`). While paused, the methods of [§5.12](#512-methods-by-contract-state)
  apply. Small withdrawals continue: on Credits `burnForBsc` stays open for a net amount below
  `delayThreshold` (1,000 USDT), and relayers keep signing those withdrawals; on BSC `claim`
  stays open for `kind 0` claims with `amount < delayThreshold`, within the rolling daily cap and
  without the queue. Deposits, mints, larger burns and claims, queued claims and `kind 1`
  (migration) claims stop.
- Cost of this choice: during a pause a colluding threshold can still be paid small false claims
  up to the daily cap (2,000 USDT per 24 h by default) until the unpause decision or the proofs
  act; the daily cap is the bound.
- A relayer that paused cannot pause again for 7 days on either chain; its own bond lock is
  extended by the length of every pause it started (C1).
- Unpause needs `U = max(T, ceil(2N/3))` approvals on Credits and `unpauseThreshold()`
  signatures on BSC (H3). If at least `U` declare the pause unfounded, the pauser becomes
  `Inactive` for 30 days and cannot pause for 30 days (H2).
- `leave`, `withdrawBond` and the CS `bond` command are refused while paused (C1).

### 8.10 Permanent block, migration and end of life

1. Governance passes `block`. Credits: `blocked = true` at once; no new offers, fills or relayers;
   mints are not yet restricted.
2. The relayers sign `Block`; the vault sets `withdrawOnly` and records `blockedDepositId`.
3. `T` relayers attest `blockedDepositId` ([§5.8](#58-attestations)); only then
   `blockDepositLimit = blockedDepositId` on Credits, so every deposit accepted by the vault
   before its block is minted (H6, I13).
4. `burnForBsc` stays open; asks and bids are refunded on cancel; epochs close with what is in
   the fund.
5. End of life (H7): relayers stay bound for at least 12 months after the block, and bonds stay
   locked until the later of 12 months and the time `totalSupply + unpaid withdrawals` falls
   below 1 % of its value at the block, at most 24 months. After that, `withdrawBond` opens and
   the remaining holders are told to withdraw; the claim page and published records keep working
   while `T` relayers remain.
6. Optional migration: governance registers new contracts; the vault target is effective after
   7 days; each user may call `migrate` instead of `burnForBsc`, naming a fallback BSC address;
   the relayers sign `kind 1` claims, paid to the new vault, or to the fallback if the new vault
   does not accept within 30 days.

---

## 9. Failure cases

| Case | Behaviour |
|---|---|
| Fewer than `T` relayers online | Mints and claims wait; nothing is lost; resumes when they return |
| Fewer than 3 signers on the vault | The vault refuses new deposits (L5); claims continue |
| One relayer malicious | Cannot reach `T`; false claim signature → slashed by proof in any state; wrong mint approval → orphan mark, mint unaffected (H1) |
| One relayer pausing repeatedly | Once per 7 days; an unfounded pause makes it `Inactive` |
| Threshold malicious | [§3.3](#33-what-is-not-protected) |
| Relayer restart | Cursors and "submitted first" records; duplicates are ignored |
| Lost BSC event (RPC gap) | Ids must be contiguous; a gap stops the loop until both sources agree |
| Duplicate event | Approval of an id already minted returns `done` |
| Invented deposit ids | Refused beyond `vaultView.nextDepositId + 256`; pending entries expire after 30 days |
| BSC reorganisation | Only `finalized` blocks are read; finality ≈ 1–2 blocks |
| BSC finality stalls | Relayers wait; no fallback to `latest` |
| Credits node out of sync or forked | Relayer signs only from blocks ≥ `creditsConfirmations` deep with a synced node not in an uncertain state |
| Credits reorganisation deeper than the signing depth | Watchdogs pause; proofs require the margin and age rules of [§8.8](#88-slashing-by-proof); residual risk in [§3.3](#33-what-is-not-protected) |
| Credits resync (contract re-execution) | All contract logic depends only on its state, arguments and block time; it never uses `getBalance` |
| Pause and resume | [§8.9](#89-pause-and-unpause); queued claims keep their unlock time and wait for unpause |
| Relayer exits | New signer set; the bond is released only after the vault applied it and 30 more days passed |
| Bond slashed | Out of the set; vault bond slashed by `T` signatures |
| Two data hashes each reaching `T` for one deposit | Automatic pause `mint-mismatch`; resolution by vote with attested data |
| Price manipulation | Free market by decision for user orders; automated purchases per [§14](#14-open-decisions) D1; entry bonds use `min(conservative, VWAP)` so wash trades make entry dearer |
| Exchange addresses | Returns cannot carry a memo; UI warning; owners can change their return address |
| Return address is a contract | `deliverCs` fails; the CS stay claimable; the owner sets another address |
| Daily cap reached | Claims are queued in order, not reverted (M4) |
| Executor timeout | Bounded state and work ([§5.11](#511-bounded-state-and-work)) |
| Contract CS balance short of liabilities | Cannot happen while I4 holds; emitted amounts are rounded down |

---

## 10. Invariants

1. `totalSupply(cUSDT) + Σ unpaid withdrawals ≤ userUsdt(vault)` (unpaid = recorded on Credits,
   not claimed on the vault, net amounts). Equality minus deposits in flight.
2. A deposit id is minted at most once; a minted id never changes data.
3. A withdrawal id is paid at most once; it is paid only with data equal to the Credits record
   (assuming fewer than `T` dishonest signers).
4. `CS balance of CusdtBridge ≥ csLiabilities` (asks escrow + bonds + claimables + slash reserve +
   dust).
5. `Σ balances + Σ bid escrow + buybackFund + Σ bondCusdt = totalSupply`.
6. `USDT balance of vault ≥ userUsdt + Σ bondUsdt + reserveUsdt`.
7. User USDT leaves the vault only through `claim`/`executeQueued`.
8. `T ≥ 2` on both chains; every governable parameter is within its hard cap.
9. Once `foundersFrozen`, the founder set only shrinks.
10. A relayer's bond requirement never changes after entry.
11. No method has an admin; no code can change after deploy.
12. While `blocked`, no new deposit is accepted and every holder can still withdraw.
13. Every deposit id below the vault's `blockedDepositId` is mintable (H6).
14. A bond is never released while its signer key is in the vault's signer set or less than 30
    days after it left (C2).
15. `proveFalseSignature` is callable in every state, for every key of every relayer that holds a
    bond (C1, M1).
16. Every collection in the contract state has a bound in code; the serialised state stays below
    1 MB (C3).
17. `dailyCap ≤ cap / 5`; increases of `cap` and `dailyCap` take 7 days.

---

## 11. Parameters

| Parameter | Initial | Changed by | Hard cap / rule in code |
|---|---|---|---|
| Operational threshold `T` | `max(2, min(N/2+1, 7))` | code | — |
| Unpause threshold `U` | `max(T, ceil(2N/3))` | code | — |
| Minimum signers for new deposits | 3 | code (vault) | — |
| Maximum relayers | 64 | code | — |
| Delegation minimum | 1,000,000 CS | vote | ≥ 500,000 CS |
| Delegation term | `coeff = 4` (`Anni`) | code | — |
| Minimum donors / max share of one donor | 2 / 70 % | vote | ≥ 2 / ≤ 90 % |
| Founders' bond | 100,000 CS + 50 USDT | code | fixed |
| New entrant bond | max(1,000 USDT, 10 % of user USDT) | vote (rate) | rate ≤ 50 %, floor 1,000 USDT |
| Entry price of CS | `min(conservativePrice, 7-day VWAP)` | code | — |
| Admission wait / objection share | 7 days / one third ([§14](#14-open-decisions) D3) | code | — |
| Founder phase end (Credits) | first buy ≥ 100 cUSDT between distinct wallets, 6 months, or 7 relayers | code | — |
| Founder cap rule (vault) | `cap ≤ 20,000 USDT` while `foundersInSet() ≥ threshold()` | code | — |
| Whitelist fallback | 30 days below 2 founders in the set | code | — |
| Vault cap | 10,000 USDT | vote + `T` | ≤ 20,000 while founders reach `T`; after, ≤ Σ `bondCs` of the smallest `T`-set × conservative price; increases ×2 max per 7 days |
| Conservative CS price | 0 until set by vote (a cap above the founder limit needs it set) | vote | lowering immediate, raising after 7 days, at most ×2 per 7 days |
| Daily claim cap (rolling 24 h) | 2,000 USDT | vote + `T` | ≤ cap / 5; increases after 7 days |
| Large-claim threshold / delay | 1,000 USDT per rolling 24 h without whitelist majority / 24 h | code | — |
| Minimum deposit / withdrawal | 5 USDT / 5 cUSDT | vote | ≥ 1; `minWithdrawal ≥ bridgeFee + 1` (L3) |
| Bridge fee | 0.05 cUSDT per direction | vote | ≤ 1 cUSDT |
| Swap fee | 0.1 % (taker) | vote | ≤ 1 % |
| Conversion at mint | 2 %, min 1, max 20 cUSDT | vote | rate ≤ 10 %, max ≤ 100 cUSDT |
| Order limits | min 10 CS / 0.10 cUSDT; ≤ 20 per wallet; ≤ 2,000 total | code | — |
| Reward epoch / participation | 7 days / 80 % | code | — |
| Owner share of rewards | 20 % | vote | ≤ 50 % |
| Paid delegators per relayer | 100 | code | — |
| Digest period / divergence rule | 1 hour / 3 in 24 | code | — |
| Orphan rule | > 3 in 7 days → `Inactive` | code | — |
| Inactivity | < 50 % in 14 days | code | — |
| Delegation-drop grace | 30 days | code | — |
| Bond lock after exit | 30 days after the vault removed the key, plus pauses started | code | — |
| Pause limits | once per 7 days per relayer; deadline ≤ 1 h on `Pause` messages | code | — |
| Credits signing depth | 30 blocks (TO VERIFY) | vote | ≥ 10 |
| Withdrawal records kept in full | 1,024 to 2,048 | code | — |
| Pending mint window / expiry | 256 ids above the attested deposit id / 30 days | code | — |
| Service after permanent block | 12 months, bonds until supply < 1 % or 24 months | code | — |
| Migration fallback | 30 days | code | — |
| Governance window / delay / execution | 14 days / 7 days / 21 days | code | — |
| Version grace after retirement | 14 days | code | — |
| Prover share | 10 % of slashed CS | code | — |

---

## 12. Test plan

### 12.1 Executor harness (no node)

`probes/executor/` today; later `tests/executor/`, run on both executors (community and
official 1518), every answer compared between the two (the comparison already runs in CI):

- token standard detection (`tokenStandard` 3/4 on community, 0 on 1518 is acceptable for v2;
  this contract uses v1);
- mint counting per data hash, out-of-order ids, orphans, `done`, `mint-mismatch`, bounded
  record (measured: 2,000 deposits × 13 relayers, state ≤ 15.8 KB, median 18 ms per approval);
- withdrawals, compaction into Merkle roots, proofs on recent and compacted ids, the reorg margin,
  high-`s` and tampered signatures (secp256k1 measured on both executors: [§13.1](#131-verified));
- order book: fills, rounding, fees, limits per call and per wallet, founder-phase closing rule;
- payable grammar and invalid user data;
- epochs and reward allocation, resumable;
- governance timing, hard caps, state matrix of [§5.12](#512-methods-by-contract-state);
- **performance at the bounds**: maximum state (64 relayers, 2,000 orders, 2,048 withdrawal
  records, roots for 1,000,000 withdrawals, holders), serialise + execute + deserialise time per
  call on both executors; the design is frozen only if every call stays under 1 s.

### 12.2 Private Credits network

`ci/testnet` of the community node with `CONTRACTS=1` (the CI job `probes.yml` runs the network
probe today), mixed executors (`EXECUTOR_JAR_ALT`):

- the TO VERIFY items of [§13.2](#132-to-verify);
- deploy, mints, burns, swaps, payable commands, `deliverCs`, state identical on all nodes;
- a node restarting and resyncing through all of it (`RESTART_AT`), with re-execution on;
- the token API (`tokens_cache=true`) showing cUSDT balances.

### 12.3 BSC testnet

- vault deployment with test USDT; deposits, claims, queue in order, rolling caps, delay window,
  pause limits, block, migration with fallback, signer set updates, founder removal, whitelist
  fallback, bond release rules;
- Foundry unit and invariant tests (I1 via a model of Credits, I6, I7, I14, I17), fuzzing of
  signature sets, EIP-712 test vectors shared with the Java implementation.

### 12.4 Relayers, end to end

A harness running N relayer processes against the private Credits network and BSC testnet (or a
local BSC fork), with faults:

| Scenario | Expected |
|---|---|
| `T − 1` relayers offline | Nothing minted or paid; resumes on return |
| One relayer approves wrong data | Orphan mark; the deposit is minted with the correct data |
| One relayer signs a false claim | Proof slashes it, also while paused; claim impossible without `T` |
| `T` relayers sign false claims | Paid up to the rolling caps and delay; watchdogs of the others pause; proofs slash; bonds of the signers cannot be withdrawn while they remain on the vault |
| A colluder pauses then leaves | `leave` and `withdrawBond` refused while paused; proofs still accepted |
| RPC source returns a gap or a forked log | Loop stops; no approval |
| Relayer killed between store and send | No double or different action |
| Digest divergence | Marks, then `Inactive`; keeps pause right |
| Unadmitted version | Approvals refused |
| Delegations fall below 1M | `Inactive` after 30 days |
| Founders leave | Whitelist fallback after 30 days |
| Permanent block with deposits in flight | Every deposit below `blockedDepositId` minted |
| Migration target reverts | Claim paid to the fallback after 30 days |
| Repeated single-relayer pause | Refused within 7 days; unfounded pause → `Inactive` |

### 12.5 CI

GitHub Actions in this repository (`.github/workflows/probes.yml`): executor probes on both jars
on every push; the private network probe on push and on demand; later the BSC-fork end-to-end
tests nightly. Heavy jobs never run on the shared server.

---

## 13. Runtime facts and what is still to verify

### 13.1 Verified

| Fact | Evidence |
|---|---|
| Contract-to-contract calls fail on mainnet | Node: `Violations::SubsequentCall` for `@UsingContract`; executor 1518: `AccessControlException` on `invokeExternalContract` (analysis of 2026-10-30, harness) |
| Contract → contract CS transfers are refused | `solver/src/smartcontracts.cpp` `test_violations` (`SourceIsContract`), `csnode/src/itervalidator.cpp` (`kContractViolation`) |
| Contract-emitted transfers carry no user data | `solver/src/smartcontracts.cpp` (≈ line 2328): emitted transfers rebuilt as plain transactions without user fields |
| Emitted transfers are paid by the caller | `prevalidate` requires the start transaction's `max_fee` to cover the new state and every emitted transfer; `walletscache.cpp` charges the initiator (security review, M8) |
| A `payable` that throws returns the CS | `walletscache.cpp` `invokeReplenishPayableContract` / `rollbackExceededTimeoutContract`; private network (5 nodes, CI run 42183949839, 2026-11-06): a 7 CS payment without user data was refused, the API answered "call to contract failed", the sender lost only the 0.0175 CS fee, the contract received nothing |
| `payable` receives the text user field | user field id 1 (`cs::trx_uf::ordinary::Text`) passed as `byte[]` (`api/src/executor.cpp`) |
| A call costs ≈ 0.0175 CS, independent of state size | `csnode/src/fee.cpp`: start tx 0.00874 (< 5 KB), new state 0.00874, execution 0.00874 CS per second |
| Time the node waits for the executor | `executor_receive_timeout` default 4,000 ms per node (`client/config/config.hpp`); consensus limit 60 s (`Consensus::TimeSmartContract`) |
| States above 8,192 bytes are not carried in blocks | `Consensus::MaxContractStateSizeToSync`; nodes re-execute or fetch them |
| `getBlockchainTimeMills()` returns block time | `api/src/executor.cpp`: the start transaction's block time; re-execution uses the explicit sequence (code read and review) |
| `getBalance` reads the current balance | `api/src/apihandler.cpp` `APIEXECHandler::WalletBalanceGet` |
| `sendTransaction` takes a `double` | `SmartContract` v3 API; 15 significant digits |
| Failed call keeps the old state | Harness: a throw after a write leaves the supply at 0 |
| Approvals scale | Harness: 2,000 deposits, 13 relayers, threshold 7: 14,000 approvals, 2,000 mints, no double mint, median 18 ms, p95 64 ms, max 1.2 s, state 1.8–15.8 KB |
| Same answers on the official 1518 and the community executor | GitHub Actions `probes.yml`, job "Executors", 2026-11-06: bridge probe (500 deposits, 13 relayers) and secp256k1 probe (50 signatures) with 0 differing steps |
| secp256k1 in Java | Harness: 50/50 signers recovered on both executors, 25 ms median, 63 ms max (community); tampered digest and high-`s` rejected. Slashing by proof works on 1518 |
| BSC finality | `finalized` 1–2 blocks behind `latest` (≈ 0.45–0.9 s) on mainnet and testnet RPCs, 2026-11-06 |
| Delegations readable from the node API | `api.thrift` `DelegatedItem` (`wallet`, `sum`, `validUntil`, `fromTime`, `coeff`); contracts cannot read them |
| 1-year delegations | `coeff = Anni = 4` for a term ≥ 4 × 7,862,400 s; timed delegations cannot be withdrawn before expiry; minimum 5 CS (`csnode/src/nodecore.cpp`, `itervalidator.cpp`) |
| Block time on a real network | Private network: `getBlockchainTimeMills()` in two calls 23.2 s apart (wall clock) returned values 22.7 s apart, 1.1–1.6 s ahead of the sender's clock, recorded identically on all 5 nodes (re-execution while syncing not covered) |
| `payable` with user data | Private network: 11 CS with text user field `bond:relayer-1` accepted; the contract received 11 CS and the exact user data |
| Emitted transfers on a real network | Private network: `sendTransaction(contract, wallet, 3, userData)` delivered exactly 3 CS with no user fields (type 16); an emitted transfer to another contract failed the whole call ("call to contract failed", no CS moved, state unchanged) |
| `getBalance` is not a usable eligibility source | Private network: the contract read 290.004 CS for a wallet the API reported at 299.948 CS around the same time |
| Same state on every node | Private network: the probe contract's state hash was identical on all 5 nodes |
| Executor speed in CI | GitHub runner: approval median 2.7 ms (1518) / 2.9 ms (community), state 1.8–5.3 KB over 500 deposits; secp256k1 recovery median 13.6 / 13.9 ms |
| Staking rewards are on on mainnet | Mainnet node log, 2026-11-05: "stakingOn = true, miningOn = true, blockReward = 1.00" (L8 resolved) |
| Delegation to a contract is refused | `itervalidator.cpp` (`kTransactionProhibited`) |
| Sandbox classes | `BigDecimal`, `BigInteger`, `TreeMap`, `String.format` need no permission (`PermissionsManager.java`); `SigProbe` runs under it |

### 13.2 TO VERIFY

On the private Credits network unless noted (block time on live nodes, refused payments,
emitted amounts and failed-call reporting are verified in [§13.1](#131-verified)):

1. Block time from `getBlockchainTimeMills()` during re-execution by a node that syncs.
2. Amounts with many decimals through the `double` of `sendTransaction` (whole amounts verified).
3. Why `getBalance` inside a contract differs from `WalletBalanceGet` (not used by the design).
4. How the API reports failed `approveMint` and `burnForBsc` calls to relayers and users.
5. Credits reorganisation depths observed on mainnet, to set `creditsConfirmations`.
6. Performance at the bounds of [§5.11](#511-bounded-state-and-work) on both executors.
7. The token cache shows cUSDT balances after mints, burns, fills and internal moves.

---

## 14. Open decisions

These need a decision by the project owner. Until then the text follows the current decision.

| # | Topic | Current decision | Review concern | Options |
|---|---|---|---|---|
| D1 | Price limits on automated purchases (H8, M3) | **Decided 2026-11-06.** No price limit anywhere: the conversion at mint is small (≤ `conversionMax`) and a free market rewards whoever sells CS; the buyback is spread in hourly slices of 1/168 of the epoch fund (option d) | — | — |
| D2 | Single-relayer pause (H2, former §14.3) | **Decided 2026-11-06.** Withdrawals below 1,000 USDT continue during a pause, within the daily cap; one pause per relayer per 7 days; an unfounded pause makes the pauser `Inactive` for 30 days ([§8.9](#89-pause-and-unpause)) | — | — |
| D3 | Objection during the 7-day wait (M6) | One third of active relayers can reject an applicant | Incumbents can veto every applicant and keep `N` small; contrary to automatic admission | Remove it; let it only trigger a re-attestation of eligibility; require a majority with a public record |
| D4 | Use of the slash reserve | Not decided | — | Proposal: reimburse users pro rata after a shortfall, by vote |
| D5 | Provisional values | As in the text | — | Bids in the book (yes); taker pays 0.1 % also on the conversion at mint, not on the buyback; owner share 20 % and the 100 largest delegators; participation 80 %; new-entrant bond: 50 USDT on the vault, the rest in CS, cUSDT or USDT; initial vault cap 10,000 (hard 20,000 while founders reach `T`); daily cap 2,000 rolling (≤ cap / 5, was 5,000 per UTC day); minimum 5 USDT; prover share 10 % |
| D6 | Bonds in cUSDT or USDT (C2) | New entrants may pay the CS value in USDT | They are recovered by a thief who drains the vault | In the text: they count for entry, not for the cap bound; alternatively accept only CS above the 50 USDT |
| D7 | Who deploys the contracts, and the initial founders | Not decided | — | — |

---

## 15. Review findings and where they are addressed

| Finding | Where |
|---|---|
| C1 proofs blocked while paused | §5.4 `leave`/`withdrawBond`/`proveFalseSignature`, §5.12, §8.8, §8.9, I15 |
| C2 bonds do not bind `T` | §2.2, §3.3, §5.3, §5.4 `withdrawBond`, §5.10, §6.3 `releaseBond`, I14, D6 |
| C3 unbounded state | §1 goal 7, §5.1 bounds, §5.11, §12.1, I16 |
| H1 one relayer blocks a mint | §5.7 |
| H2 unlimited pause | §8.9, D2 |
| H3 damage limits | §3.3, §6.1 windows, §6.3 `claim`/`setCap`/`unpause`, I17 |
| H4 20,000 cap and `foundersFrozen` | §3.3(2), §6.3 `setCap`, §11 |
| H5 entry price | §5.10 |
| H6 deposits around the block | §5.1, §8.10, I13 |
| H7 migration and end of life | §5.4 `migrate`, §6.2 `Claim.fallback`, §6.3, §8.10 |
| H8 buyback | §8.4 (hourly slices, D1 decided) |
| M1 rotated keys | §4.1, §5.1 `signerHistory`, §5.4, §8.8 |
| M2 Credits reorganisations | §3.3(7), §7.4, §8.8, §11 |
| M3 conversion in a thin book | §5.7.1 step 2; no price limit by decision D1 (at most `conversionMax` per deposit) |
| M4 daily cap griefing | §6.3 `claim` queue |
| M5 governance timing | §8.7 |
| M6 one-third veto | D3 |
| M7 digests and attestations | §5.8, §7.6, §7.7 |
| M8 emitted transfers | §5.6, `deliverCs`, §7.3 |
| M9 `depositFromMigration` | §6.3 |
| M10 founder arithmetic | §3.3(2), §11 |
| L1 `double` | §4.2, §5.6 |
| L2 rejected applicant | §5.4 `objectApplication` |
| L3 minimum withdrawal | §11 |
| L4 rolling window | §6.1 |
| L5 three relayers | §6.3 `deposit` |
| L6 `Pause` replay, `Bond(action 0)` | §6.2, §6.3 |
| L7 urgent versions | §7.7 |
| L8 staking off | §13.1 (on on mainnet) |
| L9 50 USDT release | §6.3 `releaseBond` |
| Underspecified 1–15 | §6.2 (1), §5.8 (2, 7), §5.1/§5.2 (3), §5.12 (4), §5.7 (5), §8.4 (6), §5.9/§5.1 (8), §11 (9), §5.4/§8.8 (10), §5.5 (11), §7.3/§7.4 (12), §6.3 (13), §5.6 (14), §5.14 (15) |
