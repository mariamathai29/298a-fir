
N_TAPS = 4
W_BITS = 14        # weight register width, Q2.12
W_EXT = 4          # extra fractional bits below the FIR's Q2.8
MU_Q_DEFAULT = 1   # mu = 2^-12

def _range(bits):
    return -(1 << (bits - 1)), (1 << (bits - 1)) - 1


def sat(v, bits):
    lo, hi = _range(bits)
    return max(lo, min(hi, v)), (v < lo or v > hi)


def check(v, bits, name):
    lo, hi = _range(bits)
    assert lo <= v <= hi, f"{name}={v} overflows signed {bits}-bit"
    return v


def sign(v):
    return (v > 0) - (v < 0)  # sign(0) = 0


class AdaptiveFilter:
    def __init__(self, mu_q=MU_Q_DEFAULT):
        self.mu_q = mu_q
        self.adapt_en = True
        self.reset()

    def reset(self):
        self.w = [0] * N_TAPS   # Q2.12
        self.x = [0] * N_TAPS   # Q1.7, x[0] = newest
        self.sat_flag = False   # sticky, like debug_o2

    def rst_taps(self):
        self.x = [0] * N_TAPS

    def weights_q28(self):
        return [w >> W_EXT for w in self.w]

    def rst_wts(self):
        self.w = [0] * N_TAPS

    def load_wt(self, k, value):
        self.w[k] = check(value, 10, "w") << W_EXT

    def step(self, u, r=0, e_in=0):
        check(u, 8, "u"); check(r, 8, "r"); check(e_in, 8, "e_in")

        # Shift delay line, then FIR over x[n]..x[n-7]
        self.x = [u] + self.x[:-1]
        acc = 0
        for k in range(N_TAPS):
            acc += check(self.x[k] * self.w[k], 22, "product")
        check(acc, 24, "acc")

        # Q5.19 -> Q1.7: round half up (add 2^7, drop 8 LSBs), saturate to 8 bits
        y, s1 = sat((acc + (1 << 11)) >> 12, 8)

        e_cue = check(r - y, 9, "e_int")
        e_out, s2 = sat(e_cue, 8)

        # Sign-sign LMS, same x vector that produced y
        s3 = False
        if self.adapt_en:
            se = sign(e_cue)
            for k in range(N_TAPS):
                self.w[k], s = sat(self.w[k] + self.mu_q * se * sign(self.x[k]), W_BITS)
                s3 |= s

        self.sat_flag |= s1 or s2 or s3
        return y, e_out


def to_q(v, frac_bits, bits):
    return sat(int(round(v * (1 << frac_bits))), bits)[0]
