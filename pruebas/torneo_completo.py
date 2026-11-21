#!/usr/bin/env python3
"""Torneo completo en tu laptop, con el formato oficial de PokerFight.

Clasificatoria
  - 36 bots, cada uno con 10 000 fichas. Ciegas fijas 50/100. 5 s por jugada.
  - 10 rondas. En cada ronda se sortean mesas de 5 (algunas de 6 si no cuadra).
  - Cada mesa se cierra con lo primero que pase: 50 manos, 6 minutos o que quede
    un solo bot con fichas.
  - Cada bot conserva sus fichas de una ronda a la siguiente.
  - El que se queda sin fichas queda eliminado y no juega más rondas.
  - Pasan a la final los 6 con más fichas; si quedan menos de 6 con fichas,
    completan los últimos en ser eliminados.

Final
  - Los 6 finalistas vuelven a 10 000 fichas. Gana el último en pie o el que
    tenga más fichas tras 1 hora (cámbialo con --minutos-final).

Participantes: los que figuran en pruebas/participantes.txt (edítalo para
sacar o meter bots).

Uso (desde la carpeta pokerfight-bot):
    python pruebas\\torneo_completo.py
    python pruebas\\torneo_completo.py --minutos-final 15     # final más corta
    python pruebas\\torneo_completo.py --sin-final            # solo las 10 rondas
    python pruebas\\torneo_completo.py --torneos 3            # varios torneos y tabla de títulos
    python pruebas\\torneo_completo.py --paralelo 6           # más mesas a la vez (más CPU)
"""

import argparse
import json
import math
import os
import random
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, RAIZ)
from pfbot.estilos import ESTILOS  # noqa: E402

EJEMPLO = "ejemplo_oficial"
FICHAS = 10000


# ---------------------------------------------------------------------------
# Participantes
# ---------------------------------------------------------------------------

ARCHIVO_PARTICIPANTES = os.path.join(AQUI, "participantes.txt")


def todos_los_bots():
    return [k for k in ESTILOS if k != "precavido"] + [EJEMPLO]


def participantes():
    """Lee pruebas/participantes.txt; si no existe, juegan todos los estilos."""
    if not os.path.exists(ARCHIVO_PARTICIPANTES):
        return sorted(todos_los_bots(), key=numero)
    validos = set(todos_los_bots())
    lista = []
    with open(ARCHIVO_PARTICIPANTES, encoding="utf-8") as f:
        for linea in f:
            nombre = linea.split("#", 1)[0].strip()
            if not nombre:
                continue
            if nombre not in validos:
                sys.exit(f"participantes.txt: '{nombre}' no es un estilo. Usa python mi_bot.py -estilos")
            if nombre not in lista:
                lista.append(nombre)
    if len(lista) < 2:
        sys.exit("participantes.txt: hacen falta al menos 2 bots")
    return lista


def numero(nombre):
    return 35 if nombre == EJEMPLO else ESTILOS[nombre]["numero"]


def etiqueta(nombre):
    return f"#{numero(nombre):02d} {nombre}"


def comando_bot(nombre, direccion, carpeta, modo, ronda=0):
    if nombre == EJEMPLO:
        return [sys.executable, os.path.join(AQUI, "bots", "ejemplo_oficial.py"),
                "-addr", direccion, "-token", nombre]
    return [sys.executable, os.path.join(RAIZ, "mi_bot.py"), "-addr", direccion, "-token", nombre,
            "-una-vez", "-silencioso", "-estilo", nombre, "-modo", modo, "-ronda", str(ronda),
            "-datos", os.path.join(carpeta, "datos", nombre),
            "-logs", os.path.join(carpeta, "logs", nombre)]


# ---------------------------------------------------------------------------
# Una mesa
# ---------------------------------------------------------------------------

def puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def mesa_exe(carpeta_bin):
    ruta = os.path.join(carpeta_bin, "mesa-fichas" + (".exe" if os.name == "nt" else ""))
    if not os.path.exists(ruta):
        sys.exit(f"No encuentro {ruta}. ¿Está la carpeta pruebas/bin completa?")
    return ruta


def jugar_mesa(nombre, jugadores, fichas, manos, limite_seg, modo, carpeta, args, ronda=0):
    """Juega una mesa y devuelve {bot: (fichas_finales, timeouts)}."""
    puerto = puerto_libre()
    direccion = f"127.0.0.1:{puerto}"
    # Los archivos de la mesa van a una carpeta temporal: Windows suele
    # proteger Documentos de programas nuevos como mesa-fichas.exe.
    temporal = tempfile.mkdtemp(prefix="pokerfight-mesa-")
    ruta_res = os.path.join(temporal, "resultado.json")
    stacks = ",".join(f"{j}={fichas[j]}" for j in jugadores)
    cmd_mesa = [mesa_exe(args.bin), "-addr", direccion, "-id", nombre,
                "-jugadores", str(len(jugadores)), "-min-jugadores", str(len(jugadores)),
                "-ciega-chica", "50", "-ciega-grande", "100", "-timeout-ms", "5000",
                "-stack", str(FICHAS), "-stacks", stacks, "-rondas", str(manos),
                "-limite-seg", str(limite_seg), "-resultado", ruta_res]
    log_mesa = open(os.path.join(temporal, "mesa.log"), "wb")
    mesa = subprocess.Popen(cmd_mesa, stdout=log_mesa, stderr=subprocess.STDOUT, cwd=temporal)
    time.sleep(0.8)
    orden = list(jugadores)
    random.shuffle(orden)  # el orden de llegada decide las sillas
    bots = [subprocess.Popen(comando_bot(j, direccion, carpeta, modo, ronda), stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, cwd=temporal) for j in orden]
    try:
        mesa.wait(timeout=limite_seg + 600 if limite_seg else 6 * 3600)
    except subprocess.TimeoutExpired:
        mesa.kill()
    for b in bots:
        try:
            b.wait(timeout=15)
        except subprocess.TimeoutExpired:
            b.kill()
    log_mesa.close()
    carpeta_mesa = os.path.join(carpeta, "mesas", nombre)
    os.makedirs(carpeta_mesa, exist_ok=True)
    for archivo in ("mesa.log", "resultado.json"):
        if os.path.exists(os.path.join(temporal, archivo)):
            shutil.copy(os.path.join(temporal, archivo), carpeta_mesa)
    if not os.path.exists(ruta_res):
        with open(os.path.join(temporal, "mesa.log"), encoding="utf-8", errors="replace") as f:
            cola = f.read().strip().splitlines()[-5:]
        shutil.rmtree(temporal, ignore_errors=True)
        raise RuntimeError(f"la mesa {nombre} falló:\n    " + "\n    ".join(cola))
    with open(ruta_res, encoding="utf-8") as f:
        res = json.load(f)
    shutil.rmtree(temporal, ignore_errors=True)
    salida = {j["id"]: (j["saldo_final"], j["timeouts"]) for j in res["jugadores"]}
    return salida, res


def repartir(vivos):
    """Mesas de 5; si no cuadra, algunas de 6 (y nunca más de 6)."""
    n = len(vivos)
    k = max(1, n // 5)
    while math.ceil(n / k) > 6:
        k += 1
    random.shuffle(vivos)
    mesas, i = [], 0
    for m in range(k):
        tam = n // k + (1 if m < n % k else 0)
        mesas.append(vivos[i:i + tam])
        i += tam
    return [m for m in mesas if len(m) >= 2]


# ---------------------------------------------------------------------------
# Un torneo
# ---------------------------------------------------------------------------

def un_torneo(t, args, carpeta_base):
    carpeta = os.path.join(carpeta_base, f"torneo-{t:02d}")
    os.makedirs(carpeta, exist_ok=True)
    bots = participantes()
    fichas = {b: FICHAS for b in bots}
    eliminado_en = {}   # bot -> (ronda, fichas al empezar esa ronda): para desempatar
    timeouts = {b: 0 for b in bots}
    inicio = time.time()
    print(f"\n==================== TORNEO {t} ====================")

    for ronda in range(1, args.rondas + 1):
        vivos = [b for b in bots if fichas[b] > 0]
        if len(vivos) <= 1:
            break
        mesas = repartir(list(vivos))
        antes = dict(fichas)
        print(f"\nRonda {ronda}/{args.rondas}: {len(vivos)} bots en {len(mesas)} mesas "
              f"({', '.join(str(len(m)) for m in mesas)} jugadores)", flush=True)

        def jugar(i):
            return i, jugar_mesa(f"r{ronda:02d}-mesa{i + 1}", mesas[i], fichas, args.manos,
                                 args.limite_mesa, "clasificatoria", carpeta, args, ronda)

        with ThreadPoolExecutor(max_workers=args.paralelo) as ex:
            for i, (res, info) in ex.map(jugar, range(len(mesas))):
                for b, (f, to) in res.items():
                    fichas[b] = f
                    timeouts[b] += to
                cierre = " (cerrada a los 6 min)" if info.get("cerrada_por_tiempo") else ""
                linea = "  ".join(f"{b} {fichas[b] - antes[b]:+d}" for b in sorted(res, key=lambda x: -fichas[x]))
                print(f"  Mesa {i + 1} ({info['manos']} manos{cierre}): {linea}", flush=True)

        caidos = [b for b in vivos if fichas[b] == 0]
        for b in caidos:
            eliminado_en[b] = (ronda, antes[b])
        if caidos:
            print(f"  Eliminados: {', '.join(etiqueta(b) for b in caidos)}")
        vivos = sorted((b for b in bots if fichas[b] > 0), key=lambda b: -fichas[b])
        top = ", ".join(f"{b} {fichas[b]}" for b in vivos[:6])
        print(f"  Top 6 tras la ronda {ronda}: {top}   ({time.time() - inicio:.0f} s)", flush=True)

    # Clasificación a la final
    vivos = sorted((b for b in bots if fichas[b] > 0), key=lambda b: -fichas[b])
    finalistas = vivos[:6]
    if len(finalistas) < 6:
        ultimos = sorted(eliminado_en, key=lambda b: (eliminado_en[b][0], eliminado_en[b][1]), reverse=True)
        finalistas += ultimos[:6 - len(finalistas)]

    print("\nClasificación final de la fase (fichas):")
    tabla = sorted(bots, key=lambda b: (-fichas[b], -eliminado_en.get(b, (99, 0))[0]))
    for pos, b in enumerate(tabla, 1):
        estado = "FINALISTA" if b in finalistas else (
            f"eliminado en ronda {eliminado_en[b][0]}" if b in eliminado_en else "")
        to = f"  [{timeouts[b]} timeouts]" if timeouts[b] else ""
        print(f"  {pos:2d}. {etiqueta(b):<20} {fichas[b]:7d}  {estado}{to}")

    if args.sin_final:
        print(f"\nClasificados a la final: {', '.join(etiqueta(b) for b in finalistas)}"
              f"   ({(time.time() - inicio) / 60:.0f} min en total; final omitida con --sin-final)")
        resumen = {"fichas_clasificatoria": fichas, "eliminados": eliminado_en, "finalistas": finalistas,
                   "final": {}, "posiciones_final": [], "campeon": None, "timeouts": timeouts}
        with open(os.path.join(carpeta, "resumen.json"), "w", encoding="utf-8") as f:
            json.dump(resumen, f, indent=1, ensure_ascii=False)
        return resumen

    print(f"\nFINAL: {', '.join(etiqueta(b) for b in finalistas)}")
    print(f"  (todos con 10 000 fichas; gana el último en pie o el que tenga más fichas "
          f"tras {args.minutos_final} min)", flush=True)
    res_final, info = jugar_mesa("final", finalistas, {b: FICHAS for b in finalistas}, -1,
                                 args.minutos_final * 60, "final", carpeta, args)
    orden = sorted(res_final, key=lambda b: -res_final[b][0])
    campeon = orden[0]
    cierre = "se acabó el tiempo" if info.get("cerrada_por_tiempo") else "quedó uno en pie"
    print(f"  Mesa final ({info['manos']} manos, {cierre}):")
    for pos, b in enumerate(orden, 1):
        print(f"    {pos}. {etiqueta(b):<20} {res_final[b][0]:6d} fichas")
    print(f"\n  CAMPEÓN DEL TORNEO {t}: {etiqueta(campeon)}   ({(time.time() - inicio) / 60:.0f} min en total)")

    resumen = {"fichas_clasificatoria": fichas, "eliminados": eliminado_en, "finalistas": finalistas,
               "final": {b: v[0] for b, v in res_final.items()}, "posiciones_final": orden,
               "campeon": campeon, "timeouts": timeouts}
    with open(os.path.join(carpeta, "resumen.json"), "w", encoding="utf-8") as f:
        json.dump(resumen, f, indent=1, ensure_ascii=False)
    return resumen


def main():
    p = argparse.ArgumentParser(description="Torneo completo con el formato oficial")
    p.add_argument("--torneos", type=int, default=1, help="cuántos torneos jugar (por defecto 1)")
    p.add_argument("--rondas", type=int, default=10, help="rondas de la clasificatoria (por defecto 10)")
    p.add_argument("--manos", type=int, default=50, help="manos máximas por mesa (por defecto 50)")
    p.add_argument("--limite-mesa", type=int, default=360, help="segundos máximos por mesa (por defecto 360 = 6 min)")
    p.add_argument("--minutos-final", type=int, default=60, help="duración máxima de la final (por defecto 60)")
    p.add_argument("--sin-final", action="store_true",
                   help="juega solo las rondas de clasificación, sin la mesa final")
    p.add_argument("--paralelo", type=int, default=4, help="mesas que se juegan a la vez (por defecto 4)")
    p.add_argument("--bin", default=os.path.join(AQUI, "bin"), help="carpeta con mesa-fichas")
    args = p.parse_args()

    carpeta = os.path.join(AQUI, "resultados", "torneo-" + time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(carpeta, exist_ok=True)
    print(f"{len(participantes())} bots (de pruebas/participantes.txt). Formato oficial: "
          f"{args.rondas} rondas, mesas de 5-6, fichas acumuladas, top 6 a la final.")
    print(f"Resultados y bitácoras en {carpeta}")

    titulos, finales, posiciones = {}, {}, {}
    for t in range(1, args.torneos + 1):
        try:
            r = un_torneo(t, args, carpeta)
        except RuntimeError as e:
            print(f"\nEl torneo {t} se detuvo: {e}")
            continue
        if r["campeon"]:
            titulos[r["campeon"]] = titulos.get(r["campeon"], 0) + 1
        for b in r["finalistas"]:
            finales[b] = finales.get(b, 0) + 1
        for pos, b in enumerate(sorted(r["fichas_clasificatoria"], key=lambda x: -r["fichas_clasificatoria"][x]), 1):
            posiciones.setdefault(b, []).append(pos)

    if args.torneos > 1 and posiciones:
        print(f"\n==================== RESUMEN DE {args.torneos} TORNEOS ====================")
        print(f"  {'Bot':<20}{'Títulos':>8}{'Finales':>9}{'Puesto medio clasif.':>22}")
        for b in sorted(posiciones, key=lambda b: (-titulos.get(b, 0), -finales.get(b, 0),
                                                    sum(posiciones[b]) / len(posiciones[b]))):
            print(f"  {etiqueta(b):<20}{titulos.get(b, 0):>8}{finales.get(b, 0):>9}"
                  f"{sum(posiciones[b]) / len(posiciones[b]):>22.1f}")


if __name__ == "__main__":
    main()
