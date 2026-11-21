"""Memoria de rivales: un perfil por alias, guardado en disco.

Los alias (j-a1b2c3) son estables durante todo el torneo, así que lo que
aprendemos de un rival en la ronda 1 sirve si nos lo cruzamos en la ronda 7,
y sobrevive a un reinicio del bot.

Todas las tasas usan un "prior": antes de ver a un rival suponemos que juega
como un bot promedio, y vamos corrigiendo con cada mano observada. Así no
sacamos conclusiones exageradas de 3 manos.
"""

import json
import os
import tempfile

from .cartas import desde_protocolo
from .equidad import _conexion, percentil

AGRESIVAS = ("bet", "raise")


def _tasa(eventos, oportunidades, prior, peso):
    return (eventos + prior * peso) / (oportunidades + peso)


class Perfil:
    CAMPOS = ("manos", "vpip", "pfr", "pre_enfrenta", "pre_fold",
              "post_agr", "post_pas", "post_chk", "post_enfrenta", "post_fold",
              "sd_agresivo", "faroles", "sd_total",
              "sd_sube_n", "sd_sube_pct", "sd_paga_n", "sd_paga_pct")

    def __init__(self, datos=None, factor_prior=1.0):
        # factor_prior < 1: confía antes en lo observado (aprende más rápido).
        self.fp = factor_prior
        for c in self.CAMPOS:
            setattr(self, c, 0)
        if datos:
            for c in self.CAMPOS:
                setattr(self, c, int(datos.get(c, 0)))

    def a_dict(self):
        return {c: getattr(self, c) for c in self.CAMPOS}

    # --- Tasas estimadas ------------------------------------------------
    @property
    def tasa_vpip(self):
        """Con qué frecuencia pone fichas voluntariamente preflop."""
        return _tasa(self.vpip, self.manos, 0.35, 10 * self.fp)

    @property
    def tasa_pfr(self):
        """Con qué frecuencia sube preflop."""
        return _tasa(self.pfr, self.manos, 0.18, 10 * self.fp)

    @property
    def fold_preflop(self):
        """Cuánto se retira ante una subida preflop."""
        return _tasa(self.pre_fold, self.pre_enfrenta, 0.55, 8 * self.fp)

    @property
    def fold_postflop(self):
        """Cuánto se retira ante una apuesta después del flop."""
        return _tasa(self.post_fold, self.post_enfrenta, 0.45, 8 * self.fp)

    @property
    def agresion(self):
        """Fracción de sus acciones postflop que son apuestas o subidas."""
        total = self.post_agr + self.post_pas + self.post_chk
        return _tasa(self.post_agr, total, 0.3, 8 * self.fp)

    @property
    def farol(self):
        """Cuando apuesta fuerte hasta el showdown, qué tan seguido no tiene nada."""
        base = _tasa(self.faroles, self.sd_agresivo, 0.25, 4 * self.fp)
        # Un rival muy agresivo en general también farolea más.
        return min(0.85, max(0.05, base * (0.6 + self.agresion * 1.4)))

    @staticmethod
    def _mezclar(estimado, n, suma_pct):
        """Corrige el ancho estimado con las manos que el rival mostró.

        Si un rango es "el mejor X %", el percentil medio de sus manos es X/2.
        Así, si sube mucho con basura, lo vemos en el showdown y ampliamos.
        """
        if n == 0:
            return estimado
        visto = min(0.97, 2 * (suma_pct / 1000.0) / n)
        w = n / (n + 6.0)
        return (1 - w) * estimado + w * max(visto, estimado * 0.7)

    @property
    def ancho_subida(self):
        base = self._mezclar(self.tasa_pfr * 1.1, self.sd_sube_n, self.sd_sube_pct)
        return min(0.97, max(0.04, base))

    @property
    def ancho_pago(self):
        base = self._mezclar(self.tasa_vpip, self.sd_paga_n, self.sd_paga_pct)
        return min(0.97, max(0.08, base))

    def estilo(self):
        if self.manos < max(3, int(8 * self.fp)):
            return "desconocido"
        v, a = self.tasa_vpip, self.agresion
        if v < 0.22:
            return "roca" if a < 0.4 else "selectivo-agresivo"
        if v > 0.55:
            return "maníaco" if a >= 0.45 else "pagador"
        return "agresivo" if a >= 0.45 else "equilibrado"

    def resumen(self):
        return (f"{self.estilo()} ({self.manos} manos, juega {self.tasa_vpip:.0%}, "
                f"sube {self.tasa_pfr:.0%}, se retira {self.fold_postflop:.0%}, "
                f"farol {self.farol:.0%})")


def reconstruir(estado_inicio, historial):
    """Repite las acciones de una mano y devuelve lo que hizo cada jugador.

    Devuelve dict id -> lista de dicts {etapa, tipo, subio, enfrentaba},
    además de quién fue el último agresor de cada etapa y cuántas subidas hubo.
    """
    pila = {}
    aporte = {}
    actual = 0
    if estado_inicio:
        for j in estado_inicio.get("jugadores") or []:
            # Los eliminados siguen en la lista con su última apuesta: se ignoran.
            if not j.get("en_mano", True) or not j.get("en_torneo", True):
                continue
            pila[j["id"]] = j.get("saldo", 0)
            aporte[j["id"]] = j.get("apuesta_ronda", 0)
        actual = max(aporte.values(), default=0)
    pozo = sum(aporte.values())
    etapa = "preflop"
    acciones = {}
    agresor = {}
    subidas = {}
    for h in historial or []:
        pid = h.get("id_jugador")
        acc = h.get("accion") or {}
        tipo = acc.get("tipo", "")
        if h.get("etapa", etapa) != etapa:
            etapa = h.get("etapa")
            aporte = {k: 0 for k in aporte}
            actual = 0
        previo = aporte.get(pid, 0)
        enfrentaba = actual > previo
        if tipo == "call":
            nuevo = min(actual, previo + pila.get(pid, 10 ** 9))
        elif tipo in AGRESIVAS:
            nuevo = int(acc.get("monto", actual))
        elif tipo == "allin":
            nuevo = previo + pila.get(pid, 0)
        else:
            nuevo = previo
        subio = nuevo > actual
        # Tamaño de la subida relativo al bote que había (0.5 = medio bote).
        tam = (nuevo - actual) / max(1, pozo + max(0, actual - previo)) if subio else 0.0
        pozo += max(0, nuevo - previo)
        if pid in pila:
            pila[pid] = max(0, pila[pid] - (nuevo - previo))
        aporte[pid] = nuevo
        if subio:
            actual = nuevo
            agresor[etapa] = pid
            subidas[etapa] = subidas.get(etapa, 0) + 1
        acciones.setdefault(pid, []).append(
            {"etapa": etapa, "tipo": tipo, "subio": subio, "enfrentaba": enfrentaba,
             "tam": tam, "resubida": subio and enfrentaba})
    return acciones, agresor, subidas


class Memoria:
    def __init__(self, ruta, factor_prior=1.0):
        self.ruta = ruta
        self.factor_prior = factor_prior
        self.perfiles = {}
        self.meta = {}
        if ruta and os.path.exists(ruta):
            try:
                with open(ruta, encoding="utf-8") as f:
                    datos = json.load(f)
                self.perfiles = {k: Perfil(v, factor_prior) for k, v in datos.get("rivales", {}).items()}
                self.meta = datos.get("meta", {})
            except (OSError, ValueError):
                self.perfiles = {}

    def perfil(self, alias):
        p = self.perfiles.get(alias)
        if p is None:
            p = self.perfiles[alias] = Perfil(factor_prior=self.factor_prior)
        return p

    def guardar(self):
        if not self.ruta:
            return
        datos = {"meta": self.meta,
                 "rivales": {k: v.a_dict() for k, v in self.perfiles.items()}}
        carpeta = os.path.dirname(os.path.abspath(self.ruta))
        os.makedirs(carpeta, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=carpeta, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(datos, f)
            os.replace(tmp, self.ruta)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass

    def aprender(self, mi_id, estado_inicio, historial, resultado):
        """Actualiza los perfiles con una mano terminada."""
        acciones, agresor, _ = reconstruir(estado_inicio, historial)
        en_mano = [j["id"] for j in ((estado_inicio or {}).get("jugadores") or [])
                   if j.get("en_mano", True)]
        for pid in en_mano:
            if pid == mi_id:
                continue
            p = self.perfil(pid)
            p.manos += 1
            lista = acciones.get(pid, [])
            pre = [a for a in lista if a["etapa"] == "preflop"]
            if any(a["tipo"] in ("call", "bet", "raise", "allin") for a in pre):
                p.vpip += 1
            if any(a["subio"] for a in pre):
                p.pfr += 1
            for a in pre:
                # Enfrentar una subida real (no solo la ciega grande).
                if a["enfrentaba"] and a["tipo"] in ("fold", "call", "raise", "allin"):
                    p.pre_enfrenta += 1
                    if a["tipo"] == "fold":
                        p.pre_fold += 1
            for a in lista:
                if a["etapa"] == "preflop":
                    continue
                if a["subio"]:
                    p.post_agr += 1
                elif a["tipo"] in ("call", "allin"):
                    p.post_pas += 1
                elif a["tipo"] == "check":
                    p.post_chk += 1
                if a["enfrentaba"]:
                    p.post_enfrenta += 1
                    if a["tipo"] == "fold":
                        p.post_fold += 1

        mostradas = (resultado or {}).get("mostradas") or {}
        mesa = [desde_protocolo(c) for c in (resultado or {}).get("comunitarias") or []]
        for pid, cartas in mostradas.items():
            if pid == mi_id or len(cartas) != 2 or len(mesa) < 5:
                continue
            p = self.perfil(pid)
            p.sd_total += 1
            c1, c2 = (desde_protocolo(c) for c in cartas)
            pre = [a for a in acciones.get(pid, []) if a["etapa"] == "preflop"]
            pct = int(percentil(c1, c2) * 1000)
            if any(a["subio"] for a in pre):
                p.sd_sube_n += 1
                p.sd_sube_pct += pct
            elif any(a["tipo"] in ("call", "allin") for a in pre):
                p.sd_paga_n += 1
                p.sd_paga_pct += pct
            fue_agresivo = agresor.get("river") == pid or agresor.get("turn") == pid
            if fue_agresivo:
                p.sd_agresivo += 1
                if _conexion(c1, c2, mesa) == 2:
                    p.faroles += 1
