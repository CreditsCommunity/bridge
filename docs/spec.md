# USDT bridge for Credits: specification

Status: draft for security review, 2026-11-06. Not approved. No code is written against it yet.

This document specifies a bridge that carries USDT from BNB Smart Chain (BSC) to the Credits
network as cUSDT, 1 to 1, and back; a CS ↔ cUSDT order book on Credits; and the relayer network
that connects the two chains. It replaces the design analysis of 2026-10-14 ("USDT bridge for
Credits: analysis") where the two differ: the decisions taken after it are listed in
[§2.3](#23-decisions-that-changed-since-the-analysis).

Words in capitals (MUST, MUST NOT, SHOULD) carry their usual meaning. "TO VERIFY" marks a fact
that the design depends on and that has not yet been confirmed on a real Credits network
([§13](#13-runtime-facts-and-what-is-still-to-verify)).

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
14. [Open questions](#14-open-questions)

---

## 1. Overview and goals

**What it does.**

- A user deposits USDT into `UsdtVault` on BSC. Independent relayers see the deposit in a
  finalized BSC block and approve it on Credits. When enough of them agree, the Credits contract
  `CusdtBridge` mints the same amount of cUSDT to the user, minus a fixed fee, and converts a small
  part into CS from the best sell offers, so the user can pay Credits transaction fees.
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
   cUSDT holder can still withdraw.
6. Losses in the worst case are bounded by caps that grow only as the guarantees grow.

**Non-goals.** Bridging CS to BSC; any asset other than USDT in this version; making a colluding
threshold of relayers unable to steal (see [§3](#3-trust-model)).

---

## 2. Decisions

### 2.1 Summary

| Topic | Decision |
|---|---|
| Asset | BSC USDT (BEP-20, 18 decimals) ↔ cUSDT on Credits, 1 to 1, amounts in multiples of 10⁻⁸ USDT |
| Credits contracts | One contract, `CusdtBridge`: token, bridge, relayer registry, bonds, order book, buyback, governance |
| BSC contract | `UsdtVault`: deposits, claims with EIP-712 threshold signatures, signer set, founders, whitelist, caps |
| Relayer eligibility | Credits full node whose wallet holds ≥ 1,000,000 CS of incoming 1-year delegations from at least 2 wallets other than the owner's |
| Admission | Automatic: eligibility attested by the relayers' software, 7-day wait, no sponsors |
| Operational threshold | `T = min(floor(N/2) + 1, 7)`, never below 2, `N` = active relayers |
| Governance threshold | more than half of all active relayers, no cap of 7 |
| Bonds | Founders: 100,000 CS + 50 USDT. Later entrants: value ≥ max(1,000 USDT, 10 % of user USDT in the vault), fixed at entry |
| Slashing | Automatic, by proof of a false withdrawal signature, verified in the Credits contract |
| Fees | Bridge fee 0.05 cUSDT each way; swap fee 0.1 % paid by the taker; both fund a CS buyback for relayers and their delegators |
| CS for new users | 2 % of each deposit (min 1, max 20 cUSDT) bought as CS from the lowest offers at mint |
| Prices | Free market: no price limit imposed by the contract; the depositor MAY set a maximum CS price for their own conversion |
| Large claims | Above 1,000 USDT, 24-hour delay unless the signatures include a majority of the whitelist |
| Exit | Permanent block → withdraw-only on both chains; each user withdraws, or migrates their own funds to new contracts registered by vote |

### 2.2 Rejected alternatives

| Alternative | Why it is not used |
|---|---|
| Contract-to-contract calls (`invokeExternalContract`), a separate swap contract | Refused on mainnet: the node rejects `@UsingContract` methods (`Violations::SubsequentCall`) and executor 1518 fails every `invokeExternalContract` |
| CS transfers from one contract to another | Refused by the node: a contract-emitted transaction whose target is a contract is a violation (`Violations::SourceIsContract`, `solver/src/smartcontracts.cpp`) |
| Checking the 500k CS balance with `getBalance` | Reads the wallet's current balance, not the balance at the executed block, and the balance can move right after the check |
| CS bonds locked as the eligibility criterion | Locking CS takes them out of the node's stake; delegations keep them working |
| Sponsors, manual approval | The user requires automatic admission |
| ed25519 checked inside Java, classic multisigs, price oracle, CS minted by the protocol, fixed price | As in the analysis of 2026-10-14 |
| Contract-imposed maximum or minimum price | The user wants a free market |
| Fee in BNB | Would need a DEX conversion on BSC before buying CS |
| A new reward token | Value would have to come from the fees anyway; cUSDT/CS paid directly is simpler |
| Mass transfer of funds for upgrades | The most valuable target for an attack; replaced by per-user migration |
| Memo/tag on CS returns | The node drops user data on contract-emitted transactions ([§13.1](#131-verified)) |

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
| A single relayer | Approve, sign, pause both contracts, propose, vote | Mint, pay a claim, unpause or change a setting alone |
| A threshold `T` of relayers | Mint for a deposit, sign a claim, update the vault's signer set and cap, unpause | Change a hard cap; move user USDT other than through claims; raise founders' bonds |
| More than half of active relayers | Change parameters within hard caps (7-day delay), admit versions, block permanently, register migration targets | Change code; exceed hard caps |
| Majority of active founders | Change the trusted whitelist on the vault | Anything else beyond a normal relayer |
| Anyone | Submit signatures to the vault, trigger epoch closes and status updates, submit a fraud proof | — |

### 3.2 What is protected

- **One relayer, or fewer than `T`, misbehaving:** cannot mint or pay anything. A false
  withdrawal signature loses its bond by proof. Any honest relayer can pause.
- **Lost or duplicated events, restarts, BSC reorganisations:** deposits are read by sequential
  id from finalized blocks only; mints and claims are once per id ([§9](#9-failure-cases)).
- **Operator key theft of one relayer:** same as one malicious relayer.

### 3.3 What is NOT protected

1. **A colluding threshold of relayers.** The vault cannot see Credits. If `T` relayers agree,
   they can sign a claim for a withdrawal that never happened, and the vault pays it. Equally,
   `T` relayers can approve a mint for a deposit that never happened. Nothing in the contracts
   prevents this. It is limited by:
   - the vault cap and the daily claim cap (maximum loss);
   - the 24-hour delay on large claims not signed by the whitelist majority;
   - slashing by proof of the bonds of every relayer who signed a false claim;
   - any honest relayer pausing both contracts when its watchdog sees the invariant broken.
2. **Colluding founders during the founder phase.** Founders can reach `T` alone until there are
   8 relayers, and a majority of founders also controls the whitelist, so their large claims are
   not delayed. During this phase the vault cap is fixed by vote and at most 20,000 USDT: users
   trust a known group for a limited amount.
3. **A majority of all relayers** can change parameters within the hard caps, admit a relayer
   version, block the bridge permanently and register a migration target. Users who disagree
   have 7 days to withdraw before a change applies; migration is never forced.
4. **Value of slashed bonds.** CS has no reliable market price; slashed CS may be worth less than
   the loss. A bond held as cUSDT is a claim on the same vault and does not compensate users
   if the vault is emptied, though it still costs the thief.
5. **Sybil relayers.** Disjoint-wallet rules raise the cost of one person running several
   relayers; they cannot prove that two wallets belong to different people.
6. **Relayer code.** Nobody can prove remotely which program a relayer runs. The design checks
   what relayers produce, not what they claim to run ([§7.7](#77-code-verification)).

The bound on the loss from (1) is: vault cap ≤ value of the bonds of the smallest coalition able
to reach `T` (after the founder phase), and claims per day ≤ daily cap.

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
| Node wallet | Credits | Receives the delegations; owns the bond; registers the relayer; receives the owner share of rewards (or forwards it, see `ownerWallet`) |
| Operator key | Credits | Sends approvals, digests, votes. MAY equal the node wallet. Can be rotated by the node wallet |
| Signer key | BSC (secp256k1) | Signs EIP-712 messages for the vault. Never sends BSC transactions in normal operation |
| Owner wallet | Credits | Receives the owner share of rewards; its delegations do not count for eligibility |

### 4.2 Units

| Quantity | Representation |
|---|---|
| USDT on BSC | `uint256`, 18 decimals; every amount MUST be a multiple of 10¹⁰ (8 decimals) |
| cUSDT | `BigDecimal`, scale 8; `units = USDT_wei / 10¹⁰` |
| CS amounts kept by the contract | `BigDecimal`, scale 6 (see `sendTransaction` precision, [§13.1](#131-verified)) |
| Prices | cUSDT per 1 CS, `BigDecimal` scale 8 |
| Time | Credits: `getBlockchainTimeMills()` (block time, ms); BSC: `block.timestamp` (s) |
| Credits address in BSC data | `bytes32`, the 32-byte ed25519 public key (base58 on Credits) |

Rounding rule: every division rounds in favour of the contract (amounts paid out round down,
amounts charged round up), and every rounding difference is kept in a dust account so that
[§10](#10-invariants) holds exactly.

---

## 5. Credits contract `CusdtBridge`

Java 11, one top-level class (nested static classes allowed), `extends
com.credits.scapi.v3.SmartContract implements com.credits.scapi.v1.ExtensionTokenStandard`.
Token name "Credits USDT", symbol `cUSDT`, 8 decimals. No owner field, no admin method.

Every method that changes state reads time once with `getBlockchainTimeMills()` and runs the
lazy updates (governance applications, status updates, epoch bookkeeping) that are due, bounded
in work per call ([§5.11](#511-bounded-work)).

### 5.1 State

| Field | Content |
|---|---|
| `cfg` | Immutable deployment constants: BSC chain id, vault address, EIP-712 domain separator, hard caps ([§11](#11-parameters)), deploy time |
| `params` | Current governable parameters |
| `balances: Map<String, BigDecimal>` | cUSDT balances (free) |
| `allowed: Map<String, Map<String, BigDecimal>>` | Allowances, ERC-20 semantics |
| `totalSupply` | Sum of all cUSDT in existence, including escrowed, fund and locked |
| `pendingMints: Map<Long, PendingMint>` | Per deposit id: data hash, data, approving relayer ids, first-approval time |
| `mintedBelow: long`, `mintedAbove: TreeSet<Long>`, `conflicts: Set<Long>` | Bounded record of minted deposit ids |
| `withdrawals: Map<Long, Withdrawal>` | Per withdrawal id: kind, from, BSC recipient, net amount, time, `keccak` hash of the signed data |
| `nextWithdrawalId: long` | Sequential |
| `relayers: Map<Long, Relayer>` | Relayer records ([§5.3](#53-relayer-record)) |
| `relayerByWallet`, `relayerByOperator`, `relayerBySigner` | Indexes |
| `asks: TreeMap<PriceKey, Ask>`, `bids: TreeMap<PriceKey, Bid>` | Order book, price then id |
| `lastPrice`, `dailyVolume[7]` | Last trade price; per-day CS and cUSDT volumes for the 7-day average |
| `buybackFund: BigDecimal` | cUSDT from fees, not yet spent |
| `csClaimable: Map<String, BigDecimal>` | CS owed to wallets (rewards, refunds, unattributed payments) |
| `csLiabilities` | Sum of all CS the contract owes: asks escrow, bonds, claimables, dust |
| `epochs` | Reward epoch bookkeeping and per-epoch participation counters |
| `digests` | Per digest period: digest hash per relayer |
| `proposals: Map<Long, Proposal>` | Governance |
| `admittedVersions: Map<String, Long>` | Version hash → retirement time (or max) |
| `founderPhase`: open/closed, `founderPhaseEnd` | |
| `pause`: none / paused(by relayer, reason, nonce) | |
| `blocked: boolean`, `blockedAt`, `lastBscDepositIdAtBlock` | Permanent block |
| `migration`: new contract address, new vault address, effective time | |
| `slashReserveCs`, `slashReserveCusdt` | Confiscated bonds |
| `unattributed: Map<String, BigDecimal>` | CS received without valid user data, refundable to the sender |

`PendingMint` data = `(to, amount, maxCsPrice, bscTxHash)`; two approvals with different data
for one id set a conflict.

### 5.2 Records instead of events

Credits has no event log. Every action that relayers or the claim page must read is recorded in
contract state under a sequential id and exposed by `@Getter` methods:

- withdrawals by id (`getWithdrawal(id)`, `getWithdrawalsFrom(id, count)`);
- relayer records and the active set with its version (`getRelayers()`, `getSignerSetNonce()`);
- proposals, pause state, epochs, the order book (`getAsks(count)`, `getBids(count)`).

### 5.3 Relayer record

| Field | Meaning |
|---|---|
| `id` | Sequential |
| `nodeWallet`, `operator`, `ownerWallet` | [§4.1](#41-identities-of-a-relayer) |
| `bscSigner` | 20-byte address, lowercase hex |
| `signatureUrl` | HTTPS base URL where it publishes signatures and digests |
| `status` | `Applied`, `Active`, `Inactive`, `Exiting`, `Exited`, `Slashed`, `Rejected` |
| `founder` | Applied before the founder phase closed |
| `bondCs`, `bondCusdt` | Held by this contract |
| `bondUsdtOnBsc` | 50 USDT recorded as attested by `T` relayers from the vault |
| `appliedAt`, `activatedAt`, `exitAt` | Times |
| `eligibleSince`, `ineligibleSince` | Delegation status from attestations |
| `version` | Last version hash used in an approval or digest |
| `participation` | Counters for the current windows |

### 5.4 Methods

Caller column: **U** any wallet, **R** operator of an active relayer, **W** node wallet of the
relayer concerned, **A** anyone. All amounts are `BigDecimal` (Variant `v_big_decimal`), ids are
`long`, addresses and hashes are `String`.

#### Token (standard v1)

| Method | Caller | Rules |
|---|---|---|
| `getName()`, `getSymbol()`, `getDecimal()`, `totalSupply()`, `balanceOf(owner)`, `allowance(owner, spender)` | A | `@Getter` |
| `transfer(to, amount)` | U | Positive, ≤ 8 decimals, ≤ balance; `to` a valid Credits address ≠ this contract. Allowed while paused or blocked |
| `transferFrom(from, to, amount)` | U | As `transfer`, within allowance |
| `approve(spender, amount)` | U | Sets the allowance (not additive) |
| `burn(amount)` | U | Always throws "use burnForBsc": a burn without a withdrawal would destroy the holder's claim on the vault |
| `setFrozen(frozen)` | U | Always throws: no admin |
| `register()` | U | No-op, returns |
| `payable(amount, userData)` | U | See [§5.5](#55-incoming-cs-payable) |

#### Bridge

| Method | Caller | Rules |
|---|---|---|
| `approveMint(depositId, to, amount, maxCsPrice, bscTxHash, version)` | R | Not paused; `version` admitted; `depositId` not minted, not in conflict; if blocked, `depositId < lastBscDepositIdAtBlock`. Records the approval; if the data differs from an earlier approval of the same id → conflict, mint blocked, alarm. At `T` matching approvals: mint ([§8.1](#81-deposit-bsc--credits)). Returns `pending k`, `minted`, `done`, `conflict` |
| `burnForBsc(amount, bscAddress)` | U | Not paused, not blocked-for-new-withdrawals (withdrawals stay open when blocked); `amount ≥ minWithdrawal`; `bscAddress` 20-byte hex, not zero, not the vault. Charges `bridgeFee` to the fund, burns `amount − bridgeFee`, records withdrawal `kind=0` with the next id. Returns the id |
| `migrate(amount, newCreditsAddress)` | U | Migration target effective; as `burnForBsc` with `kind=1`, recipient = registered new vault, `creditsTo` = `newCreditsAddress`; no bridge fee |
| `getWithdrawal(id)`, `getWithdrawalsFrom(id, n)` | A | `@Getter` |

#### Relayers

| Method | Caller | Rules |
|---|---|---|
| `applyRelayer(operator, ownerWallet, bscSigner, signatureUrl, version)` | W (initiator = node wallet) | Not blocked; not already a relayer; bond already paid by the same wallet ([§5.5](#55-incoming-cs-payable), `bond` command) covering the bond required at this moment; founder if the founder phase is open. Status `Applied` |
| `attestEligibility(relayerId, eligible, delegatedTotal, donorsDigest, delegatorsList, bscBondPaid)` | R | Records this relayer's view of the candidate or member: eligibility under [§8.5](#85-relayer-admission), the delegation total, the delegator list (≤ `maxPaidDelegators` entries, `wallet:amount` pairs) and whether the 50 USDT bond is on the vault. Accepted when `T` identical attestations exist |
| `objectApplication(relayerId)` | R | During the 7-day wait. At one third of active relayers (rounded up) the application is rejected and the bond becomes withdrawable at once |
| `activate(relayerId)` | A | After 7 days, eligibility and bond attested, not rejected. Status `Active`; signer set nonce +1 |
| `setOperator(op)`, `setSignatureUrl(url)`, `setOwnerWallet(w)` | W | Immediate |
| `rotateSigner(bscSigner)` | W | Signer set nonce +1; old key stays valid on the vault until the update lands |
| `leave()` | W | Status `Exiting`, removed from the active set; signer set nonce +1; `exitAt = now` |
| `withdrawBond()` | W | `Exiting`/`Rejected`/`Inactive` (if it chose to leave); `now ≥ exitAt + 30 days`, and if blocked `now ≥ blockedAt + 12 months`; not under an open proof. Pays CS to the return address, cUSDT to the node wallet's balance; marks `Exited`. The relayers sign the BSC `BondRelease` |
| `submitDigest(period, digestHash, version)` | R | Once per relayer per digest period ([§7.6](#76-state-digests)) |
| `updateStatus(relayerId)` | A | Applies inactivity, delegation-drop and divergence rules ([§8.6](#86-inactivity-delegation-drop-divergence)) |
| `proveFalseSignature(id, kind, to, amount, creditsTo, sigHex)` | A | [§8.8](#88-slashing-by-proof) |

#### Order book

| Method | Caller | Rules |
|---|---|---|
| (`payable`, command `ask`) | U | Places an ask: CS escrowed, price in the command |
| `placeBid(cusdtAmount, price, returnAddress)` | U | Escrows cUSDT from the caller's balance |
| `cancelAsk(id)`, `cancelBid(id)` | owner of the offer | CS to the return address; cUSDT back to the balance |
| `buy(maxCusdt, maxPrice)` | U | Takes asks from the lowest price, then oldest; spends at most `maxCusdt` including the swap fee; `maxPrice` 0 = no limit (the caller's own choice). CS sent to the caller's return address (default: caller) |
| (`payable`, command `sell`) | U | Sells the CS paid into bids from the highest price; optional minimum price; unsold CS refunded or left as an ask (command option) |
| `setReturn(kind, id, address)` | owner | Changes the return address of an ask or of the caller's bond; allowed while blocked |
| `claimCs()` | U | Pays the caller's `csClaimable` to the caller's registered return address (default: caller) |
| `setMyReturnAddress(address)` | U | Default return address for the caller's claimables |

#### Rewards and governance

| Method | Caller | Rules |
|---|---|---|
| `closeEpoch()` | A | After the epoch end: runs the buyback from the fund, allocates CS ([§8.4](#84-fees-buyback-and-rewards)) |
| `propose(kind, key, value)` | R | Kinds: parameter, admit/retire version, conservative CS price, vault cap, permanent block, migration target. Rejected if outside the hard caps |
| `vote(proposalId, yes)` | R | One vote per active relayer; changeable until decided |
| `execute(proposalId)` | A | Passed (yes > half of active relayers at execution) within 14 days, and 7 days elapsed since passing (0 days for changes that only lower risk, [§8.7](#87-governance)) |
| `pause(reason)` | R | Immediate. Records `pausedBy`, a nonce |
| `approveUnpause(nonce)` | R | At `T` approvals the pause ends |

### 5.5 Incoming CS (`payable`)

`payable(amount, userData)` runs when a wallet transfers CS to the contract. `userData` is the
transaction's text user field (`cs::trx_uf::ordinary::Text`, id 1) passed as bytes. It MUST be
UTF-8 of one of:

| Command | Meaning |
|---|---|
| `bond` | Adds to the sender's relayer bond (CS part). Return address defaults to the sender |
| `bond|<returnAddress>` | Same, with a return address |
| `ask|<price>` or `ask|<price>|<returnAddress>` | Places an ask of `amount` CS at `price` |
| `sell|<minPrice>|<rest>` | Sells into bids; `rest` = `refund` or `ask:<price>` |

Rules: `amount` positive with at most 6 decimals and at most 10⁹ CS; anything else MUST throw.
**TO VERIFY:** that a `payable` that throws makes the node discard the CS transfer, not only the
state change. If the transfer is kept, the contract instead records the amount under
`unattributed[sender]` and the sender gets it back with `claimCs()`; the method then returns
instead of throwing. The implementation is chosen after the private-network test.

### 5.6 Outgoing CS

CS leaves only through `sendTransaction(contractAddress, to, amount)` to:

- the return address of an ask or bond (cancel, fill of a bid, bond release),
- the buyer of CS (purchase, conversion at mint),
- a wallet claiming its `csClaimable`.

Never to a contract address (the node refuses it). Amounts are rounded down to 6 decimals before
the `double` conversion; the difference stays in the dust account. **The node drops user data
on contract-emitted transactions** ([§13.1](#131-verified)): no memo or tag can accompany a
return. Return addresses MUST be wallets the owner controls; the UI MUST warn against exchange
deposit addresses that need a memo. Emitted transfers with user data are a possible future node
change, not a feature of this version.

### 5.7 Minting and the conversion to CS

At the `T`-th matching approval of deposit `(id, to, A, maxCsPrice)`:

1. `fee = bridgeFee`; if `A ≤ fee + conversionMin` the deposit is still minted with
   conversion 0 (minimum deposit on the vault makes this rare).
2. `budget = clamp(conversionRate × (A − fee), conversionMin, conversionMax)`, at most `A − fee`.
3. Take asks from the lowest price, oldest first, not above `maxCsPrice` if it is set, spending
   at most `budget` including the swap fee. Fills follow [§5.9](#59-order-matching).
4. Mint `A`: `fee` to `buybackFund`, swap fee to `buybackFund`, the cUSDT paid to the sellers'
   balances, the rest to `to`.
5. Send the CS bought to `to` (one emitted transfer).
6. Mark the id minted; update `mintedBelow`/`mintedAbove`.

Without asks within the limit, the whole `A − fee` is credited as cUSDT. The mint never fails
because of the order book.

### 5.8 Withdrawal record and signed data

For withdrawal `id`, the data the relayers sign is
`Claim(id, kind, to, amountWei, creditsTo)` ([§6.2](#62-eip-712)). The contract stores
`hashStruct(Claim)` for each id, computed in Java with the same Keccak-256 used for proofs, so a
proof needs no other state.

### 5.9 Order matching

- Asks are ordered by price ascending then id; bids by price descending then id.
- A buyer pays `qty × price` per fill, rounded up to 8 decimals, plus `swapFee` of the total,
  rounded up. CS quantities are rounded down to 6 decimals. A fill that would give 0 CS stops.
- A seller into bids receives `qty × price − swapFee`, rounded down.
- Every fill updates `lastPrice` and the day's volumes.
- At most `maxFillsPerCall` fills per call ([§5.11](#511-bounded-work)); the rest of the order
  is returned unspent.
- The founder phase closes at the first fill of a single `buy` (not a conversion, not the
  buyback) where the buyer paid ≥ 100 cUSDT in total and the buyer differs from every seller
  filled.

### 5.10 Bond required at entry

Computed when `applyRelayer` is called and fixed for that relayer:

- founder phase open: 100,000 CS in `bondCs` **and** 50 USDT on the vault;
- otherwise: 50 USDT on the vault, plus CS and/or cUSDT held by this contract such that
  `bondCs × entryPrice + bondCusdt + 50 ≥ max(1000, newBondRate × userUsdtInVault)`, where
  `entryPrice = max(conservativePrice, 7-day average price)` and `userUsdtInVault` is the last
  value attested by `T` relayers in their digests.

A later rise of the requirement never applies to existing relayers.

### 5.11 Bounded work

Every method's work is bounded so that a call stays far below the time the node waits for the
executor ([§13](#13-runtime-facts-and-what-is-still-to-verify)): at most 50 fills, 50 lazy
updates, 100 reward allocations per call. Long jobs (an epoch close with many delegators) are
resumable: a second call continues where the first stopped.

### 5.12 Errors

Methods throw `IllegalStateException` with a stable message prefix (`paused`, `blocked`,
`not relayer`, `version`, `conflict`, `amount`, `address`, `bond`, `cap`, `time`, `proof`).
A failed call keeps the previous state and emits nothing (verified in the executor harness).

---

## 6. BSC contract `UsdtVault`

Solidity ≥ 0.8.24, no proxy, no owner. Uses OpenZeppelin `SafeERC20`, `ECDSA`, `EIP712`,
`ReentrancyGuard`. Constructor: USDT token address, initial signers and founders (the founders
active at launch), initial cap, Credits contract address (informational).

### 6.1 State

| Field | Meaning |
|---|---|
| `usdt` | Token |
| `signers: address[]`, `isSigner` | Current signer set, sorted |
| `threshold()` | `max(2, min(n/2 + 1, 7))` computed from `n` |
| `founders`, `isFounder`, `foundersFrozen` | Founder set; only shrinks once frozen |
| `whitelist`, `isWhitelisted` | Trusted signers for immediate large claims |
| `foundersBelowTwoSince` | Time the number of founders in the signer set fell below 2 (0 otherwise) |
| `nextDepositId` | Sequential |
| `userUsdt` | User funds held: deposits − claims − migrations |
| `bondUsdt[bytes32 nodeWallet]` | Relayer bonds, apart from user funds |
| `reserveUsdt` | Slashed bonds |
| `claimed[uint64]` | Withdrawal ids paid or queued |
| `queued[uint64]` | `(to, amount, kind, creditsTo, unlockTime)` |
| `cap`, `pendingCap`, `pendingCapTime` | Vault cap on `userUsdt` |
| `dailyCap`, `day`, `claimedToday` | Claims per UTC day |
| `paused`, `pauseNonce`, `withdrawOnly` | |
| `migrationTarget`, `migrationTime` | New vault, effective time |
| `nonces[kind]` | Replay protection per message kind |

### 6.2 EIP-712

Domain: `name = "CreditsUsdtVault"`, `version = "1"`, `chainId`, `verifyingContract = vault`.

| Type | Fields |
|---|---|
| `Claim` | `uint64 withdrawalId, uint8 kind, address to, uint256 amount, bytes32 creditsTo` |
| `SignerSet` | `uint64 nonce, address[] signers, address[] foundersToAdd, bool freezeFounders` |
| `FounderRemoval` | `uint64 nonce, address founder` |
| `Whitelist` | `uint64 nonce, address[] whitelist` |
| `Cap` | `uint64 nonce, uint256 cap, uint256 dailyCap` |
| `Bond` | `uint64 nonce, bytes32 nodeWallet, uint8 action, address to, uint256 amount` (action 0 credit-attest, 1 release, 2 slash) |
| `Pause` | `uint64 nonce` |
| `Unpause` | `uint64 nonce` |
| `Block` | `uint64 nonce` |
| `Migration` | `uint64 nonce, address target` |

Signatures are 65-byte `(r, s, v)`, low-`s` only, passed sorted by signer address with no
duplicates; every signer MUST be in the current signer set.

### 6.3 Methods

| Method | Who | Rules |
|---|---|---|
| `deposit(amount, creditsTo, maxCsPrice)` | user | Not paused, not `withdrawOnly`; `amount` multiple of 10¹⁰ and ≥ `minDeposit`; `creditsTo ≠ 0`; `userUsdt + amount ≤ cap`. Pulls USDT (measures the balance delta and requires it equal to `amount`). Emits `Deposit(id, from, amount, creditsTo, maxCsPrice)` |
| `claim(id, kind, to, amount, creditsTo, sigs)` | anyone | Not paused; not claimed; `T` valid signatures over `Claim`; `kind 1` only to `migrationTarget` after `migrationTime`; within the daily cap. If `amount > delayThreshold` and the signatures include fewer than `floor(W/2)+1` whitelisted signers (`W` = whitelisted members of the signer set; `W = 0` always delays), the claim is queued for 24 hours; else paid. Marks `claimed[id]` |
| `executeQueued(id)` | anyone | Not paused; `now ≥ unlockTime`; daily cap; pays |
| `updateSigners(SignerSet, sigs)` | anyone | `T` of the current signers; nonce = next; new set non-empty, sorted, ≤ 64; `foundersToAdd` accepted only while not `foundersFrozen` and each must be in the new set; `freezeFounders` sets `foundersFrozen`. Founders not in the new set are removed only if they signed their own `FounderRemoval` or a pending removal matured (below) |
| `requestFounderRemoval(FounderRemoval, sigs)` | anyone | Signed by the founder alone: immediate. Signed by `T` instead: effective after 30 days unless cancelled by a `FounderRemoval` with the same nonce signed by a majority of founders |
| `setWhitelist(Whitelist, sigs)` | anyone | Normal mode: a majority of founders in the signer set, immediate. Fallback mode (`foundersBelowTwoSince` older than 30 days): more than half of all signers, effective after 7 days |
| `setCap(Cap, sigs)` | anyone | `T` signatures. Decreases immediate. Increases after 7 days, at most ×2 per step. While not `foundersFrozen`: `cap ≤ 20,000 USDT`. `dailyCap ≤ cap` |
| `bond(Bond, sigs)` | anyone | Action 0: anyone may pay a bond with `depositBond`; action 1 release: `T` signatures, pays `to` from `bondUsdt`; action 2 slash: `T` signatures, moves to `reserveUsdt` |
| `depositBond(nodeWallet, amount)` | relayer | Adds to `bondUsdt[nodeWallet]`; not counted in `userUsdt` or the cap |
| `pause(Pause, sig)` / `pauseDirect()` | one signer | Immediate |
| `unpause(Unpause, sigs)` | anyone | `T` signatures |
| `block(Block, sigs)` | anyone | `T` signatures (after the Credits vote). Sets `withdrawOnly` forever; records `nextDepositId` |
| `setMigration(Migration, sigs)` | anyone | `T` signatures; only while `withdrawOnly`; effective after 7 days; target a contract |

No function transfers user USDT except `claim`/`executeQueued`. A `kind 1` claim approves the
target and calls `IUsdtVault(target).depositFromMigration(amount, creditsTo)`, which on the new
vault behaves like `deposit` from the old vault, with the new vault's own cap. If the new vault
reverts, the whole claim reverts and the withdrawal stays claimable.

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
- Publisher: writes signed withdrawals and digests as static JSON under `signatureUrl`.
- Store: a local database with cursors and the history of what was signed.

### 7.2 Cursors

| Cursor | Meaning |
|---|---|
| `nextDepositToRead` | Next BSC deposit id to process |
| `nextWithdrawalToSign` | Next Credits withdrawal id to sign |
| `signedWithdrawals[id] = data hash` | Never sign two different data for one id |
| `approvedDeposits[id] = data hash` | Never approve two different data for one id |
| `digestPeriod` | Last digest submitted |

Every cursor and record is written to the store before the corresponding action is sent
("submitted" first), so a restart never repeats an action with different data.

### 7.3 Deposit loop

1. Read `finalized` from each BSC source; use the lowest common block whose hash all sources agree on.
2. Read `Deposit` logs of the vault up to that block; index by `id`; require ids to be
   contiguous from `nextDepositToRead`. A gap means a source is incomplete: retry, never skip.
3. For each new id, check on Credits that it is not minted, then call `approveMint`. If the node
   reports the call failed for a reason other than `done`, retry later.
4. Advance the cursor only after the approval is recorded on Credits or the id is minted.

### 7.4 Withdrawal loop

1. Read withdrawals from Credits by id, starting at `nextWithdrawalToSign`, only from blocks at
   least `credits_confirmations` (3) deep and only while the node is in sync (last block time
   within 60 s of the wall clock).
2. Check the record against the contract's stored hash; build `Claim`; sign; store; publish
   `/<chainId>/<vault>/claims/<id>.json` with the data, the signature and the version.
3. Never sign a withdrawal while the Credits contract is paused, or if the watchdog fails.

### 7.5 Watchdog, every cycle

Invariant (per [§10](#10-invariants), I1):
`cUSDT totalSupply + Σ net amounts of withdrawals not claimed on the vault ≤ userUsdt`.
Bonds and the reserve are counted apart. Also: no mint without a matching finalized deposit; no
claimed withdrawal id without a Credits record with the same hash; vault signer set equal to the
Credits active set (after the latest update). On any failure: pause both contracts, publish the
evidence, stop signing.

### 7.6 State digests

Every digest period (1 hour), each relayer submits `hash(period, lastFinalizedDepositId,
nextWithdrawalId, userUsdt, totalSupply, unpaidWithdrawals, invariantOk, signerSetNonce)`
and publishes the clear values at its URL. The contract counts, per period, the most common
digest. A relayer whose digest differs from the most common one, when that one has at least `T`
submitters, gets a divergence mark.

### 7.7 Code verification

1. **Admitted versions.** The relayer is published as source with reproducible builds; the hash
   of each release is admitted by governance. Approvals and digests carry the version hash; the
   contract refuses unadmitted versions. A retired version stays valid for 14 days.
   This coordinates upgrades; it does not prove what runs.
2. **Consensus on outputs.** Honest relayers compute the same data from the same chains; the
   contract accepts only identical approvals and compares digests.
3. **Automatic consequences.** Divergence in 3 of the last 24 digest periods, or orphan or
   conflicting approvals above 3 in 7 days → `Inactive` until it is back in line. No slashing
   without proof.
4. **Later option.** Remote attestation of the binary on TEE hardware (Intel TDX, AMD SEV).

### 7.8 Keys

- Keys never appear in code, repositories or logs. Files mode `0600`, owned by the relayer user.
- The BSC signer key is used only for EIP-712 signatures; the relayer has no need for BNB.
- The operator key MAY differ from the node wallet; the node wallet only registers, rotates and
  withdraws bonds and can be kept offline.

### 7.9 Restarts

On start: reload cursors; re-read every withdrawal signed in the last 24 hours and check the
published file matches the stored hash; re-check pending approvals. A crash between storing and
sending repeats the same data, which the contracts treat as a duplicate.

---

## 8. Flows

### 8.1 Deposit (BSC → Credits)

1. User approves USDT and calls `deposit(100 USDT, creditsTo, maxCsPrice=0)` on the vault.
2. Each relayer, after finality (≈ 1 s), calls `approveMint(id, to, 100, 0, txHash, version)`.
3. At `T` approvals: fee 0.05 to the fund; conversion budget = 2 % × 99.95 = 1.999 cUSDT;
   CS bought from the lowest asks; the rest credited as cUSDT.
4. Approvals after the mint return `done` and count only for participation.

### 8.2 Withdrawal (Credits → BSC)

1. User calls `burnForBsc(100, 0xBob)`: 0.05 to the fund, 99.95 burned, withdrawal `id` recorded.
2. Relayers sign `Claim(id, 0, 0xBob, 99.95e18, 0)` and publish.
3. The claim page fetches `T` signatures and Bob sends `claim`. Above 1,000 USDT without a
   whitelist majority among the signatures, it is queued for 24 hours, then
   `executeQueued`.

### 8.3 Swap

- Ask: Carol sends 10,000 CS with user data `ask|0.01` → ask id.
- Buy: Alice calls `buy(101, 0)`; she pays 100 cUSDT to Carol's balance plus 0.1 fee to the fund
  and receives 10,000 CS.
- Bid and sell are the mirror image, with the fee taken from the seller's proceeds.

### 8.4 Fees, buyback and rewards

1. Bridge fees and swap fees accumulate in `buybackFund` (cUSDT).
2. At `closeEpoch()` (every 7 days) the contract buys CS from the lowest asks with the whole
   fund (no price limit), then splits the CS bought equally among relayers active for the
   whole epoch with ≥ 80 % participation (approvals of the epoch's minted deposits within 10
   minutes of the mint, plus digests).
3. Each relayer's share: `ownerShare` (20 %) to its owner wallet, the rest to its delegators
   pro rata, using the delegator list attested by `T` relayers for that epoch, at most
   `maxPaidDelegators` (100) largest; the remainder to the owner. Credited to `csClaimable`.
4. If no asks exist, the fund carries over.

### 8.5 Relayer admission

1. Node wallet pays the CS bond (`bond` command) and, on BSC, `depositBond(nodeWallet, 50)`.
2. Node wallet calls `applyRelayer(...)`.
3. Each relayer's software reads the candidate's delegations from its own node
   (`DelegatedItem`: `wallet`, `sum`, `validUntil`, `fromTime`, `coeff`) and attests eligibility:
   - counted: incoming delegations with `coeff` = 1-year term (TO VERIFY the value: `Anni` = 4
     in `StakingCoefficient`), `validUntil > now + 30 days`, from wallets other than the node
     wallet and the declared owner wallet;
   - total counted ≥ 1,000,000 CS; at least 2 distinct donors; no donor above 70 % of the total;
   - warning only (not blocking): donors linked to each other or to the owner by direct
     transfers in the last 6 months.
4. 7-day wait; one third of active relayers may object.
5. `activate`. The relayers sign the new `SignerSet`; anyone submits it to the vault.

### 8.6 Inactivity, delegation drop, divergence

- Participation below 50 % over 14 days → `Inactive`.
- Eligibility attested false → `ineligibleSince`; after 30 days → `Inactive`. Back above →
  `Active` again with the same bond.
- Divergence rule of [§7.7](#77-code-verification).
- `Inactive` relayers are out of `N`, `T` and the signer set; they may `leave()` and recover
  the bond after 30 days, or return to `Active` when the condition clears.

### 8.7 Governance

- A relayer proposes; votes run 14 days; passes with yes > half of active relayers.
- Applies 7 days after passing. Immediate when it only lowers risk: lowering the vault cap or
  the conservative price, retiring a version (with its 14-day grace), a permanent block.
- Hard caps are checked at proposal and at execution.
- Changes needing the vault (cap, block, migration) are then signed by `T` relayers.

### 8.8 Slashing by proof

`proveFalseSignature(id, kind, to, amount, creditsTo, sig)`:

1. Compute the EIP-712 digest of `Claim` with the vault's domain; recover the signer
   (pure-Java secp256k1, low-`s`).
2. The signer must be the `bscSigner` of a relayer that is not `Exited`.
3. False if `id ≥ nextWithdrawalId`, or `hashStruct` differs from the stored one.
4. Then: status `Slashed`, out of the active set; `bondCs` and `bondCusdt` move to the slash
   reserve, minus 10 % of the CS to the prover; the relayers sign `Bond(action=2)` for its
   50 USDT. The prover's wallet must not be the slashed relayer's.

Other signed messages (`SignerSet`, `Cap`, `Bond`) are not provable this way in version 1.

### 8.9 Pause and unpause

Any relayer pauses Credits (`pause`) and BSC (`pause` signature). While paused: no mints, no new
withdrawals, no claims, no new offers or fills; cancels, `claimCs`, `setReturn` and bond
withdrawals that are due remain open. Unpause needs `T` approvals on each chain.

### 8.10 Permanent block and migration

1. Governance passes `block`. Credits: `blocked = true` at once; the relayers sign `Block`.
2. After `Block`, the vault takes no deposits; deposits made before it are still minted.
3. On Credits: no new offers or fills; asks are refunded on request; `burnForBsc` stays open;
   epochs close with what is in the fund.
4. Relayers stay bound for 12 months after the block (bonds locked until then).
5. Optional migration: governance registers new contracts; after 7 days each user may call
   `migrate` instead of `burnForBsc`; the relayers sign `kind 1` claims, paid only to the new
   vault, which credits the user on the new Credits contract.

---

## 9. Failure cases

| Case | Behaviour |
|---|---|
| Fewer than `T` relayers online | Mints and claims wait; nothing is lost; resumes when they return |
| Active relayers below 3 | The relayers sign a `Cap` equal to the current `userUsdt`, so no new deposit fits; deposits already made are still minted; claims continue. The cap is restored by a later `Cap` when there are 3 again |
| One relayer malicious | Cannot reach `T`; false claim signature → slashed by proof; false mint approval → conflict, alarm |
| Threshold malicious | [§3.3](#33-what-is-not-protected) |
| Relayer restart | Cursors and "submitted first" records; duplicates are ignored |
| Lost BSC event (RPC gap) | Ids must be contiguous; a gap stops the loop until both sources agree |
| Duplicate event | Approval of an id already approved or minted returns `done` |
| BSC reorganisation | Only `finalized` blocks are read; finality ≈ 1–2 blocks |
| BSC finality stalls | Relayers wait; no fallback to `latest` |
| Credits node out of sync or forked | Relayer signs only from blocks ≥ 3 deep with a synced node; a mismatch with the contract's stored hash stops signing |
| Credits resync (contract re-execution) | All contract logic depends only on its state, arguments and block time; it never uses `getBalance`; TO VERIFY block time during re-execution |
| Pause and resume | [§8.9](#89-pause-and-unpause); queued claims keep their unlock time and wait for unpause |
| Relayer exits | Signer set update; signatures from the old set are rejected by the vault once updated |
| Bond slashed | Out of the set; vault bond slashed by `T` signatures |
| Conflicting approvals | Mint blocked for that id; the conflict and the approvers are visible; resolution by vote (a proposal that replaces the data with the finalized deposit's data, applied after 7 days) |
| Price manipulation | Free market by decision; conversions limited to 20 cUSDT per deposit; depositor's own `maxCsPrice`; the 7-day average used for entry bonds can be raised by self-trades, which only makes entry dearer |
| Exchange addresses | Returns cannot carry a memo; UI warning; owners can change their return address |
| Executor timeout | Bounded work per call ([§5.11](#511-bounded-work)) |
| Contract CS balance short of liabilities | Cannot happen while I4 holds; emitted amounts are rounded down |

---

## 10. Invariants

1. `totalSupply(cUSDT) + Σ unpaid withdrawals ≤ userUsdt(vault)` (unpaid = recorded on Credits,
   not claimed on the vault, net amounts). Equality minus deposits in flight.
2. A deposit id is minted at most once; a minted id never changes data.
3. A withdrawal id is paid at most once; it is paid only with data equal to the Credits record
   (assuming fewer than `T` dishonest signers).
4. `CS balance of CusdtBridge ≥ csLiabilities` (asks escrow + bonds + claimables + unattributed
   + slash reserve + dust).
5. `Σ balances + Σ bid escrow + buybackFund + Σ bondCusdt + slashReserveCusdt = totalSupply`.
6. `USDT balance of vault ≥ userUsdt + Σ bondUsdt + reserveUsdt`.
7. User USDT leaves the vault only through `claim`/`executeQueued`.
8. `T ≥ 2` on both chains; every governable parameter is within its hard cap.
9. Once `foundersFrozen`, the founder set only shrinks.
10. A relayer's bond requirement never changes after entry.
11. No method has an admin; no code can change after deploy.
12. While `blocked`, no new deposit is accepted and every holder can still withdraw.

---

## 11. Parameters

| Parameter | Initial | Changed by | Hard cap / rule in code |
|---|---|---|---|
| Operational threshold `T` | `max(2, min(N/2+1, 7))` | code | — |
| Minimum active relayers for new deposits | 3 | code | — |
| Delegation minimum | 1,000,000 CS | vote | ≥ 500,000 CS |
| Delegation term | 1 year (`coeff` Anni) | code | — |
| Minimum donors / max share of one donor | 2 / 70 % | vote | ≥ 2 / ≤ 90 % |
| Founders' bond | 100,000 CS + 50 USDT | code | fixed |
| New entrant bond | max(1,000 USDT, 10 % of user USDT) | vote (rate) | rate ≤ 50 %, floor 1,000 USDT |
| Admission wait / objection share | 7 days / one third | code | — |
| Founder phase end | first buy ≥ 100 cUSDT between distinct wallets, 6 months, or 7 relayers | code | — |
| Whitelist fallback | 30 days below 2 founders | code | — |
| Vault cap (founder phase) | 10,000 USDT | vote + `T` signatures | ≤ 20,000 USDT; increases ×2 max per 7 days |
| Vault cap (after) | ≤ bonds of the smallest `T`-coalition × conservative price | vote + `T` | increases ×2 max per 7 days |
| Conservative CS price | set by vote before the phase ends | vote | lowering immediate, raising after 7 days |
| Daily claim cap | 5,000 USDT | vote + `T` | ≤ vault cap |
| Large-claim threshold / delay | 1,000 USDT / 24 h | code | — |
| Minimum deposit / withdrawal | 5 USDT / 5 cUSDT | vote | ≥ 1 |
| Bridge fee | 0.05 cUSDT per direction | vote | ≤ 1 cUSDT |
| Swap fee | 0.1 % (taker) | vote | ≤ 1 % |
| Conversion at mint | 2 %, min 1, max 20 cUSDT | vote | rate ≤ 10 %, max ≤ 100 cUSDT |
| Reward epoch / participation | 7 days / 80 % | code | — |
| Owner share of rewards | 20 % | vote | ≤ 50 % |
| Paid delegators per relayer | 100 | code | — |
| Digest period / divergence rule | 1 hour / 3 in 24 | code | — |
| Inactivity | < 50 % in 14 days | code | — |
| Delegation-drop grace | 30 days | code | — |
| Bond lock after exit | 30 days | code | — |
| Service after permanent block | 12 months | code | — |
| Governance window / delay | 14 days / 7 days | code | — |
| Version grace after retirement | 14 days | code | — |
| Prover reward | 10 % of slashed CS | code | — |

---

## 12. Test plan

### 12.1 Executor harness (no node)

`probes/executor/` today; later `tests/executor/`, run on both executors (community and
official 1518), every answer compared between the two:

- token standard detection (`tokenStandard` 3/4 on community, 0 on 1518 is acceptable for v2;
  this contract uses v1);
- mint at threshold, out-of-order ids, conflicts, `done`, bounded record (measured: 2,000
  deposits × 13 relayers, state ≤ 15.8 KB, median 18 ms per approval);
- withdrawals, proofs (secp256k1 recovery measured: 50/50 correct, 25 ms median), false and
  valid proofs, high-`s` and tampered signatures;
- order book: fills, rounding, fees, limits per call, founder-phase closing rule;
- payable commands and invalid user data;
- epochs and reward allocation, resumable;
- governance timing and hard caps;
- performance at scale: 100,000 withdrawal records, 1,000 offers, 64 relayers.

### 12.2 Private Credits network

`ci/testnet` of the community node with `CONTRACTS=1`, mixed executors (`EXECUTOR_JAR_ALT`):

- the TO VERIFY items of [§13.2](#132-to-verify);
- deploy, mints, burns, swaps, payable commands, emitted CS transfers, state identical on all
  nodes;
- a node restarting and resyncing through all of it (`RESTART_AT`), with re-execution on;
- the token API (`tokens_cache=true`) showing cUSDT balances.

### 12.3 BSC testnet

- vault deployment with test USDT; deposits, claims, queue, caps, pause, block, migration to a
  second vault, signer set updates, founder removal, whitelist fallback;
- Foundry unit and invariant tests (I1 via a model of Credits, I6, I7), fuzzing of signature
  sets.

### 12.4 Relayers, end to end

A harness running N relayer processes against the private Credits network and BSC testnet (or a
local BSC fork), with faults:

| Scenario | Expected |
|---|---|
| `T − 1` relayers offline | Nothing minted or paid; resumes on return |
| One relayer approves wrong data | Conflict, mint blocked, alarm |
| One relayer signs a false claim | Proof slashes it; claim impossible without `T` |
| `T` relayers sign a false claim | Paid up to caps (shows the bound); watchdogs of the others pause |
| RPC source returns a gap or a forked log | Loop stops; no approval |
| Relayer killed between store and send | No double or different action |
| Digest divergence | Marks, then `Inactive` |
| Unadmitted version | Approvals refused |
| Delegations fall below 1M | `Inactive` after 30 days |
| Founders leave | Whitelist fallback after 30 days |

### 12.5 CI

GitHub Actions in this repository: executor harness on both jars on every push; the private
network and BSC-fork end-to-end tests on demand and nightly. Heavy jobs never run on the shared
server.

---

## 13. Runtime facts and what is still to verify

### 13.1 Verified

| Fact | Evidence |
|---|---|
| Contract-to-contract calls fail on mainnet | Node: `Violations::SubsequentCall` for `@UsingContract`; executor 1518: `AccessControlException` on `invokeExternalContract` (analysis of 2026-10-30, harness) |
| Contract → contract CS transfers are refused | `solver/src/smartcontracts.cpp` `test_violations` (`SourceIsContract`), `csnode/src/itervalidator.cpp` (`kContractViolation`) |
| Contract-emitted transfers carry no user data | `solver/src/smartcontracts.cpp`: emitted transfers rebuilt as plain transactions without user fields |
| `payable` receives the text user field | user field id 1 (`cs::trx_uf::ordinary::Text`) passed as `byte[]` |
| A call costs ≈ 0.0175 CS, independent of state size | `csnode/src/fee.cpp`: start tx 0.00874 (< 5 KB), new state 0.00874 (min fee, blocks carry only the state hash), execution 0.00874 CS per second |
| Consensus execution limit 60 s | `Consensus::TimeSmartContract = 60000` |
| `getBlockchainTimeMills()` returns block time | `api/src/executor.cpp`: access id → block of the execution → `BlockChain::getBlockTime` (code read) |
| `getBalance` reads the current balance | `api/src/apihandler.cpp` `APIEXECHandler::WalletBalanceGet` reads wallet data, not the executed block |
| `sendTransaction` takes a `double` | `SmartContract` v3 API; 1234567.123456789012345678 → .123456789 (analysis 2026-10-30) |
| Failed call keeps the old state | Harness: a throw after a write leaves the supply at 0 |
| Approvals scale | Harness: 2,000 deposits, 13 relayers, threshold 7: 14,000 approvals, 2,000 mints, no double mint, median 18 ms, p95 64 ms, max 1.2 s, state 1.8–15.8 KB |
| CS bond in and out | Harness: `payable` 500000.25 recorded; refund emitted 500000.25 exactly |
| secp256k1 in Java | Harness (community executor): 50/50 signers recovered, 25 ms median, 63 ms max; tampered digest and high-`s` rejected |
| BSC finality | `finalized` 1–2 blocks behind `latest` (≈ 0.45–0.9 s) on mainnet and testnet RPCs, 2026-11-06 |
| Delegations readable from the node API | `api.thrift` `DelegatedItem` (`wallet`, `sum`, `validUntil`, `fromTime`, `coeff`); contracts cannot read them |
| Delegation to a contract is refused | `itervalidator.cpp` (`kTransactionProhibited`) |

### 13.2 TO VERIFY

On the private Credits network unless noted:

1. Block time from `getBlockchainTimeMills()` is identical on every node and during
   re-execution while syncing.
2. A `payable` that throws discards the CS transfer (or keeps it: [§5.5](#55-incoming-cs-payable)).
3. Emitted CS transfers: exact amount received after the `double` conversion; who pays their
   fee; several emitted transfers in one call.
4. How the API reports a failed call (`approveMint`, `burnForBsc`, `payable`) to the sender.
5. The official executor 1518 gives identical results for every probe, including the
   secp256k1 recovery and its timing.
6. The time the node actually waits for the executor (`executor_receive_timeout`, 4 s in the
   analysis of 2026-10-30) versus the 60 s consensus limit; bounded work sized to stay below 1 s.
7. `DelegatedItem.coeff` value of a 1-year delegation; whether a 1-year delegation can be
   revoked before `validUntil`.
8. Performance with 100,000 withdrawal records, 1,000 offers and 64 relayers.
9. The token cache shows cUSDT balances after mints, burns, fills and internal moves.
10. The Java classes used (`TreeMap`, `BigInteger`, `BigDecimal`, `String.format`) are allowed
    by the executor sandbox on both executors.

---

## 14. Open questions

1. Use of the slash reserve (CS and USDT): compensate users pro rata after a shortfall, by vote?
2. Withdrawal records grow forever (one hash per id); keep all, or prune claimed ids attested by
   `T` relayers (a pruned id can no longer be proven false)?
3. Should a single-relayer pause stop small claims too (this draft: yes) or let claims up to the
   delay threshold continue within the daily cap?
4. Bids: included in version 1 (this draft: yes, the contract cannot be extended later).
5. Swap fee on the conversion at mint and on the buyback (this draft: on the conversion yes, on
   the buyback no).
6. Who deploys the contracts, and the initial founders.
7. Proofs for other false signed messages (`SignerSet`, `Cap`, `Bond`) in a later version.
8. Whether the objection by one third of relayers during the 7-day wait stays, given automatic
   admission.
