"""Cartas y evaluador de manos de 7 cartas, en Python puro y rápido.

Una carta es un entero: rango * 4 + palo, con rango 2..14 (14 = as) y
palo 0..3 (tréboles, diamantes, corazones, picas), igual que en el protocolo.

`evaluar(cartas)` devuelve un entero: mientras más alto, mejor la mano.
Dos manos de igual valor empatan (los palos no desempatan).
"""

RANGOS = "23456789TJQKA"
PALOS = "cdhs"

CATEGORIAS = [
    "carta alta", "par", "doble par", "trío", "escalera",
    "color", "full house", "póker", "escalera de color",
]


def desde_protocolo(carta):
    """{"rango": 14, "palo": 3} -> entero."""
    return carta["rango"] * 4 + carta["palo"]


def legible(c):
    """Entero -> "As"."""
    return RANGOS[(c >> 2) - 2] + PALOS[c & 3]


def legibles(cartas):
    return " ".join(legible(c) for c in cartas)


MAZO = [r * 4 + p for r in range(2, 15) for p in range(4)]

# ---------------------------------------------------------------------------
# Tablas precalculadas sobre máscaras de 15 bits (bit r = rango r presente).
# ---------------------------------------------------------------------------
_N = 1 << 15


def _construir_tablas():
    recta = [0] * _N        # rango más alto de la mejor escalera, o 0
    top = [[0] * _N for _ in range(6)]  # top[k][m]: los k bits más altos de m
    for m in range(_N):
        # Escalera: el as (bit 14) también cuenta como 1 (bit 1).
        mm = m | 2 if m & (1 << 14) else m
        for alto in range(14, 4, -1):
            v = 0b11111 << (alto - 4)
            if mm & v == v:
                recta[m] = alto
                break
        x = m
        bits = []
        while x and len(bits) < 5:
            b = x.bit_length() - 1
            bits.append(1 << b)
            x ^= 1 << b
        acc = 0
        for k in range(1, 6):
            if k <= len(bits):
                acc |= bits[k - 1]
            top[k][m] = acc
    return recta, top


_RECTA, _TOP = _construir_tablas()
_TOP1, _TOP2, _TOP3, _TOP5 = _TOP[1], _TOP[2], _TOP[3], _TOP[5]
_POP = [bin(m).count("1") for m in range(_N)]


def evaluar(cartas):
    """Valor de la mejor mano de 5 entre 5 a 7 cartas."""
    m1 = m2 = m3 = m4 = 0
    s0 = s1 = s2 = s3 = 0
    for c in cartas:
        b = 1 << (c >> 2)
        p = c & 3
        if p == 0:
            s0 |= b
        elif p == 1:
            s1 |= b
        elif p == 2:
            s2 |= b
        else:
            s3 |= b
        if m1 & b:
            if m2 & b:
                if m3 & b:
                    m4 |= b
                else:
                    m3 |= b
            else:
                m2 |= b
        else:
            m1 |= b

    color = 0
    for s in (s0, s1, s2, s3):
        if _POP[s] >= 5:
            color = s
            break
    if color:
        r = _RECTA[color]
        if r:
            return (8 << 32) | (r << 20)

    if m4:
        q = m4.bit_length() - 1
        return (7 << 32) | (q << 20) | _TOP1[m1 & ~(1 << q)]
    if m3:
        t = m3.bit_length() - 1
        resto = m2 & ~(1 << t)
        if resto:
            pr = resto.bit_length() - 1
            return (6 << 32) | (t << 20) | (pr << 16)
    if color:
        return (5 << 32) | _TOP5[color]
    r = _RECTA[m1]
    if r:
        return (4 << 32) | (r << 20)
    if m3:
        t = m3.bit_length() - 1
        return (3 << 32) | (t << 20) | _TOP2[m1 & ~(1 << t)]
    if m2:
        p1 = m2.bit_length() - 1
        resto = m2 & ~(1 << p1)
        if resto:
            p2 = resto.bit_length() - 1
            return (2 << 32) | (p1 << 20) | (p2 << 16) | _TOP1[m1 & ~((1 << p1) | (1 << p2))]
        return (1 << 32) | (p1 << 20) | _TOP3[m1 & ~(1 << p1)]
    return _TOP5[m1]


def categoria(valor):
    """0 = carta alta ... 8 = escalera de color."""
    return valor >> 32


def nombre_categoria(valor):
    return CATEGORIAS[valor >> 32]
