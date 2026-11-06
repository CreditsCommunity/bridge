import com.credits.scapi.annotations.Getter;
import com.credits.scapi.v3.SmartContract;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.HashMap;

/**
 * Probe of what only a real node answers: block time, CS balances, payments refused by
 * payable(), CS emitted with user data, and CS emitted to another contract.
 */
public class NetProbe extends SmartContract {

    private final ArrayList<Long> times = new ArrayList<>();
    private final HashMap<String, String> balancesSeen = new HashMap<>();
    private final HashMap<String, BigDecimal> paid = new HashMap<>();
    private String lastUserData = "";
    private int payments;

    public NetProbe() {
        super();
    }

    public long now() {
        long t = getBlockchainTimeMills();
        times.add(t);
        return t;
    }

    public String seeBalance(String wallet) {
        String b = getBalance(wallet).toPlainString();
        balancesSeen.put(wallet, b);
        return b;
    }

    /** CS sent to the contract: accepted only with user data, refused (exception) without. */
    public String payable(BigDecimal amount, byte[] userData) {
        if (userData == null || userData.length == 0) throw new IllegalStateException("payment without user data");
        paid.merge(initiator, amount, BigDecimal::add);
        lastUserData = new String(userData, java.nio.charset.StandardCharsets.UTF_8);
        payments++;
        return "accepted " + amount.toPlainString();
    }

    /** CS out of the contract with user data attached by the contract. */
    public String refund(String to, String amount) {
        sendTransaction(contractAddress, to, Double.parseDouble(amount), "refund-memo".getBytes());
        return "sent " + amount;
    }

    /** CS out of the contract to another contract. */
    public String payContract(String other, String amount) {
        sendTransaction(contractAddress, other, Double.parseDouble(amount));
        return "sent " + amount + " to " + other;
    }

    @Getter
    public String summary() {
        return "times=" + times + " balances=" + balancesSeen + " paid=" + paid + " payments=" + payments
                + " lastUserData=" + lastUserData;
    }
}
