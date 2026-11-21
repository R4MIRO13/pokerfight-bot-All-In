#!/usr/bin/env python3
"""Solo finales: mide qué bots son mejores en la mesa final.

Cada final es como la oficial: 6 bots, todos con 10 000 fichas, ciegas 50/100,
5 s por jugada; gana el último en pie (o el que tenga más fichas al llegar al
tope de tiempo o de manos).

En cada ciclo se sortean los bots en grupos de 6 y se juega una final por
grupo. Con varios ciclos, cada bot juega varias finales contra rivales
distintos y se ve quién gana más y quién sobrevive más.

Uso (desde la carpeta pokerfight-bot):
    python pruebas\\torneo_finales.py                       # los de participantes.txt, 3 ciclos
    python pruebas\\torneo_finales.py --ciclos 5
    python pruebas\\torneo_finales.py --bots equilibrado entrenador icm simulador prudente tamano --ciclos 10
"""

import argparse
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
from torneo_completo import FICHAS, etiqueta, jugar_mesa, participantes, todos_los_bots  # noqa: E402


def main():
    p = argparse.ArgumentParser(description="Simulador de mesas finales")
    p.add_argument("--bots", nargs="+", default=None, choices=todos_los_bots(), metavar="BOT",
                   help="bots que participan (por defecto los de pruebas/participantes.txt)")
    p.add_argument("--ciclos", type=int, default=3, help="cuántas veces se sortean los grupos (por defecto 3)")
    p.add_argument("--minutos", type=int, default=60, help="tope de tiempo de cada final (por defecto 60)")
    p.add_argument("--manos-max", type=int, default=400,
                   help="tope de manos de cada final; si se alcanza, gana quien tenga más fichas (por defecto 400)")
    p.add_argument("--paralelo", type=int, default=4, help="finales que se juegan a la vez (por defecto 4)")
    p.add_argument("--bin", default=os.path.join(AQUI, "bin"), help="carpeta con mesa-fichas")
    args = p.parse_args()

    bots = list(dict.fromkeys(args.bots or participantes()))
    if len(bots) < 2:
        sys.exit("Hacen falta al menos 2 bots.")
    carpeta = os.path.join(AQUI, "resultados", "finales-" + time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(carpeta, exist_ok=True)
    print(f"{len(bots)} bots, {args.ciclos} ciclos de finales de 6. Resultados en {carpeta}")

    stats = {b: {"finales": 0, "ganadas": 0, "puestos": [], "fichas": []} for b in bots}
    inicio = time.time()
    for ciclo in range(1, args.ciclos + 1):
        orden = list(bots)
        random.shuffle(orden)
        # Grupos de 6; si sobran, se completan con bots ya sorteados en este ciclo.
        grupos = [orden[i:i + 6] for i in range(0, len(orden), 6)]
        if len(grupos[-1]) < 6 and len(orden) >= 6:
            faltan = [b for b in orden if b not in grupos[-1]]
            grupos[-1] += random.sample(faltan, 6 - len(grupos[-1]))
        print(f"\nCiclo {ciclo}/{args.ciclos}: {len(grupos)} finales", flush=True)

        def jugar(i):
            g = grupos[i]
            res, info = jugar_mesa(f"c{ciclo:02d}-final{i + 1}", g, {b: FICHAS for b in g},
                                   args.manos_max, args.minutos * 60, "final", carpeta, args)
            return i, res, info

        with ThreadPoolExecutor(max_workers=args.paralelo) as ex:
            for i, res, info in ex.map(jugar, range(len(grupos))):
                # Puesto según el motor de la mesa: más fichas primero y, entre
                # eliminados, el que cayó más tarde queda mejor.
                orden_final = [j["id"] for j in sorted(info["jugadores"], key=lambda j: j["posicion"])]
                for puesto, b in enumerate(orden_final, 1):
                    s = stats[b]
                    s["finales"] += 1
                    s["puestos"].append(puesto)
                    s["fichas"].append(res[b][0])
                    if puesto == 1:
                        s["ganadas"] += 1
                motivo = "quedó uno" if res[orden_final[0]][0] >= FICHAS * len(res) else (
                    "tope de tiempo" if info.get("cerrada_por_tiempo") else "tope de manos")
                print(f"  Final {i + 1} ({info['manos']} manos, {motivo}): "
                      + "  ".join(f"{p}. {b}" for p, b in enumerate(orden_final, 1)), flush=True)
        print(f"  ({(time.time() - inicio) / 60:.0f} min)")

    print("\n==================== RESULTADO ====================")
    print(f"  {'Bot':<20}{'Finales':>8}{'Ganadas':>9}{'% gana':>8}{'Puesto medio':>14}{'Fichas medias':>15}")
    filas = sorted(bots, key=lambda b: (-stats[b]["ganadas"] / max(1, stats[b]["finales"]),
                                        sum(stats[b]["puestos"]) / max(1, len(stats[b]["puestos"]))))
    for b in filas:
        s = stats[b]
        n = max(1, s["finales"])
        print(f"  {etiqueta(b):<20}{s['finales']:>8}{s['ganadas']:>9}{100 * s['ganadas'] / n:>7.0f}%"
              f"{sum(s['puestos']) / n:>14.1f}{sum(s['fichas']) / n:>15.0f}")
    print("\n'Puesto medio': 1 = gana siempre, 6 = siempre el primero en caer. "
          "Con pocas finales por bot la suerte pesa mucho: usa varios ciclos.")


if __name__ == "__main__":
    main()
