#!/usr/bin/env python3
"""Pone a jugar los estilos del bot entre ellos en tu laptop y muestra quién gana.

Cada mesa es como una de la clasificatoria: 10 000 fichas, ciegas 50/100,
50 manos, 5 segundos por jugada. En cada mesa se sientan los estilos elegidos
y, por defecto, un bot del kit distinto cada vez (para que no sea solo un
espejo). Cada estilo guarda su propia memoria de rivales, así que aprende de
mesa en mesa como en el torneo.

Uso (desde la carpeta pokerfight-bot):
    python pruebas\\torneo_estilos.py
    python pruebas\\torneo_estilos.py --mesas 20
    python pruebas\\torneo_estilos.py --estilos prudente agresivo --rival ninguno

Una sola mesa depende mucho de la suerte: para comparar en serio usa 20 o más.
"""

import argparse
import json
import os
import random
import shutil
import subprocess
import tempfile
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, RAIZ)
from pfbot.estilos import ESTILOS  # noqa: E402

BOTS_KIT = ["darwin", "espia", "estadistico", "bandido", "base", "conservador", "aleatorio"]


def exe(carpeta_bin, nombre):
    ruta = os.path.join(carpeta_bin, nombre + (".exe" if os.name == "nt" else ""))
    if not os.path.exists(ruta):
        sys.exit(f"No encuentro {ruta}. ¿Está la carpeta pruebas/bin completa?")
    return ruta


def comando_kit(carpeta_bin, nombre):
    cmd = [exe(carpeta_bin, nombre)]
    if nombre in ("bandido", "espia", "darwin"):
        cmd.append("-silencioso")
    if nombre == "estadistico":
        cmd += ["-simulaciones", "2000"]
    return cmd


def jugar_mesa(i, estilos, rival, args, salida):
    carpeta = os.path.join(salida, f"mesa-{i:03d}")
    os.makedirs(carpeta, exist_ok=True)
    participantes = []
    for e in estilos:
        participantes.append({
            "id": e, "nombre": e,
            "comando": [sys.executable, os.path.join(RAIZ, "mi_bot.py"), "-una-vez", "-silencioso",
                        "-estilo", e,
                        "-datos", os.path.join(salida, "datos-" + e),
                        "-logs", os.path.join(salida, "logs-" + e)],
        })
    if rival:
        participantes.append({"id": "kit-" + rival, "nombre": rival,
                              "comando": comando_kit(args.bin, rival)})
    config = {
        "nombre": f"estilos-{i}", "formato": "mesa-unica", "puntuacion": "neto",
        "manos_por_enfrentamiento": args.manos, "reponer_stack": False,
        "semilla": random.randint(1, 10 ** 9), "paralelismo": 1,
        "guardar_historial": False, "salida": "resultado",
        "mesa": {"ciega_chica": 50, "ciega_grande": 100, "stack": 10000,
                 "timeout_ms": 5000, "espera_jugadores_ms": 30000},
        "participantes": participantes,
    }
    # La arena escribe en una carpeta temporal: Windows suele proteger Documentos
    # ("acceso controlado a carpetas") y no deja escribir ahí a programas nuevos.
    temporal = tempfile.mkdtemp(prefix="pokerfight-arena-")
    os.makedirs(os.path.join(temporal, "resultado"), exist_ok=True)
    ruta_cfg = os.path.join(temporal, "config.json")
    with open(ruta_cfg, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=1)
    shutil.copy(ruta_cfg, os.path.join(carpeta, "config.json"))
    proceso = subprocess.run([exe(args.bin, "arena"), "correr", "-config", ruta_cfg],
                             cwd=temporal, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             timeout=1800)
    with open(os.path.join(carpeta, "arena.log"), "wb") as log:
        log.write(proceso.stdout or b"")
    netos = {}
    archivo = os.path.join(temporal, "resultado", "enfrentamientos.jsonl")
    if not os.path.exists(archivo):
        return None
    shutil.copy(archivo, os.path.join(carpeta, "enfrentamientos.jsonl"))
    with open(archivo, encoding="utf-8") as f:
        for linea in f:
            for p in json.loads(linea).get("puestos", []):
                netos[p["id_participante"]] = (p.get("neto", 0), p.get("timeouts", 0))
    shutil.rmtree(temporal, ignore_errors=True)
    return netos


def main():
    p = argparse.ArgumentParser(description="Torneo local entre estilos del bot")
    p.add_argument("--mesas", type=int, default=10, help="cuántas mesas jugar (por defecto 10)")
    p.add_argument("--estilos", nargs="+", default=["equilibrado", "agresivo", "prudente", "farolero"],
                   choices=sorted(ESTILOS), help="estilos a enfrentar")
    p.add_argument("--rival", default="rotar", choices=["rotar", "ninguno"] + BOTS_KIT,
                   help="bot del kit que se sienta en cada mesa (rotar = uno distinto cada vez)")
    p.add_argument("--manos", type=int, default=50, help="manos por mesa (por defecto 50)")
    p.add_argument("--bin", default=os.path.join(AQUI, "bin"), help="carpeta con arena y bots del kit")
    args = p.parse_args()

    if len(args.estilos) != len(set(args.estilos)):
        sys.exit("Cada estilo debe aparecer una sola vez.")
    salida = os.path.join(AQUI, "resultados", time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(salida, exist_ok=True)
    print(f"Jugando {args.mesas} mesas: {', '.join(args.estilos)}"
          f"{'' if args.rival == 'ninguno' else ' + un bot del kit'}. Resultados en {salida}\n")

    total = {e: [] for e in args.estilos}
    ganadas = {e: 0 for e in args.estilos}
    timeouts = {e: 0 for e in args.estilos}
    inicio = time.time()
    for i in range(1, args.mesas + 1):
        if args.rival == "rotar":
            rival = BOTS_KIT[(i - 1) % len(BOTS_KIT)]
        elif args.rival == "ninguno":
            rival = None
        else:
            rival = args.rival
        netos = jugar_mesa(i, args.estilos, rival, args, salida)
        if not netos:
            ruta_log = os.path.join(salida, f"mesa-{i:03d}", "arena.log")
            print(f"Mesa {i}: falló. Esto dice la arena ({ruta_log}):")
            with open(ruta_log, encoding="utf-8", errors="replace") as f:
                print("    " + "    ".join(f.readlines()[-5:]))
            continue
        mejor = max(args.estilos, key=lambda e: netos.get(e, (-10 ** 9, 0))[0])
        ganadas[mejor] += 1
        for e in args.estilos:
            neto, to = netos.get(e, (0, 0))
            total[e].append(neto)
            timeouts[e] += to
        resumen = "  ".join(f"{e} {netos.get(e, (0, 0))[0]:+6d}" for e in args.estilos)
        extra = f"  | {rival} {netos.get('kit-' + rival, (0, 0))[0]:+6d}" if rival else ""
        print(f"Mesa {i:3d}/{args.mesas}: {resumen}{extra}   ({time.time() - inicio:.0f} s)", flush=True)

    print("\nResultado final (fichas ganadas o perdidas por mesa):\n")
    print(f"{'Estilo':<13}{'Promedio':>10}{'Total':>10}{'Mejor estilo':>14}{'Eliminado':>11}{'Timeouts':>10}")
    orden = sorted(args.estilos, key=lambda e: -(sum(total[e]) / max(1, len(total[e]))))
    for e in orden:
        n = max(1, len(total[e]))
        elim = sum(1 for x in total[e] if x <= -10000)
        print(f"{e:<13}{sum(total[e]) / n:>+10.0f}{sum(total[e]):>+10d}{ganadas[e]:>14d}"
              f"{elim:>11d}{timeouts[e]:>10d}")
    print("\n'Mejor estilo' = en cuántas mesas fue el estilo con más fichas. "
          "'Eliminado' = mesas en que se quedó sin fichas.")
    if args.mesas < 20:
        print("Ojo: con menos de 20 mesas la suerte pesa mucho; no saques conclusiones fuertes.")


if __name__ == "__main__":
    main()
