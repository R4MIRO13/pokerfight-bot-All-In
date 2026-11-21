"""Controladores: personalidades que cambian de estilo durante el juego.

Un controlador decide, antes de cada jugada, qué estilo usar (por ejemplo,
el meta-bot elige entre 4 estilos según cuál le está dando más fichas).
Algunos además toman la decisión ellos mismos (el comité, el kamikaze).

Todo lo que deben recordar entre mesas lo guardan en memoria.meta, que se
graba en disco junto a la memoria de rivales.
"""

import math
import random

from .estilos import BASE, ESTILOS, HU_NUMEROS, HU_SIN, UNO_CONTRA_UNO
from .estrategia import _pagar, _segura, decidir, validar

NUMEROS = ("apertura", "tam_apuesta", "valor", "faroles", "riesgo", "piso")


def modo_uno_contra_uno(base):
    """Modo uno contra uno sobre un estilo: conserva sus lecturas de rivales,
    deja los comportamientos de supervivencia y presiona más."""
    d = dict(base)
    for k in HU_SIN:
        d.pop(k, None)
    d.update(HU_NUMEROS)
    d["perfiles"] = max(base.get("perfiles", 0), 1.0)
    return d


def _mezcla(nombre_base, **cambios):
    d = dict(ESTILOS[nombre_base])
    d.update(cambios)
    return d


class Controlador:
    """Estilo fijo (con modo uno contra uno si la personalidad lo pide)."""

    def __init__(self, nombre, memoria, log):
        self.nombre = nombre
        self.memoria = memoria
        self.log = log
        self.base = ESTILOS[nombre]
        self.actual = nombre

    def _hu(self, info):
        return self.base.get("hu_experto") and info["vivos"] == 2

    def estilo(self, info):
        if self._hu(info):
            self.actual = f"{self.nombre}: uno contra uno"
            return modo_uno_contra_uno(self.base)
        self.actual = self.nombre
        return self.base

    def decidir(self, ctx):
        """None = usar la estrategia normal con el estilo elegido."""
        return None

    def nueva_mesa(self, info):
        pass

    def fin_mano(self, info):
        pass


class Adaptativo(Controlador):
    def estilo(self, info):
        self.actual = "prudente" if info["pila"] < info["pila_inicio_mesa"] else "equilibrado"
        return ESTILOS[self.actual]


class Gestor(Controlador):
    def estilo(self, info):
        r = info["pila"] / max(1, info["pila_inicio_mesa"])
        self.actual = "tortuga" if r >= 1.5 else "prudente" if r <= 0.6 else "equilibrado"
        return ESTILOS[self.actual]


class Cerrador(Controlador):
    def estilo(self, info):
        if info["mano_mesa"] >= 40:
            self.actual = "tortuga" if info["pila"] >= info["pila_inicio_mesa"] else "agresivo"
        else:
            self.actual = "equilibrado"
        return ESTILOS[self.actual]


class Meta(Controlador):
    OBJETIVO = 3000

    def estilo(self, info):
        logrado = info["pila"] >= info["pila_inicio_mesa"] + self.OBJETIVO
        self.actual = "tortuga" if logrado else "equilibrado"
        return ESTILOS[self.actual]


class Observador(Controlador):
    def estilo(self, info):
        if info["mano_mesa"] <= 12:
            self.actual = "tortuga"
            return ESTILOS["tortuga"]
        self.actual = "clasificador"
        return _mezcla("clasificador", perfiles=1.5)


class Lector(Controlador):
    """Cada 10 manos mira a los rivales de la mesa y elige el estilo que mejor les gana."""

    def __init__(self, *a):
        super().__init__(*a)
        self.actual = "equilibrado"

    def estilo(self, info):
        if info["mano_mesa"] % 10 == 1 and info["rivales"]:
            perfiles = [self.memoria.perfil(r) for r in info["rivales"]]
            vpip = sum(p.tasa_vpip for p in perfiles) / len(perfiles)
            fold = sum(p.fold_preflop for p in perfiles) / len(perfiles)
            agr = sum(p.agresion for p in perfiles) / len(perfiles)
            if vpip > 0.5:
                nuevo = "antimaniaco"
            elif fold > 0.6:
                nuevo = "ladron"
            elif agr > 0.45:
                nuevo = "trampero"
            else:
                nuevo = "equilibrado"
            if nuevo != self.actual:
                self.log(f"Lector: la mesa juega {vpip:.0%} de manos, se retira {fold:.0%} "
                         f"y agrede {agr:.0%} -> cambio a {nuevo}")
            self.actual = nuevo
        return ESTILOS[self.actual]


class MetaBot(Controlador):
    """Bandido multibrazo: prueba estilos en bloques de 8 manos y repite el que más gana."""

    BRAZOS = ("equilibrado", "agresivo", "prudente", "farolero")
    BLOQUE = 8

    def __init__(self, *a):
        super().__init__(*a)
        self.stats = self.memoria.meta.setdefault("metabot", {b: [0, 0.0] for b in self.BRAZOS})
        self.actual = None
        self.manos_bloque = 0
        self.pila_bloque = None

    def _elegir(self):
        total = sum(n for n, _ in self.stats.values())
        for b in self.BRAZOS:
            if self.stats[b][0] == 0:
                return b

        def ucb(b):
            n, suma = self.stats[b]
            return suma / n + 3.0 * math.sqrt(math.log(total + 1) / n)
        return max(self.BRAZOS, key=ucb)

    def estilo(self, info):
        if self.actual is None:
            self.actual = self._elegir()
            self.pila_bloque = info["pila"]
            self.manos_bloque = 0
        return ESTILOS[self.actual]

    def fin_mano(self, info):
        if self.actual is None:
            return
        self.manos_bloque += 1
        if self.manos_bloque >= self.BLOQUE or info["pila"] <= 0:
            premio = (info["pila"] - self.pila_bloque) / max(1, info["bb"]) / self.manos_bloque
            n, suma = self.stats[self.actual]
            self.stats[self.actual] = [n + 1, suma + premio]
            previo = self.actual
            self.actual = None
            elegido = self._elegir()
            if elegido != previo:
                self.log(f"Meta-bot: {previo} rindió {premio:+.1f} ciegas/mano; ahora pruebo {elegido}")


class Entrenador(Controlador):
    """Entre mesas revisa cómo le fue y corrige sus propios parámetros."""

    def __init__(self, *a):
        super().__init__(*a)
        self.params = self.memoria.meta.setdefault("entrenador", {k: BASE[k] for k in NUMEROS})
        self.pila_mesa = None

    def nueva_mesa(self, info):
        hist = self.memoria.meta.get("entrenador_ultima")
        if hist:
            res = hist["final"] - hist["inicio"]
            p = self.params
            if res < -3000:
                p["riesgo"] = min(2.5, p["riesgo"] + 0.25)
                p["apertura"] = max(0.6, p["apertura"] - 0.08)
                p["faroles"] = max(0.3, p["faroles"] - 0.15)
                consejo = "perdí mucho: más cuidado con la pila, menos manos y menos faroles"
            elif res > 3000:
                p["apertura"] = min(1.5, p["apertura"] + 0.05)
                p["faroles"] = min(2.0, p["faroles"] + 0.1)
                consejo = "gané bien: abro un poco más y presiono más"
            else:
                consejo = "resultado parejo: mantengo el plan"
            self.log(f"Entrenador: la mesa anterior terminó {res:+d}. {consejo}. "
                     f"Parámetros: " + ", ".join(f"{k}={v:.2f}" for k, v in p.items()))
        else:
            self.log("Entrenador: primera mesa, empiezo con los parámetros del equilibrado")
        self.memoria.meta["entrenador_ultima"] = {"inicio": info["pila"], "final": info["pila"]}

    def fin_mano(self, info):
        ult = self.memoria.meta.get("entrenador_ultima")
        if ult is not None:
            ult["final"] = info["pila"]

    def estilo(self, info):
        d = dict(ESTILOS["equilibrado"])
        d.update(self.params)
        return d


class Evolutivo(Controlador):
    """Población de 6 variantes; cada mesa prueba una, y las peores se reemplazan por mutaciones de las mejores."""

    TAM = 6

    def __init__(self, *a):
        super().__init__(*a)
        evo = self.memoria.meta.get("evolutivo")
        if not evo:
            pob = [{"params": {k: BASE[k] for k in NUMEROS}, "puntos": 0.0, "mesas": 0}]
            while len(pob) < self.TAM:
                pob.append({"params": self._mutar(pob[0]["params"], 0.25), "puntos": 0.0, "mesas": 0})
            evo = {"poblacion": pob, "actual": 0, "generacion": 1}
            self.memoria.meta["evolutivo"] = evo
        self.evo = evo
        self.inicio = None

    @staticmethod
    def _mutar(params, fuerza):
        nuevo = {}
        for k, v in params.items():
            if k in ("valor", "piso"):
                nuevo[k] = max(-0.1, min(0.15, v + random.gauss(0, 0.04 * fuerza / 0.25)))
            else:
                nuevo[k] = max(0.3, min(2.5, v * math.exp(random.gauss(0, fuerza))))
        return nuevo

    def nueva_mesa(self, info):
        pob = self.evo["poblacion"]
        if self.inicio is not None:
            pass  # el resultado de la mesa anterior ya se sumó en fin_mano
        if all(ind["mesas"] >= 1 for ind in pob):
            pob.sort(key=lambda ind: ind["puntos"] / ind["mesas"], reverse=True)
            for i in range(self.TAM - 2, self.TAM):
                padre = pob[i - (self.TAM - 2)]
                pob[i] = {"params": self._mutar(padre["params"], 0.2), "puntos": 0.0, "mesas": 0}
            self.evo["generacion"] += 1
            self.log(f"Evolutivo: generación {self.evo['generacion']}; la mejor variante: "
                     + ", ".join(f"{k}={v:.2f}" for k, v in pob[0]["params"].items()))
        self.evo["actual"] = min(range(len(pob)), key=lambda i: pob[i]["mesas"])
        pob[self.evo["actual"]]["mesas"] += 1
        self.log(f"Evolutivo: en esta mesa pruebo la variante {self.evo['actual'] + 1} de "
                 f"{len(pob)} (generación {self.evo['generacion']}): "
                 + ", ".join(f"{k}={v:.2f}" for k, v in pob[self.evo["actual"]]["params"].items()))
        self.inicio = info["pila"]

    def fin_mano(self, info):
        if self.inicio is None:
            return
        ind = self.evo["poblacion"][self.evo["actual"]]
        ind["puntos"] += (info["pila"] - info["pila_previa"]) / max(1, info["bb"])

    def estilo(self, info):
        d = dict(ESTILOS["equilibrado"])
        d.update(self.evo["poblacion"][self.evo["actual"]]["params"])
        return d


class Comite(Controlador):
    """Tres estilos votan cada jugada; gana la mayoría (fold / pasivo / agresivo)."""

    MIEMBROS = ("prudente", "equilibrado", "agresivo")

    @staticmethod
    def _clase(accion):
        t = accion["tipo"]
        if t == "fold":
            return "retirarse"
        if t in ("check", "call"):
            return "pasivo"
        return "agresivo"

    def decidir(self, ctx):
        votos = {}
        original = ctx.e
        for m in self.MIEMBROS:
            ctx.e = ESTILOS[m]
            accion, _ = decidir(ctx)
            votos[m] = accion
        ctx.e = original
        clases = {m: self._clase(a) for m, a in votos.items()}
        conteo = {}
        for c in clases.values():
            conteo[c] = conteo.get(c, 0) + 1
        ganadora, n = max(conteo.items(), key=lambda kv: kv[1])
        if n == 1:
            accion = votos["equilibrado"]
            ganadora = clases["equilibrado"]
        else:
            # Entre los que votaron igual, preferimos la opinión del equilibrado.
            elegido = "equilibrado" if clases["equilibrado"] == ganadora else next(
                m for m in self.MIEMBROS if clases[m] == ganadora)
            accion = votos[elegido]
        detalle = ", ".join(f"{m}: {c}" for m, c in clases.items())
        return validar(ctx, accion), f"Comité ({detalle}) -> gana {ganadora}"


class Kamikaze(Controlador):
    """All-in en su primera mano; luego solo ciegas salvo equidad >= 90 %; experto en uno contra uno."""

    def estilo(self, info):
        if info["vivos"] == 2:
            self.actual = "uno contra uno"
            return UNO_CONTRA_UNO
        self.actual = "kamikaze"
        return ESTILOS["equilibrado"]

    def decidir(self, ctx):
        if not self.memoria.meta.get("kamikaze_allin_hecho"):
            self.memoria.meta["kamikaze_allin_hecho"] = True
            if "allin" in ctx.validas:
                return {"tipo": "allin"}, "Kamikaze: primera mano del torneo, ALL-IN sin mirar las cartas"
        vivos = sum(1 for j in ctx.jugadores if j.get("en_torneo", True))
        if vivos == 2:
            return None  # modo uno contra uno: estrategia normal con el estilo de especialista
        rangos = [ctx.rango_de(j["id"]) for j in ctx.rivales]
        eq, _ = ctx.equidad(rangos, max(0.15, min(1.0, ctx.timeout_ms / 1000.0 * 0.1)))
        if eq >= 0.90:
            accion, razon = decidir(ctx)
            return accion, f"Kamikaze: equidad {eq:.0%} >= 90 %, juego en serio | {razon}"
        if ctx.etapa == "preflop" and ctx.mi_apuesta + ctx.por_pagar <= ctx.bb:
            return _pagar(ctx), f"Kamikaze: equidad {eq:.0%}, solo pongo la ciega"
        return _segura(ctx), f"Kamikaze: equidad {eq:.0%} < 90 %, no pongo más que la ciega"


class Fases(Controlador):
    """Híbrido por fases: un estilo para la ronda 1, otro para las rondas 2-10,
    otro para la final y, opcionalmente, modo uno contra uno cuando en la final
    queda un solo rival. Con candado: si las fichas alcanzan para clasificar aun
    perdiendo todas las ciegas que faltan, deja de apostar hasta la final."""

    CIEGAS_POR_RONDA = 1750   # lo que se pierde por ronda sin apostar (medido en simulaciones)
    RONDAS = 10

    def __init__(self, *a):
        super().__init__(*a)
        self.cfg = self.base["fases"]
        nombres = {self.cfg["r1"], self.cfg["rondas"], self.cfg["final"]}
        self.subs = {n: crear(n, self.memoria, self.log) for n in nombres}
        self.cerrado = False
        self.fase = None

    def _candado(self, info):
        limite = self.cfg.get("candado")
        if not limite or info["modo"] == "final" or info["ronda"] < self.cfg.get("candado_desde", 2):
            return False
        faltan = max(0, self.RONDAS - info["ronda"] + 1)
        margen = info["pila"] - faltan * self.cfg.get("ciegas_ronda", self.CIEGAS_POR_RONDA)
        if not self.cerrado and margen > limite:
            self.cerrado = True
            self.log(f"Candado: tengo {info['pila']} fichas en la ronda {info['ronda']}; "
                     f"aun perdiendo {faltan} rondas de ciegas me quedan {margen} > {limite}. "
                     f"Dejo de apostar hasta la final.")
        return self.cerrado

    def estilo(self, info):
        if info["modo"] == "final":
            self.cerrado = False
            nombre, fase = self.cfg["final"], "final"
        elif info["ronda"] <= 1:
            nombre, fase = self.cfg["r1"], "ronda 1"
        else:
            nombre, fase = self.cfg["rondas"], f"ronda {info['ronda']}"
        self._candado(info)
        sub = self.subs[nombre]
        d = sub.estilo(info)
        if info["modo"] == "final" and self.cfg.get("hu") and info["vivos"] == 2:
            d = modo_uno_contra_uno(d)
            self.actual = f"{fase}: {nombre} uno contra uno"
        elif self.cerrado:
            self.actual = f"{fase}: candado"
        else:
            self.actual = f"{fase}: {sub.actual}"
        self.fase = nombre
        return d

    def decidir(self, ctx):
        if self.cerrado:
            return _segura(ctx), "Candado activado: clasificación asegurada, no apuesto hasta la final"
        return self.subs[self.fase].decidir(ctx) if self.fase else None

    def nueva_mesa(self, info):
        for sub in self.subs.values():
            sub.nueva_mesa(info)

    def fin_mano(self, info):
        for sub in self.subs.values():
            sub.fin_mano(info)


CONTROLADORES = {
    "adaptativo": Adaptativo, "gestor": Gestor, "cerrador": Cerrador, "meta": Meta,
    "observador": Observador, "lector": Lector, "metabot": MetaBot, "entrenador": Entrenador,
    "evolutivo": Evolutivo, "comite": Comite, "kamikaze": Kamikaze, "fases": Fases,
}


def crear(nombre, memoria, log):
    clase = CONTROLADORES.get(ESTILOS[nombre].get("controlador"), Controlador)
    return clase(nombre, memoria, log)
