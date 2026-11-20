"""Minimal ristretto255 group (RFC 9496) in pure Python.

Only what the OPAQUE client needs: decode, encode, add, scalar multiply and
the one-way map used by hash-to-group. Python integers are not constant time;
every secret handled here is ephemeral and lives a few milliseconds.
"""

P = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493  # group order


def _inv(x):
    return pow(x, P - 2, P)


def _is_neg(x):
    return x % P & 1


def _abs(x):
    x %= P
    return P - x if x & 1 else x


D = (-121665 * _inv(121666)) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)


def _sqrt_ratio_m1(u, v):
    """Return (was_square, sqrt(u/v)) with a non-negative root."""
    u %= P
    v %= P
    v3 = v * v % P * v % P
    v7 = v3 * v3 % P * v % P
    r = u * v3 % P * pow(u * v7 % P, (P - 5) // 8, P) % P
    check = v * r % P * r % P
    correct = check == u
    flipped = check == (-u) % P
    flipped_i = check == (-u * SQRT_M1) % P
    if flipped or flipped_i:
        r = r * SQRT_M1 % P
    return correct or flipped, _abs(r)


def _sqrt(x):
    ok, r = _sqrt_ratio_m1(x, 1)
    if not ok:
        raise ValueError('not a square')
    return r


# RFC 9496 picks the "negative" (odd) root for this constant.
SQRT_AD_MINUS_ONE = P - _sqrt((-D - 1) % P)
INVSQRT_A_MINUS_D = _sqrt_ratio_m1(1, (-1 - D) % P)[1]
ONE_MINUS_D_SQ = (1 - D * D) % P
D_MINUS_ONE_SQ = (D - 1) * (D - 1) % P
D2 = 2 * D % P


class Point:
    """Point in extended twisted Edwards coordinates (X:Y:Z:T)."""

    __slots__ = ('X', 'Y', 'Z', 'T')

    def __init__(self, X, Y, Z, T):
        self.X, self.Y, self.Z, self.T = X % P, Y % P, Z % P, T % P

    def __add__(self, o):
        a = (self.Y - self.X) * (o.Y - o.X) % P
        b = (self.Y + self.X) * (o.Y + o.X) % P
        c = self.T * D2 % P * o.T % P
        d = 2 * self.Z * o.Z % P
        e, f, g, h = b - a, d - c, d + c, b + a
        return Point(e * f, g * h, f * g, e * h)

    def double(self):
        a = self.X * self.X % P
        b = self.Y * self.Y % P
        c = 2 * self.Z * self.Z % P
        e = ((self.X + self.Y) ** 2 - a - b) % P
        g = (b - a) % P
        f = (g - c) % P
        h = (-a - b) % P
        return Point(e * f, g * h, f * g, e * h)

    def __mul__(self, k):
        k %= L
        # 4-bit fixed window: 64 additions + 252 doublings.
        table = [IDENTITY, self]
        for _ in range(14):
            table.append(table[-1] + self)
        acc = IDENTITY
        for shift in range(252, -1, -4):
            acc = acc.double().double().double().double()
            acc = acc + table[(k >> shift) & 15]
        return acc

    __rmul__ = __mul__

    def __eq__(self, o):
        return (self.X * o.Y - self.Y * o.X) % P == 0 or (self.Y * o.Y - self.X * o.X) % P == 0

    def __hash__(self):
        return hash(self.encode())

    def is_identity(self):
        return self == IDENTITY

    def encode(self):
        x0, y0, z0, t0 = self.X, self.Y, self.Z, self.T
        u1 = (z0 + y0) * (z0 - y0) % P
        u2 = x0 * y0 % P
        _, invsqrt = _sqrt_ratio_m1(1, u1 * u2 % P * u2 % P)
        den1 = invsqrt * u1 % P
        den2 = invsqrt * u2 % P
        z_inv = den1 * den2 % P * t0 % P
        if _is_neg(t0 * z_inv):
            x, y = y0 * SQRT_M1 % P, x0 * SQRT_M1 % P
            den_inv = den1 * INVSQRT_A_MINUS_D % P
        else:
            x, y, den_inv = x0, y0, den2
        if _is_neg(x * z_inv):
            y = -y
        s = _abs(den_inv * (z0 - y))
        return s.to_bytes(32, 'little')

    @staticmethod
    def decode(data):
        if len(data) != 32:
            raise ValueError('invalid ristretto255 encoding length')
        s = int.from_bytes(data, 'little')
        if s >= P or s & 1:
            raise ValueError('non-canonical ristretto255 encoding')
        ss = s * s % P
        u1 = (1 - ss) % P
        u2 = (1 + ss) % P
        u2_sqr = u2 * u2 % P
        v = (-(D * u1 % P * u1) - u2_sqr) % P
        was_square, invsqrt = _sqrt_ratio_m1(1, v * u2_sqr % P)
        den_x = invsqrt * u2 % P
        den_y = invsqrt * den_x % P * v % P
        x = _abs(2 * s * den_x)
        y = u1 * den_y % P
        t = x * y % P
        if not was_square or _is_neg(t) or y == 0:
            raise ValueError('invalid ristretto255 encoding')
        return Point(x, y, 1, t)

    @staticmethod
    def _map(t):
        r = SQRT_M1 * t % P * t % P
        u = (r + 1) * ONE_MINUS_D_SQ % P
        v = (-1 - r * D) * (r + D) % P
        was_square, s = _sqrt_ratio_m1(u, v)
        if was_square:
            c = P - 1
        else:
            s = (-_abs(s * t)) % P
            c = r
        n = (c * (r - 1) % P * D_MINUS_ONE_SQ - v) % P
        w0 = 2 * s * v % P
        w1 = n * SQRT_AD_MINUS_ONE % P
        w2 = (1 - s * s) % P
        w3 = (1 + s * s) % P
        return Point(w0 * w3, w2 * w1, w1 * w3, w0 * w2)

    @staticmethod
    def from_uniform_bytes(data):
        if len(data) != 64:
            raise ValueError('expected 64 uniform bytes')
        mask = (1 << 255) - 1
        r0 = (int.from_bytes(data[:32], 'little') & mask) % P
        r1 = (int.from_bytes(data[32:], 'little') & mask) % P
        return Point._map(r0) + Point._map(r1)


IDENTITY = Point(0, 1, 1, 0)

_BY = 4 * _inv(5) % P
_BX = _sqrt((_BY * _BY - 1) * _inv(D * _BY * _BY + 1) % P)
BASE = Point(_BX, _BY, 1, _BX * _BY)


def scalar_from_bytes(data):
    """Canonical 32-byte little-endian scalar, as used for private keys."""
    k = int.from_bytes(data, 'little')
    if k >= L:
        raise ValueError('non-canonical scalar')
    return k


def scalar_to_bytes(k):
    return (k % L).to_bytes(32, 'little')
