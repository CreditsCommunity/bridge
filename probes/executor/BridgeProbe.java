import com.credits.scapi.annotations.Getter;
import com.credits.scapi.v3.SmartContract;

import java.math.BigDecimal;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

/**
 * Probe, not the real cUSDT: measures what the bridge design needs from the Credits runtime.
 * - approval counting per deposit id, mint at a threshold, conflict on differing data;
 * - a bounded record of minted ids (watermark plus the ids above it);
 * - sequential withdrawal ids from burns;
 * - CS received through payable() as a relayer bond, refunded with sendTransaction;
 * - block time and CS balance as a contract sees them.
 */
public class BridgeProbe extends SmartContract {

    private static final class Pending implements java.io.Serializable {
        final String to;
        final BigDecimal amount;
        final HashSet<String> approvers = new HashSet<>();
        Pending(String to, BigDecimal amount) { this.to = to; this.amount = amount; }
    }

    private final HashSet<String> relayers = new HashSet<>();
    private int threshold;
    private final HashMap<String, BigDecimal> balances = new HashMap<>();
    private BigDecimal supply = BigDecimal.ZERO;
    private final HashMap<Long, Pending> pending = new HashMap<>();
    private long mintedBelow;                       // every id < mintedBelow is minted
    private final TreeSet<Long> mintedAbove = new TreeSet<>();
    private final HashSet<Long> conflicts = new HashSet<>();
    private long nextWithdrawalId;
    private final HashMap<Long, String> withdrawals = new HashMap<>();
    private final HashMap<String, BigDecimal> bonds = new HashMap<>();

    public BridgeProbe() {
        super();
    }

    public void setup(String relayerList, int threshold) {
        if (!relayers.isEmpty()) throw new IllegalStateException("already set up");
        for (String r : relayerList.split(",")) relayers.add(r);
        this.threshold = threshold;
    }

    public String approveMint(long depositId, String to, BigDecimal amount) {
        if (!relayers.contains(initiator)) throw new IllegalStateException("not a relayer");
        if (depositId < mintedBelow || mintedAbove.contains(depositId)) return "done";
        if (conflicts.contains(depositId)) return "conflict";
        Pending p = pending.get(depositId);
        if (p == null) {
            p = new Pending(to, amount);
            pending.put(depositId, p);
        } else if (!p.to.equals(to) || p.amount.compareTo(amount) != 0) {
            conflicts.add(depositId);
            pending.remove(depositId);
            return "conflict";
        }
        p.approvers.add(initiator);
        if (p.approvers.size() < threshold) return "pending " + p.approvers.size();
        pending.remove(depositId);
        balances.merge(to, amount, BigDecimal::add);
        supply = supply.add(amount);
        mintedAbove.add(depositId);
        while (mintedAbove.contains(mintedBelow)) mintedAbove.remove(mintedBelow++);
        return "minted";
    }

    public long burnForBsc(BigDecimal amount, String bscAddress) {
        BigDecimal b = balances.getOrDefault(initiator, BigDecimal.ZERO);
        if (amount.signum() <= 0 || b.compareTo(amount) < 0) throw new IllegalStateException("balance");
        balances.put(initiator, b.subtract(amount));
        supply = supply.subtract(amount);
        long id = nextWithdrawalId++;
        withdrawals.put(id, initiator + "|" + bscAddress + "|" + amount.toPlainString());
        return id;
    }

    public String failAfterWrite() {
        supply = supply.add(BigDecimal.ONE);
        throw new IllegalStateException("thrown after a write");
    }

    public String payable(BigDecimal amount, byte[] userData) {
        bonds.merge(initiator, amount, BigDecimal::add);
        return "bond " + bonds.get(initiator).toPlainString();
    }

    public String refundBond() {
        BigDecimal b = bonds.remove(initiator);
        if (b == null) throw new IllegalStateException("no bond");
        sendTransaction(contractAddress, initiator, b.doubleValue());
        return b.toPlainString();
    }

    public long now() {
        return getBlockchainTimeMills();
    }

    public String csBalance(String wallet) {
        return getBalance(wallet).toPlainString();
    }

    @Getter
    public String totalSupply() {
        return supply.toPlainString();
    }

    @Getter
    public String balanceOf(String owner) {
        return balances.getOrDefault(owner, BigDecimal.ZERO).toPlainString();
    }

    @Getter
    public String stats() {
        return "pending=" + pending.size() + " mintedBelow=" + mintedBelow + " mintedAbove=" + mintedAbove.size()
                + " conflicts=" + conflicts.size() + " withdrawals=" + withdrawals.size();
    }
}
