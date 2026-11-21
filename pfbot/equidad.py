"""Probabilidad de ganar (equidad) por simulación Monte Carlo.

A diferencia de la transmisión de TV, el bot no ve las cartas de los rivales.
Por eso imagina miles de repartos posibles y cuenta cuántos gana. La clave
está en NO imaginar cartas totalmente al azar: cada rival recibe manos
coherentes con lo que ha hecho (su "rango"), según su perfil.
"""

import math
import random
import time
from bisect import bisect_left

from .cartas import MAZO, RANGOS, evaluar
from .tablas import PERCENTIL


def clase_preflop(c1, c2):
    """Dos cartas -> "AKs", "QQ", "72o"."""
    r1, r2 = c1 >> 2, c2 >> 2
    a, b = max(r1, r2), min(r1, r2)
    if a == b:
        return RANGOS[a - 2] * 2
    return RANGOS[a - 2] + RANGOS[b - 2] + ("s" if (c1 & 3) == (c2 & 3) else "o")


# Percentil de cada par de cartas, indexado por los enteros de las cartas.
_PCT = [[1.0] * 60 for _ in range(60)]
for _a in MAZO:
    for _b in MAZO:
        if _a != _b:
            _PCT[_a][_b] = PERCENTIL[clase_preflop(_a, _b)]


def percentil(c1, c2):
    return _PCT[c1][c2]


class Rango:
    """Lo que creemos que puede tener un rival en esta mano.

    ancho: fracción de manos con las que entra así preflop (0.15 = el mejor 15 %).
    nivel: después del flop, fracción de su rango que sigue apostando/pagando
           así (0.3 = solo el 30 % más fuerte de lo que podría tener). None si
           no ha mostrado nada después del flop.
    farol: probabilidad de que una mano fuera de ese nivel igual esté ahí.
    """

    __slots__ = ("ancho", "nivel", "farol", "proyecto")

    def __init__(self, ancho=1.0, nivel=None, farol=0.3, proyecto=0.7):
        self.ancho = ancho
        self.nivel = nivel
        self.farol = farol
        self.proyecto = proyecto

    def peso_preflop(self, c1, c2):
        p = _PCT[c1][c2]
        if p <= self.ancho:
            return 1.0
        return math.exp(-(p - self.ancho) / (0.12 * self.ancho + 0.008))

    def pesos(self, combos, mesa):
        """Peso de cada combinación posible para este rival."""
        w = [self.peso_preflop(a, b) for a, b in combos]
        if self.nivel is None or len(mesa) < 3:
            return w
        # Ordenamos su rango por fuerza en ESTA mesa y nos quedamos con la parte
        # de arriba: quien apuesta fuerte suele tener manos fuertes.
        valores = [evaluar([a, b] + mesa) for a, b in combos]
        orden = sorted(range(len(combos)), key=valores.__getitem__, reverse=True)
        total = sum(w) or 1.0
        acumulado = 0.0
        resultado = w[:]
        basura = []          # índices fuera del nivel y sin proyecto
        fuerte = 0.0
        i = 0
        while i < len(orden):
            # Manos de igual valor comparten percentil.
            j = i
            bloque = 0.0
            while j < len(orden) and valores[orden[j]] == valores[orden[i]]:
                bloque += w[orden[j]]
                j += 1
            q = (acumulado + bloque / 2) / total
            for k in orden[i:j]:
                f = 1.0 if q <= self.nivel else math.exp(-(q - self.nivel) / 0.04)
                if f < 0.5 and len(mesa) < 5:
                    a, b = combos[k]
                    if _conexion(a, b, mesa) == 1:
                        f = max(f, self.proyecto)
                if f < 0.05:
                    basura.append(k)
                else:
                    resultado[k] = w[k] * f
                    fuerte += resultado[k]
            acumulado += bloque
            i = j
        # Los faroles son una FRACCIÓN del rango final, no un piso de peso.
        masa_basura = sum(w[k] for k in basura)
        if masa_basura > 0:
            farol = min(0.7, max(0.0, self.farol))
            escala = min(1.0, (farol / (1 - farol)) * fuerte / masa_basura) if fuerte else 1.0
            for k in basura:
                resultado[k] = w[k] * escala
        return resultado


def _conexion(c1, c2, mesa):
    """0 = tiene al menos par usando sus cartas, 1 = proyecto, 2 = nada."""
    r1, r2 = c1 >> 2, c2 >> 2
    rangos_mesa = [c >> 2 for c in mesa]
    if r1 == r2 or r1 in rangos_mesa or r2 in rangos_mesa:
        return 0
    if (evaluar([c1, c2] + list(mesa)) >> 32) >= 4:  # escalera o color hecho
        return 0
    if len(mesa) < 5:
        palos = [c & 3 for c in mesa]
        if (c1 & 3) == (c2 & 3) and palos.count(c1 & 3) >= 2:
            return 1
        if palos.count(c1 & 3) >= 3 or palos.count(c2 & 3) >= 3:
            return 1
        todos = set(rangos_mesa) | {r1, r2}
        if 14 in todos:
            todos.add(1)
        for bajo in range(1, 11):
            if sum(1 for r in range(bajo, bajo + 5) if r in todos) >= 4 and (
                    any(bajo <= r < bajo + 5 for r in (r1, r2))):
                return 1
        if min(r1, r2) > max(rangos_mesa):  # dos cartas por encima
            return 1
    return 2


def equidad(mias, mesa, rangos, tiempo_max=0.6, max_sims=20000, min_sims=300):
    """Fracción de botes que ganamos (los empates cuentan su parte).

    mias: nuestras 2 cartas. mesa: 0-5 comunitarias. rangos: un Rango por
    rival que sigue en la mano. Devuelve (equidad, simulaciones).
    """
    if not rangos:
        return 1.0, 0
    conocidas = set(mias) | set(mesa)
    mazo = [c for c in MAZO if c not in conocidas]
    combos = [(a, b) for i, a in enumerate(mazo) for b in mazo[i + 1:]]
    faltan = 5 - len(mesa)
    n = len(rangos)

    # Para cada rival, lista acumulada de pesos sobre todas sus combinaciones.
    acumulados = []
    for rango in rangos:
        acc = []
        total = 0.0
        for peso in rango.pesos(combos, mesa):
            total += peso
            acc.append(total)
        if total <= 0:
            acc = list(range(1, len(combos) + 1))
            total = float(len(combos))
        acumulados.append((acc, total))

    limite = time.perf_counter() + tiempo_max
    azar = random.random
    muestra = random.sample
    ncombos = len(combos)
    ganadas = 0.0
    sims = 0
    while sims < max_sims:
        if sims >= min_sims and (sims & 127) == 0 and time.perf_counter() > limite:
            break
        usadas = set()
        manos = []
        for acc, total in acumulados:
            for _ in range(20):
                j = bisect_left(acc, azar() * total)
                if j >= ncombos:
                    j = ncombos - 1
                a, b = combos[j]
                if a not in usadas and b not in usadas:
                    break
            else:
                break
            usadas.add(a)
            usadas.add(b)
            manos.append((a, b))
        if len(manos) < n:
            continue
        tablero = list(mesa)
        if faltan:
            for c in muestra(mazo, faltan + 2 * n):
                if c not in usadas:
                    tablero.append(c)
                    if len(tablero) == 5:
                        break
        yo = evaluar(list(mias) + tablero)
        mejor = 0
        empates = 0
        for a, b in manos:
            v = evaluar([a, b] + tablero)
            if v > mejor:
                mejor = v
                empates = 1 if v == yo else 0
            elif v == mejor and v == yo:
                empates += 1
        if yo > mejor:
            ganadas += 1
        elif yo == mejor:
            ganadas += 1.0 / (1 + empates)
        sims += 1
    return (ganadas / sims if sims else 0.0), sims
