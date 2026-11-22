#!/usr/bin/env python3
"""Bot de PokerFight. Solo usa la biblioteca estándar de Python (3.8+).

Uso:
    python mi_bot.py -addr HOST:PUERTO -token TU_TOKEN

El token también puede ir en la variable de entorno POKERFIGHT_TOKEN o en un
archivo token.txt junto a este script (está en .gitignore), para no tener que
escribirlo en la terminal.
"""

import argparse
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

from pfbot.bot import correr  # noqa: E402
from pfbot.estilos import ESTILOS, POR_DEFECTO  # noqa: E402


def leer_token(argumento):
    if argumento:
        return argumento.strip()
    if os.environ.get("POKERFIGHT_TOKEN"):
        return os.environ["POKERFIGHT_TOKEN"].strip()
    ruta = os.path.join(AQUI, "token.txt")
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            return f.read().strip()
    return None


def main():
    p = argparse.ArgumentParser(description="Bot de PokerFight")
    p.add_argument("-addr", default="localhost:9000", help="HOST:PUERTO de la mesa")
    p.add_argument("-token", default=None, help="token del equipo (o POKERFIGHT_TOKEN, o token.txt)")
    p.add_argument("-modo", default="auto", choices=["auto", "clasificatoria", "final"],
                   help="auto detecta la final; úsalo para forzar un modo")
    p.add_argument("-estilo", default=POR_DEFECTO, choices=sorted(ESTILOS), metavar="ESTILO",
                   help=f"personalidad del bot (por defecto {POR_DEFECTO}). Usa -estilos para ver la lista")
    p.add_argument("-estilos", action="store_true", help="muestra las personalidades disponibles y sale")
    p.add_argument("-ronda", type=int, default=0,
                   help="ronda de la clasificatoria en la que entra el bot (solo si lo reinicias "
                        "a mitad del torneo; por defecto las cuenta solo)")
    p.add_argument("-escala", type=float, default=1.0,
                   help="multiplica los umbrales de fichas del hibrido5 (1.0 = calibrado con 30 "
                        "equipos; con 36 equipos usa 1.2)")
    p.add_argument("-una-vez", action="store_true",
                   help="no reconectar al cerrarse la conexión (para pruebas con la arena)")
    p.add_argument("-silencioso", action="store_true", help="no imprimir la bitácora en consola")
    p.add_argument("-datos", default=os.path.join(AQUI, "datos"), help="carpeta de la memoria de rivales")
    p.add_argument("-logs", default=os.path.join(AQUI, "logs"), help="carpeta de la bitácora")
    a = p.parse_args()
    if a.estilos:
        for k, v in sorted(ESTILOS.items(), key=lambda kv: kv[1]["numero"]):
            if k != "precavido":
                print(f"  {v['numero']:2d}. {k:<13} {v['descripcion']}")
        print("  (precavido = prudente)")
        return

    token = leer_token(a.token)
    if not token:
        p.error("falta el token: usa -token, la variable POKERFIGHT_TOKEN o un archivo token.txt")

    sys.exit(correr(a.addr, token, reconectar=not a.una_vez, carpeta_datos=a.datos,
                    carpeta_logs=a.logs, modo=a.modo, silencioso=a.silencioso,
                    estilo=a.estilo, ronda=a.ronda, escala=a.escala))


if __name__ == "__main__":
    main()
