"""El cerebro: decide cada jugada y explica por qué.

Idea general
------------
1. Estimar la equidad (probabilidad de ganar) con Monte Carlo, imaginando a
   cada rival con manos coherentes con su perfil y con lo que hizo en la mano.
2. Compararla con las pot odds: lo que cuesta pagar frente a lo que se gana.
3. Ajustar por posición, número de rivales, riesgo de quedar eliminado y
   tendencias del rival (si se retira mucho, farolear; si paga todo, no).

Cada decisión devuelve también un texto legible para la bitácora.
"""

import random

from .cartas import legibles
from .equidad import Rango, clase_preflop, equidad, percentil
from .rivales import Perfil, reconstruir
from .estilos import ESTILOS, POR_DEFECTO

_NEUTRAL = Perfil()

# Ancho de apertura (fracción de manos) según cuántos jugadores faltan por hablar.
APERTURA = {0: 0.15, 1: 0.45, 2: 0.36, 3: 0.27, 4: 0.21, 5: 0.17, 6: 0.15}


class Contexto:
    """Todo lo que se sabe al momento de decidir."""

    def __init__(self, mensaje, mis_cartas, mi_id, estado_inicio, memoria, modo="clasificatoria",
                 estilo=POR_DEFECTO, mano_mesa=1, pila_inicio_mesa=None):
        self.estado = mensaje.get("estado") or {}
        self.validas = mensaje.get("acciones_validas") or []
        self.timeout_ms = mensaje.get("timeout_ms") or 5000
        self.cartas = mis_cartas
        self.mi_id = mi_id
        self.memoria = memoria
        self.modo = modo
        self.e = estilo if isinstance(estilo, dict) else ESTILOS.get(estilo, ESTILOS[POR_DEFECTO])
        if self.e.get("final"):
            self.modo = "final"
        self.mano_mesa = mano_mesa
        self._cache_eq = {}
        self.inicio = estado_inicio or self.estado

        e = self.estado
        self.jugadores = e.get("jugadores") or []
        self.yo = next((j for j in self.jugadores if j.get("id") == mi_id),
                       {"saldo": 0, "apuesta_ronda": 0, "posicion_silla": -1})
        self.etapa = e.get("etapa", "preflop")
        from .cartas import desde_protocolo
        self.mesa = [desde_protocolo(c) for c in (e.get("comunitarias") or [])]
        self.bb = e.get("ciega_grande") or 100
        self.pozo = e.get("pozo", 0)
        self.apuesta_actual = e.get("apuesta_actual", 0)
        self.mi_apuesta = self.yo.get("apuesta_ronda", 0)
        self.saldo = self.yo.get("saldo", 0)
        self.techo = self.saldo + self.mi_apuesta
        self.por_pagar = min(max(0, self.apuesta_actual - self.mi_apuesta), self.saldo)
        self.min_subida = self.apuesta_actual + max(e.get("subida_minima", 0), self.bb)
        self.rivales = [j for j in self.jugadores
                        if j.get("id") != mi_id and j.get("activo") and j.get("en_mano", True)
                        and j.get("en_torneo", True)]
        self.acciones, self.agresor, self.subidas = reconstruir(self.inicio, e.get("historial_acciones"))
        self.pila_inicio_mesa = pila_inicio_mesa or self.techo

    # --- Utilidades para las personalidades ------------------------------
    def f(self, clave, defecto=None):
        return self.e.get(clave, defecto)

    def perfil(self, pid):
        """Perfil del rival; neutral si la personalidad no usa lecturas."""
        return _NEUTRAL if self.e.get("neutral") else self.memoria.perfil(pid)

    def pila_de(self, j):
        return j.get("saldo", 0) + j.get("apuesta_ronda", 0)

    def me_cubre(self, j, factor=0.9):
        return self.pila_de(j) >= max(1, self.techo) * factor

    def equidad(self, rangos, tiempo):
        """Equidad con memoria: si varias personalidades preguntan lo mismo, se calcula una vez."""
        clave = (len(self.mesa), tuple((r.ancho, r.nivel, r.farol, r.proyecto) for r in rangos))
        if clave not in self._cache_eq:
            self._cache_eq[clave] = equidad(self.cartas, self.mesa, rangos, tiempo_max=tiempo)
        return self._cache_eq[clave]

    # --- Posición -----------------------------------------------------
    def _orden(self, preflop):
        """Ids de los jugadores en mano, en el orden en que hablan."""
        en_mano = [j for j in self.jugadores if j.get("en_mano", True) and j.get("en_torneo", True)]
        en_mano.sort(key=lambda j: j.get("posicion_silla", 0))
        boton = self.estado.get("posicion_boton", 0)
        despues = [j for j in en_mano if j.get("posicion_silla", 0) > boton]
        antes = [j for j in en_mano if j.get("posicion_silla", 0) <= boton]
        orden = [j["id"] for j in despues + antes]  # empieza en la ciega chica
        if preflop:
            if len(orden) == 2:
                orden = orden[::-1]  # heads-up: el botón (ciega chica) habla primero
            else:
                orden = orden[2:] + orden[:2]
        return orden

    def detras(self):
        """Rivales que todavía hablan después de mí en esta ronda (preflop)."""
        orden = self._orden(preflop=True)
        if self.mi_id not in orden:
            return []
        i = orden.index(self.mi_id)
        activos = {j["id"] for j in self.rivales if not j.get("allin")}
        return [pid for pid in orden[i + 1:] if pid in activos]

    def en_posicion(self):
        """True si después del flop hablo último entre los que siguen."""
        orden = [pid for pid in self._orden(preflop=False)
                 if pid == self.mi_id or pid in {j["id"] for j in self.rivales}]
        return bool(orden) and orden[-1] == self.mi_id

    # --- Rangos de los rivales -------------------------------------------
    def rango_de(self, pid):
        p = self.perfil(pid)
        acts = self.acciones.get(pid, [])
        pre = [a for a in acts if a["etapa"] == "preflop"]
        subidas_pre = sum(1 for a in pre if a["subio"])
        ancho = 1.0
        if subidas_pre:
            ancho = p.ancho_subida
            if self.subidas.get("preflop", 0) >= 2 and pre and pre[-1]["subio"]:
                # Resubida: rango más fuerte, salvo en jugadores que suben con todo.
                ancho *= 0.4 + 0.6 * max(0.0, (ancho - 0.3) / 0.7)
            if any(a["tipo"] == "allin" and a["subio"] for a in pre):
                # Un all-in de un jugador que sube con todo no es necesariamente fuerte.
                ancho = max(ancho, p.ancho_subida * (0.5 if p.manos < 15 else 0.9))
        elif any(a["tipo"] in ("call", "allin") for a in pre):
            ancho = p.ancho_pago
        post = [a for a in acts if a["etapa"] != "preflop"]
        if not post:
            return Rango(ancho, None, p.farol)
        # Qué tan arriba de su rango debe estar según cómo apostó.
        # Un agresivo/maníaco apuesta con más manos: su "nivel" es más ancho.
        soltura = min(1.6, max(0.7, (p.agresion / 0.3) ** 0.5))
        nivel = 1.0
        farol = p.farol
        calles_agresivas = 0
        for a in post:
            if a["subio"]:
                calles_agresivas += 1
                n = 0.60 - 0.35 * min(a["tam"], 1.5)       # medio bote ~0.43, bote ~0.25, sobreapuesta ~0.08
                if a["resubida"]:
                    n *= 0.5                                 # subir sobre una apuesta: fuerte
                    farol *= 0.7
                # Las apuestas enormes casi nunca son farol, sobre todo en jugadores pasivos.
                farol *= max(0.3, 1.15 - 0.55 * min(a["tam"], 1.5))
                if p.agresion < 0.3:
                    farol *= 0.7
                nivel = min(nivel, n * soltura) * (0.85 if calles_agresivas > 1 else 1.0)
            elif a["tipo"] in ("call", "allin") and a["enfrentaba"]:
                nivel = min(1.0, nivel * 0.8 if nivel < 1.0 else 0.72 * soltura)
        if nivel >= 1.0:
            return Rango(ancho, None, farol)
        nivel = max(0.06, min(0.95, nivel))
        proyecto = min(0.6, 0.15 + nivel * 0.8)   # proyectos: menos creíbles ante apuestas grandes
        return Rango(ancho, nivel, max(0.04, min(0.6, farol * 0.8)), proyecto)


# ---------------------------------------------------------------------------
# Construcción de acciones siempre válidas
# ---------------------------------------------------------------------------

def _segura(ctx):
    if "check" in ctx.validas:
        return {"tipo": "check"}
    return {"tipo": "fold"}


def _pagar(ctx):
    if ctx.por_pagar == 0 and "check" in ctx.validas:
        return {"tipo": "check"}
    if "call" in ctx.validas:
        return {"tipo": "call"}
    if "allin" in ctx.validas:  # no alcanza para pagar completo
        return {"tipo": "allin"}
    return _segura(ctx)


def _apostar(ctx, total):
    """Llevar la apuesta de la ronda a `total` (monto TOTAL, no incremento)."""
    tipo = "bet" if "bet" in ctx.validas else ("raise" if "raise" in ctx.validas else None)
    total = int(total)
    # Si después de apostar quedaría casi nada, mejor ir all-in.
    if total >= ctx.techo * 0.75 or ctx.min_subida > ctx.techo or tipo is None:
        if "allin" in ctx.validas and total >= ctx.min_subida * 0.9:
            return {"tipo": "allin"}
        if tipo is None:
            return _pagar(ctx)
    total = max(ctx.min_subida, min(total, ctx.techo))
    if total >= ctx.techo and "allin" in ctx.validas:
        return {"tipo": "allin"}
    return {"tipo": tipo, "monto": total}


def validar(ctx, accion):
    """Última barrera: nunca mandar algo que la mesa vaya a rechazar."""
    t = accion.get("tipo")
    if t not in ctx.validas:
        if t in ("bet", "raise") and "allin" in ctx.validas:
            return {"tipo": "allin"}
        return _segura(ctx)
    if t in ("bet", "raise"):
        m = int(accion.get("monto", 0))
        if m < ctx.min_subida or m > ctx.techo:
            if ctx.min_subida > ctx.techo and "allin" in ctx.validas:
                return {"tipo": "allin"}
            m = max(ctx.min_subida, min(m, ctx.techo))
        return {"tipo": t, "monto": m}
    return {"tipo": t}


# ---------------------------------------------------------------------------
# Decisión
# ---------------------------------------------------------------------------

def _riesgo(ctx, costo):
    """Margen extra de equidad exigido cuando una jugada arriesga el torneo.

    En la clasificatoria quedar sin fichas es definitivo y muchos bots se
    eliminan solos: sobrevivir vale más que una ventaja pequeña. Solo aplica
    si algún rival nos cubre (si no nos cubre, perder no nos elimina).
    """
    mi_pila = max(1, ctx.saldo + ctx.mi_apuesta)
    nos_cubren = any(ctx.me_cubre(j) for j in ctx.rivales)
    fraccion = costo / mi_pila
    final = ctx.modo == "final"
    if not nos_cubren:
        return 0.0 if fraccion < 0.6 else 0.02
    if fraccion >= 0.6:
        return (0.05 if final else 0.09) * ctx.e["riesgo"]
    if fraccion >= 0.3:
        return (0.03 if final else 0.05) * ctx.e["riesgo"]
    return 0.0


def _piso_supervivencia(ctx, costo):
    """Equidad mínima para jugarse casi toda la pila contra alguien que nos cubre."""
    mi_pila = max(1, ctx.saldo + ctx.mi_apuesta)
    if costo / mi_pila < 0.6:
        return 0.0
    if not any(ctx.me_cubre(j) for j in ctx.rivales):
        return 0.0
    return (0.38 if ctx.modo == "final" else 0.45) + ctx.e["piso"]


def _tiempo(ctx, fraccion):
    return max(0.15, min(1.2, ctx.timeout_ms / 1000.0 * fraccion))


def _lecturas(ctx, pids):
    """Ajustes de las personalidades que explotan perfiles (clasificador, anti-kit...).

    Devuelve (multiplicador de faroles, delta de margen para pagar, multiplicador de tamaño).
    """
    fuerza = ctx.f("perfiles", 0)
    if not fuerza or not pids:
        return 1.0, 0.0, 1.0, ""
    farol, margen, tam = 1.0, 0.0, 1.0
    etiquetas = []
    for pid in pids:
        estilo = ctx.perfil(pid).estilo()
        etiquetas.append(estilo)
        if estilo == "roca":
            farol *= 1 + 0.4 * fuerza          # se retira mucho: robarle
            margen += 0.02 * fuerza            # cuando apuesta, tiene
        elif estilo == "selectivo-agresivo":
            margen += 0.01 * fuerza
        elif estilo == "maníaco":
            farol /= 1 + 0.5 * fuerza          # no se retira: no farolear
            margen -= 0.03 * fuerza            # apuesta con cualquier cosa: pagar más
        elif estilo == "pagador":
            farol /= 1 + 1.0 * fuerza
            tam *= 1 + 0.15 * fuerza           # cobrarle más grande
        elif estilo == "agresivo":
            margen -= 0.015 * fuerza
    n = len(pids)
    return farol, margen / n, tam, "lectura: " + ", ".join(sorted(set(etiquetas)))


def _utilidad_icm(ctx, eq):
    """¿Pagar sube el valor de torneo? Las fichas valen como raíz cuadrada (cada ficha extra vale menos)."""
    pila = ctx.saldo
    c = ctx.por_pagar
    gana = (pila + ctx.pozo) ** 0.5
    pierde = max(0, pila - c) ** 0.5
    return eq * gana + (1 - eq) * pierde > pila ** 0.5


def _pagar_o_no(ctx, eq, necesaria, margen, piso):
    """Decisión común de pagar, con los ajustes de ICM y aleatoriedad."""
    if ctx.f("icm") and ctx.por_pagar > 0.25 * max(1, ctx.techo):
        return _utilidad_icm(ctx, eq), "ICM"
    umbral = max(necesaria + margen, piso)
    paga = eq >= umbral
    aleat = ctx.f("aleatorio", 0)
    if aleat and abs(eq - umbral) < 0.06 and random.random() < aleat:
        return not paga, "al azar"
    return paga, ""


def _tam_aleatorio(ctx, monto):
    if ctx.f("aleatorio"):
        return monto * random.uniform(0.7, 1.4)
    return monto


def decidir(ctx):
    """Devuelve (accion, explicacion)."""
    c1, c2 = ctx.cartas
    if ctx.etapa == "preflop" or not ctx.mesa:
        accion, razon = _preflop(ctx, c1, c2)
    else:
        accion, razon = _postflop(ctx, c1, c2)
    return validar(ctx, accion), razon


def _push_fold(ctx, c1, c2, pct, tag, subidas):
    """Con pila corta: all-in o retirarse."""
    bbs = ctx.techo / max(1, ctx.bb)
    vivos = sum(1 for j in ctx.jugadores if j.get("en_torneo", True))
    if subidas == 0:
        ancho = 0.55 if bbs <= 5 else 0.40 if bbs <= 8 else 0.28 if bbs <= 12 else 0.20
        if vivos == 2:
            ancho = min(0.9, ancho * 1.6)
        if pct <= ancho:
            return {"tipo": "allin"}, f"{tag}: push/fold con {bbs:.0f} ciegas -> ALL-IN"
        return _segura(ctx), f"{tag}: push/fold con {bbs:.0f} ciegas -> me retiro"
    rangos = [ctx.rango_de(j["id"]) for j in ctx.rivales]
    eq, _ = ctx.equidad(rangos, _tiempo(ctx, 0.08))
    pozo_total = ctx.pozo + ctx.por_pagar
    necesaria = ctx.por_pagar / pozo_total if pozo_total else 0
    if eq >= necesaria:
        return {"tipo": "allin"}, f"{tag}: push/fold, equidad {eq:.0%} >= {necesaria:.0%} -> ALL-IN"
    return _segura(ctx), f"{tag}: push/fold, equidad {eq:.0%} < {necesaria:.0%} -> me retiro"


def _preflop(ctx, c1, c2):
    pct = percentil(c1, c2)
    clase = clase_preflop(c1, c2)
    bb = ctx.bb
    subidas = ctx.subidas.get("preflop", 0)
    detras = ctx.detras()
    limpers = sum(1 for pid, acts in ctx.acciones.items()
                  if pid != ctx.mi_id and any(a["etapa"] == "preflop" and a["tipo"] == "call" for a in acts))
    tag = f"{clase} (top {pct:.0%})"

    if ctx.f("pushfold") and ctx.techo <= ctx.f("pushfold") * bb:
        return _push_fold(ctx, c1, c2, pct, tag, subidas)

    por_id = {j["id"]: j for j in ctx.rivales}
    if subidas == 0:
        if ctx.por_pagar == 0:  # ciega grande sin subidas
            if pct <= min(0.12 + (0.05 if limpers <= 1 else 0), ctx.f("ancho_max", 1.0)):
                return _apostar(ctx, (3 + limpers) * bb), f"{tag}: subo desde la ciega grande para aislar"
            return _segura(ctx), f"{tag}: paso gratis desde la ciega grande"
        ancho = APERTURA.get(len(detras), 0.15)
        en_mano = sum(1 for j in ctx.jugadores if j.get("en_mano", True) and j.get("en_torneo", True))
        if en_mano == 2:
            ancho = 0.75  # heads-up: desde el botón se juega casi todo
        # Si los que faltan hablar se retiran mucho, robamos más.
        if detras:
            fold_medio = sum(ctx.perfil(p).fold_preflop for p in detras) / len(detras)
            ancho *= min(1.45, max(0.8, 1 + (fold_medio - 0.55) * 1.5))
        if limpers:
            ancho *= 0.75
        if ctx.modo == "final":
            ancho *= 1.1
        notas = []
        if ctx.f("ladron") and len(detras) <= 2 and not limpers:
            ancho *= ctx.f("ladron")
            notas.append("robo desde atrás")
        if ctx.f("presion") and any(ctx.pila_de(por_id[p]) < 0.4 * ctx.techo for p in detras if p in por_id):
            ancho *= 1.25
            notas.append("presiono a una pila corta")
        if ctx.f("evita_lider") and any(ctx.pila_de(por_id[p]) > 1.3 * ctx.techo for p in detras if p in por_id):
            ancho *= 0.75
            notas.append("el líder habla detrás")
        if ctx.f("perfiles") and detras:
            rocas = sum(1 for p in detras if ctx.perfil(p).estilo() == "roca")
            ancho *= 1 + 0.15 * ctx.f("perfiles") * rocas / len(detras)
        ancho = min(0.95, ancho * ctx.e["apertura"], ctx.f("ancho_max", 1.0))
        extra = f"; {', '.join(notas)}" if notas else ""
        if pct <= ancho:
            tam = ((2.5 + limpers) * bb if len(detras) > 1 else 3 * bb) * ctx.e["tam_apuesta"]
            return (_apostar(ctx, _tam_aleatorio(ctx, tam)),
                    f"{tag}: abro subiendo (abro con el {ancho:.0%} mejor, faltan {len(detras)}{extra})")
        if limpers and pct <= ancho * 1.6 and ctx.por_pagar <= bb:
            return _pagar(ctx), f"{tag}: entro barato detrás de {limpers} limper(s)"
        if len(detras) == 1 and ctx.por_pagar <= bb / 2 and pct <= min(0.55, ctx.f("ancho_max", 1.0) * 3):
            return _pagar(ctx), f"{tag}: completo la ciega chica"
        return _segura(ctx), f"{tag}: mano débil para esta posición, me retiro"

    # --- Enfrentamos una o más subidas ---
    agresor = ctx.agresor.get("preflop")
    perfil = ctx.perfil(agresor) if agresor else None
    rangos = [ctx.rango_de(j["id"]) for j in ctx.rivales]
    eq, sims = ctx.equidad(rangos, _tiempo(ctx, 0.08))
    pozo_total = ctx.pozo + ctx.por_pagar
    necesaria = ctx.por_pagar / pozo_total if pozo_total else 0
    margen = (0.02 if ctx.en_posicion() or len(ctx.rivales) == 1 else 0.05) + _riesgo(ctx, ctx.por_pagar)
    piso = _piso_supervivencia(ctx, ctx.por_pagar)
    notas = []
    if ctx.f("ancho_max"):
        margen += 0.05
    if ctx.f("antimaniaco") and perfil is not None:
        if perfil.ancho_subida > 0.45 or perfil.estilo() == "maníaco":
            margen -= 0.04
            piso = max(0.0, piso - 0.05)
            notas.append("el agresor sube con cualquier cosa")
        else:
            margen += 0.02
    if ctx.f("evita_lider") and agresor in por_id and ctx.pila_de(por_id[agresor]) > 1.3 * ctx.techo:
        margen += 0.04
        piso += 0.05 if piso else 0.0
        notas.append("me sube el que me cubre")
    f_farol, d_margen, _, lectura = _lecturas(ctx, [agresor] if agresor and agresor in por_id else [])
    margen += d_margen
    if lectura:
        notas.append(lectura)
    ancho_r = rangos[0].ancho if len(rangos) == 1 else min(r.ancho for r in rangos)
    info = (f"{tag}, equidad {eq:.0%} vs {len(rangos)} rival(es) "
            f"(rango del agresor ~{ancho_r:.0%}), necesito {necesaria:.0%}+{margen:.0%}")
    if perfil is not None and not ctx.f("neutral"):
        info += f" | agresor: {perfil.resumen()}"
    if notas:
        info += " | " + "; ".join(notas)

    # Resubir por valor
    premium = 0.03 if ctx.f("ancho_max") else max(0.03, ancho_r * 0.25)
    if subidas == 1 and (pct <= premium or (eq >= 0.6 + ctx.e["valor"] and len(rangos) == 1)):
        tam = (ctx.apuesta_actual * (3 if ctx.en_posicion() else 3.6) + limpers * bb) * ctx.e["tam_apuesta"]
        return _apostar(ctx, _tam_aleatorio(ctx, tam)), f"{info} -> RESUBO por valor"
    if subidas >= 2 and (pct <= 0.02 or eq >= 0.62):
        return _apostar(ctx, ctx.apuesta_actual * 2.4), f"{info} -> RESUBO otra vez, mano premium"

    # Resubida de farol contra quien abre mucho y se retira mucho
    if (subidas == 1 and len(rangos) == 1 and perfil is not None and perfil.fold_preflop > 0.55
            and 0.08 < pct < 0.35 and (c1 & 3) == (c2 & 3)
            and random.random() < min(0.8, 0.3 * ctx.e["faroles"] * f_farol)
            and ctx.por_pagar < ctx.techo * 0.15):
        return _apostar(ctx, ctx.apuesta_actual * 3), f"{info} -> RESUBO de farol (se retira {perfil.fold_preflop:.0%})"

    paga, motivo = _pagar_o_no(ctx, eq, necesaria, margen, piso)
    if paga:
        return _pagar(ctx), f"{info} -> PAGO{' (' + motivo + ')' if motivo else ''}"
    # Parejas chicas: pagar barato buscando trío (cuotas implícitas)
    pila_efectiva = min(ctx.techo, max(ctx.pila_de(j) for j in ctx.rivales))
    if (c1 >> 2) == (c2 >> 2) and ctx.por_pagar * 15 <= pila_efectiva and ctx.por_pagar <= ctx.techo * 0.08:
        return _pagar(ctx), f"{info} -> PAGO buscando trío (cuotas implícitas)"
    return _segura(ctx), f"{info} -> ME RETIRO{' (' + motivo + ')' if motivo else ''}"


def _prob_fold(ctx, perfiles, frac):
    """Probabilidad estimada de que los rivales se retiren ante una apuesta de `frac` del bote."""
    if not perfiles:
        return 0.0
    base = sum(p.fold_postflop for p in perfiles) / len(perfiles)
    pf = min(0.85, base * (0.65 + 0.55 * frac))
    return pf ** len(perfiles)


def _ev_apuesta(ctx, eq, perfiles, frac):
    """Valor esperado (en fichas) de apostar `frac` del bote, contando retiradas y pagos."""
    pozo = ctx.pozo
    b = frac * pozo
    pf = _prob_fold(ctx, perfiles, frac)
    eq_pagado = max(0.0, eq - 0.12 * frac)  # quien paga una apuesta grande suele tener algo
    return pf * pozo + (1 - pf) * (eq_pagado * (pozo + 2 * b) - b)


def _postflop(ctx, c1, c2):
    n = len(ctx.rivales)
    rangos = [ctx.rango_de(j["id"]) for j in ctx.rivales]
    if ctx.f("gto"):
        for r in rangos:
            r.farol = 0.33
    eq, sims = ctx.equidad(rangos, _tiempo(ctx, 0.14))
    pozo = ctx.pozo
    rio = ctx.etapa == "river"
    pids = [j["id"] for j in ctx.rivales]
    perfiles = [ctx.perfil(pid) for pid in pids]
    fold_medio = sum(p.fold_postflop for p in perfiles) / max(1, n)
    soy_agresor_pre = ctx.agresor.get("preflop") == ctx.mi_id
    f_farol, d_margen, f_tam, lectura = _lecturas(ctx, pids)
    base = (f"{legibles(ctx.cartas)} | mesa {legibles(ctx.mesa)} | bote {pozo} | "
            f"equidad {eq:.0%} vs {n} rival(es) ({sims} simulaciones)")
    if lectura:
        base += f" | {lectura}"
    mis_acts = ctx.acciones.get(ctx.mi_id, [])
    pase_esta_calle = any(a["etapa"] == ctx.etapa and a["tipo"] == "check" for a in mis_acts)
    pagadores = all(p.fold_postflop < 0.4 or p.estilo() in ("pagador", "maníaco") for p in perfiles)
    cortos = [j for j in ctx.rivales if ctx.pila_de(j) < 0.4 * ctx.techo]

    if ctx.por_pagar == 0:
        umbral = (0.55 if rio else 0.52) + 0.08 * (n - 1) + ctx.e["valor"]
        cobrar = ctx.f("cobrador") and pagadores
        if cobrar:
            umbral -= 0.04
        if eq >= umbral:
            prob_trampa = 0.7 if ctx.f("trampero") else 0.25
            calle_trampa = (not rio) if ctx.f("trampero") else ctx.etapa == "flop"
            if eq > (0.85 if ctx.f("trampero") else 0.92) and calle_trampa and n == 1 and random.random() < prob_trampa:
                return _segura(ctx), f"{base} -> PASO como trampa (mano enorme)"
            frac = 0.5 if eq < 0.7 else 0.7
            if rio and eq > 0.85:
                frac = 0.9
            if ctx.f("gto"):
                frac = 0.66
            if ctx.f("tamano") or ctx.f("simulador"):
                frac = max((0.33, 0.5, 0.75, 1.0, 1.5), key=lambda x: _ev_apuesta(ctx, eq, perfiles, x))
            frac *= ctx.e["tam_apuesta"] * f_tam * (1.3 if cobrar else 1.0)
            motivo = "cobrando a pagadores" if cobrar else "por valor"
            return _apostar(ctx, _tam_aleatorio(ctx, pozo * frac)), f"{base} -> APUESTO {frac:.0%} del bote {motivo}"

        # Sin mano para valor: ¿farol?
        if ctx.f("simulador") and n <= 2:
            mejor = max((0.33, 0.5, 0.75, 1.0), key=lambda x: _ev_apuesta(ctx, eq, perfiles, x))
            ev_b = _ev_apuesta(ctx, eq, perfiles, mejor)
            ev_c = eq * pozo * 0.85
            if ev_b > ev_c:
                return (_apostar(ctx, pozo * mejor),
                        f"{base} -> APUESTO {mejor:.0%} (simulé: apostar vale {ev_b:.0f}, pasar {ev_c:.0f})")
            return _segura(ctx), f"{base} -> PASO (simulé: pasar vale {ev_c:.0f}, apostar {ev_b:.0f})"
        if (ctx.f("flotador") and ctx.etapa == "turn" and n == 1 and ctx.en_posicion()
                and any(a["etapa"] == "flop" and a["tipo"] == "call" for a in mis_acts)
                and random.random() < 0.65):
            return _apostar(ctx, pozo * 0.6), f"{base} -> APUESTO: el agresor se rindió en el turn (flotada)"
        if ctx.f("gto"):
            if n == 1 and eq < 0.35 and random.random() < (0.30 if rio else 0.35):
                return _apostar(ctx, pozo * 0.66), f"{base} -> APUESTO de farol en proporción GTO"
            return _segura(ctx), f"{base} -> PASO"
        if n <= 2 and not (ctx.f("cobrador") and pagadores):
            prob = (fold_medio - 0.35) * 1.5
            if soy_agresor_pre and ctx.etapa == "flop":
                prob += 0.25
            if not rio and eq > 0.3:
                prob += 0.1  # semi-farol con proyecto
            if ctx.f("presion") and cortos:
                prob += 0.25
            prob = max(0.0, min(0.7, prob * ctx.e["faroles"] * f_farol)) / n
            if random.random() < prob:
                tipo = "semi-farol" if (not rio and eq > 0.3) else "farol"
                if ctx.f("presion") and cortos:
                    tipo += " contra pila corta"
                return (_apostar(ctx, _tam_aleatorio(ctx, pozo * 0.5)),
                        f"{base} -> APUESTO de {tipo} (rivales se retiran {fold_medio:.0%})")
        return _segura(ctx), f"{base} -> PASO"

    # Nos apostaron
    pozo_total = pozo + ctx.por_pagar
    necesaria = ctx.por_pagar / pozo_total if pozo_total else 0
    margen = 0.02 + _riesgo(ctx, ctx.por_pagar) + d_margen
    piso = _piso_supervivencia(ctx, ctx.por_pagar)
    agresor = ctx.agresor.get(ctx.etapa)
    texto_agr = ""
    perfil_agr = None
    j_agr = next((j for j in ctx.rivales if j["id"] == agresor), None)
    if agresor and agresor != ctx.mi_id:
        perfil_agr = ctx.perfil(agresor)
        if not ctx.f("neutral"):
            texto_agr = f" | apostó {perfil_agr.resumen()}"
    notas = []
    if ctx.f("gto"):
        margen = 0.0 + _riesgo(ctx, ctx.por_pagar)
    if ctx.f("antimaniaco") and perfil_agr is not None and (
            perfil_agr.agresion > 0.45 or perfil_agr.estilo() == "maníaco"):
        margen -= 0.04
        piso = max(0.0, piso - 0.05)
        notas.append("apuesta con cualquier cosa")
    if ctx.f("evita_lider") and j_agr is not None and ctx.pila_de(j_agr) > 1.3 * ctx.techo:
        margen += 0.05
        piso += 0.05 if piso else 0.0
        notas.append("me apuesta el que me cubre")
    if (ctx.f("flotador") and ctx.etapa == "flop" and n == 1 and ctx.en_posicion()
            and agresor == ctx.agresor.get("preflop") and ctx.por_pagar <= pozo * 0.8):
        margen -= 0.08
        notas.append("floto en posición")
    info = f"{base} | pagar {ctx.por_pagar} (necesito {necesaria:.0%}+{margen:.0%}){texto_agr}"
    if notas:
        info += " | " + "; ".join(notas)

    umbral_subida = (0.85 if rio else 0.80) + (0.06 if n > 1 else 0) + ctx.e["valor"]
    if ctx.f("trampero") and pase_esta_calle:
        umbral_subida -= 0.04
    if eq >= umbral_subida and ("raise" in ctx.validas or "allin" in ctx.validas):
        tam = ctx.apuesta_actual + max(ctx.min_subida - ctx.apuesta_actual, int(pozo_total * 0.8))
        motivo = "cierro la trampa" if ctx.f("trampero") and pase_esta_calle else "por valor"
        return _apostar(ctx, _tam_aleatorio(ctx, tam)), f"{info} -> SUBO {motivo}"
    if (ctx.etapa == "flop" and n == 1 and 0.3 < eq < 0.5 and perfil_agr is not None
            and perfil_agr.fold_postflop > 0.5
            and random.random() < min(0.6, 0.15 * ctx.e["faroles"] * f_farol)
            and ctx.por_pagar < ctx.techo * 0.2):
        tam = ctx.apuesta_actual * 3
        return _apostar(ctx, tam), f"{info} -> SUBO de semi-farol"
    paga, motivo = _pagar_o_no(ctx, eq, necesaria, max(-0.05, margen), piso)
    if paga:
        return _pagar(ctx), f"{info} -> PAGO{' (' + motivo + ')' if motivo else ''}"
    if piso and eq >= necesaria + margen and not motivo:
        return _segura(ctx), f"{info} -> ME RETIRO: pagar me jugaría el torneo con solo {eq:.0%}"
    return _segura(ctx), f"{info} -> ME RETIRO{' (' + motivo + ')' if motivo else ''}"
