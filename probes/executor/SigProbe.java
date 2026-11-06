import com.credits.scapi.annotations.Getter;
import com.credits.scapi.v3.SmartContract;

import java.math.BigInteger;

/**
 * Probe: can a Credits contract recover the signer of a secp256k1 signature (Ethereum ecrecover)
 * in plain Java, so that a false BSC withdrawal signature can be proven on Credits?
 * Keccak-256 and the curve arithmetic are written out here: the sandbox may not offer them.
 */
public class SigProbe extends SmartContract {

    private String lastSigner = "";

    public SigProbe() {
        super();
    }

    /** digest and signature in hex (no 0x): r(32) s(32) v(1, 27/28 or 0/1); returns the address. */
    public String recover(String digestHex, String sigHex) {
        lastSigner = Secp.recoverAddress(hex(digestHex), hex(sigHex));
        return lastSigner;
    }

    public String keccak(String dataHex) {
        return toHex(Keccak.hash(hex(dataHex)));
    }

    public String payable(java.math.BigDecimal amount, byte[] userData) {
        throw new IllegalStateException("no payments");
    }

    @Getter
    public String lastSigner() {
        return lastSigner;
    }

    static byte[] hex(String s) {
        if (s.startsWith("0x")) s = s.substring(2);
        byte[] b = new byte[s.length() / 2];
        for (int i = 0; i < b.length; i++) b[i] = (byte) Integer.parseInt(s.substring(2 * i, 2 * i + 2), 16);
        return b;
    }

    static String toHex(byte[] b) {
        StringBuilder sb = new StringBuilder();
        for (byte x : b) sb.append(String.format("%02x", x & 0xff));
        return sb.toString();
    }

    static final class Keccak {
        private static final long[] RC = {
            0x0000000000000001L, 0x0000000000008082L, 0x800000000000808aL, 0x8000000080008000L,
            0x000000000000808bL, 0x0000000080000001L, 0x8000000080008081L, 0x8000000000008009L,
            0x000000000000008aL, 0x0000000000000088L, 0x0000000080008009L, 0x000000008000000aL,
            0x000000008000808bL, 0x800000000000008bL, 0x8000000000008089L, 0x8000000000008003L,
            0x8000000000008002L, 0x8000000000000080L, 0x000000000000800aL, 0x800000008000000aL,
            0x8000000080008081L, 0x8000000000008080L, 0x0000000080000001L, 0x8000000080008008L};
        private static final int[] ROT = {0, 1, 62, 28, 27, 36, 44, 6, 55, 20, 3, 10, 43, 25, 39, 41, 45, 15, 21, 8,
            18, 2, 61, 56, 14};

        static byte[] hash(byte[] in) {
            int rate = 136;
            int padded = (in.length / rate + 1) * rate;
            byte[] m = new byte[padded];
            System.arraycopy(in, 0, m, 0, in.length);
            m[in.length] ^= 0x01;
            m[padded - 1] ^= (byte) 0x80;
            long[] a = new long[25];
            for (int off = 0; off < padded; off += rate) {
                for (int i = 0; i < rate / 8; i++) {
                    long v = 0;
                    for (int j = 0; j < 8; j++) v |= (m[off + 8 * i + j] & 0xffL) << (8 * j);
                    a[i] ^= v;
                }
                f(a);
            }
            byte[] out = new byte[32];
            for (int i = 0; i < 32; i++) out[i] = (byte) (a[i / 8] >>> (8 * (i % 8)));
            return out;
        }

        private static void f(long[] a) {
            long[] c = new long[5];
            long[] b = new long[25];
            for (int round = 0; round < 24; round++) {
                for (int x = 0; x < 5; x++) c[x] = a[x] ^ a[x + 5] ^ a[x + 10] ^ a[x + 15] ^ a[x + 20];
                for (int x = 0; x < 5; x++) {
                    long d = c[(x + 4) % 5] ^ Long.rotateLeft(c[(x + 1) % 5], 1);
                    for (int y = 0; y < 25; y += 5) a[y + x] ^= d;
                }
                for (int x = 0; x < 5; x++)
                    for (int y = 0; y < 5; y++)
                        b[y + 5 * ((2 * x + 3 * y) % 5)] = Long.rotateLeft(a[x + 5 * y], ROT[x + 5 * y]);
                for (int x = 0; x < 5; x++)
                    for (int y = 0; y < 25; y += 5)
                        a[y + x] = b[y + x] ^ (~b[y + (x + 1) % 5] & b[y + (x + 2) % 5]);
                a[0] ^= RC[round];
            }
        }
    }

    static final class Secp {
        static final BigInteger P = new BigInteger("fffffffffffffffffffffffffffffffffffffffffffffffffffffffefffffc2f", 16);
        static final BigInteger N = new BigInteger("fffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd0364141", 16);
        static final BigInteger GX = new BigInteger("79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798", 16);
        static final BigInteger GY = new BigInteger("483ada7726a3c4655da4fbfc0e1108a8fd17b448a68554199c47d08ffb10d4b8", 16);
        static final BigInteger HALF_N = N.shiftRight(1);

        /** Ethereum address (0x + 40 hex) of the signer, or "" if the signature is invalid. */
        static String recoverAddress(byte[] digest, byte[] sig) {
            if (digest.length != 32 || sig.length != 65) return "";
            BigInteger r = new BigInteger(1, java.util.Arrays.copyOfRange(sig, 0, 32));
            BigInteger s = new BigInteger(1, java.util.Arrays.copyOfRange(sig, 32, 64));
            int v = sig[64] & 0xff;
            if (v >= 27) v -= 27;
            if (v > 1 || r.signum() == 0 || s.signum() == 0 || r.compareTo(N) >= 0 || s.compareTo(HALF_N) > 0) return "";
            BigInteger x = r;
            BigInteger alpha = x.pow(3).add(BigInteger.valueOf(7)).mod(P);
            BigInteger y = alpha.modPow(P.add(BigInteger.ONE).shiftRight(2), P);
            if (!y.multiply(y).mod(P).equals(alpha)) return "";
            if (y.testBit(0) != (v == 1)) y = P.subtract(y);
            BigInteger e = new BigInteger(1, digest);
            BigInteger rInv = r.modInverse(N);
            BigInteger u1 = e.negate().mod(N).multiply(rInv).mod(N);
            BigInteger u2 = s.multiply(rInv).mod(N);
            BigInteger[] q = add(mul(new BigInteger[]{GX, GY, BigInteger.ONE}, u1), mul(new BigInteger[]{x, y, BigInteger.ONE}, u2));
            if (q[2].signum() == 0) return "";
            BigInteger zInv = q[2].modInverse(P);
            BigInteger z2 = zInv.multiply(zInv).mod(P);
            BigInteger ax = q[0].multiply(z2).mod(P);
            BigInteger ay = q[1].multiply(z2).multiply(zInv).mod(P);
            byte[] pub = new byte[64];
            put32(pub, 0, ax);
            put32(pub, 32, ay);
            byte[] h = Keccak.hash(pub);
            return "0x" + toHex(java.util.Arrays.copyOfRange(h, 12, 32));
        }

        private static void put32(byte[] out, int off, BigInteger v) {
            byte[] b = v.toByteArray();
            int n = Math.min(b.length, 32);
            System.arraycopy(b, b.length - n, out, off + 32 - n, n);
        }

        // Jacobian coordinates (X, Y, Z); Z = 0 is the point at infinity
        private static BigInteger[] dbl(BigInteger[] p) {
            if (p[2].signum() == 0 || p[1].signum() == 0) return new BigInteger[]{BigInteger.ONE, BigInteger.ONE, BigInteger.ZERO};
            BigInteger ysq = p[1].multiply(p[1]).mod(P);
            BigInteger s = p[0].multiply(ysq).shiftLeft(2).mod(P);
            BigInteger m = p[0].multiply(p[0]).multiply(BigInteger.valueOf(3)).mod(P);
            BigInteger nx = m.multiply(m).subtract(s.shiftLeft(1)).mod(P);
            BigInteger ny = m.multiply(s.subtract(nx)).subtract(ysq.multiply(ysq).shiftLeft(3)).mod(P);
            BigInteger nz = p[1].multiply(p[2]).shiftLeft(1).mod(P);
            return new BigInteger[]{nx, ny, nz};
        }

        private static BigInteger[] add(BigInteger[] p, BigInteger[] q) {
            if (p[2].signum() == 0) return q;
            if (q[2].signum() == 0) return p;
            BigInteger pz2 = p[2].multiply(p[2]).mod(P);
            BigInteger qz2 = q[2].multiply(q[2]).mod(P);
            BigInteger u1 = p[0].multiply(qz2).mod(P);
            BigInteger u2 = q[0].multiply(pz2).mod(P);
            BigInteger s1 = p[1].multiply(qz2).multiply(q[2]).mod(P);
            BigInteger s2 = q[1].multiply(pz2).multiply(p[2]).mod(P);
            if (u1.equals(u2)) {
                if (!s1.equals(s2)) return new BigInteger[]{BigInteger.ONE, BigInteger.ONE, BigInteger.ZERO};
                return dbl(p);
            }
            BigInteger h = u2.subtract(u1).mod(P);
            BigInteger r = s2.subtract(s1).mod(P);
            BigInteger h2 = h.multiply(h).mod(P);
            BigInteger h3 = h2.multiply(h).mod(P);
            BigInteger u1h2 = u1.multiply(h2).mod(P);
            BigInteger nx = r.multiply(r).subtract(h3).subtract(u1h2.shiftLeft(1)).mod(P);
            BigInteger ny = r.multiply(u1h2.subtract(nx)).subtract(s1.multiply(h3)).mod(P);
            BigInteger nz = h.multiply(p[2]).multiply(q[2]).mod(P);
            return new BigInteger[]{nx, ny, nz};
        }

        private static BigInteger[] mul(BigInteger[] p, BigInteger k) {
            BigInteger[] r = {BigInteger.ONE, BigInteger.ONE, BigInteger.ZERO};
            for (int i = k.bitLength() - 1; i >= 0; i--) {
                r = dbl(r);
                if (k.testBit(i)) r = add(r, p);
            }
            return r;
        }
    }
}
