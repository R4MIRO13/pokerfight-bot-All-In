#!/usr/bin/env python3
"""Torneo uno contra uno de doble eliminación, con 32 estilos.

Cada partida es como la mesa final oficial pero de 2 jugadores: cada estilo
empieza con 30 000 fichas, ciegas 50/100, 5 s por jugada; gana el último en
pie o, si se cumple el tiempo (1 hora por defecto), quien tenga más fichas.

Formato
  Winner bracket  dieciseisavos (sorteo 100 % aleatorio), octavos, cuartos,
                  semifinales y final del winner bracket.
  Loser bracket   los que pierden en el winner bracket bajan al loser bracket;
                  una segunda derrota elimina. El orden es fijo desde el sorteo.
  Gran final      campeón del winner bracket vs campeón del loser bracket,
                  partida única (sin reinicio).
  Desempates      los eliminados en la misma ronda quedan empatados en un
                  grupo (5-6, 7-8, 9-12, 13-16, 17-24, 25-32). Cada grupo se
                  ordena por completo con rondas sucesivas (ganadores arriba,
                  perdedores abajo), así que al final no queda ningún empate.

Orden: 10 tandas. Desde la tanda 4 hay como máximo 8 enfrentamientos por tanda
(--max-tanda); los lugares que deja libres el bracket se llenan con desempates,
priorizando siempre los puestos más altos. Dentro de una tanda se juegan hasta
--paralelo partidas a la vez y, en cuanto una termina, entra la próxima.

Uso (desde la carpeta pokerfight-bot):
    python pruebas\\torneo_doble_elim.py
    python pruebas\\torneo_doble_elim.py --paralelo 8 --minutos 30
"""

import argparse
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
from torneo_completo import etiqueta, jugar_mesa, todos_los_bots  # noqa: E402

FICHAS_UNO_CONTRA_UNO = 30000

ESTILOS_POR_DEFECTO = [
    "antikit", "simulador", "huella", "icm", "farolero", "ladron", "esquivador", "unocontrauno",
    "cobrador", "lector", "metabot", "tamano", "observador", "maton", "antimaniaco", "clasificador",
    "entrenador", "gestor", "equilibrado", "comite", "impredecible", "meta", "trampero", "cerrador",
    "finalista", "evolutivo", "agresivo", "explicable", "tortuga", "prudente", "adaptativo", "gto",
]


class Torneo:
    def __init__(self, bots, args, carpeta):
        self.args = args
        self.carpeta = carpeta
        self.bots = bots
        self.registro = []      # todas las partidas jugadas
        self.inicio = time.time()

    # --- Una partida ----------------------------------------------------
    def partida(self, codigo, a, b):
        fichas = {a: FICHAS_UNO_CONTRA_UNO, b: FICHAS_UNO_CONTRA_UNO}
        res, info = jugar_mesa(codigo, [a, b], fichas, -1, self.args.minutos * 60,
                               "final", self.carpeta, self.args)
        fa, fb = res[a][0], res[b][0]
        if fa == fb:
            ganador = random.choice([a, b])
            motivo = "empate en fichas, se sorteó"
        else:
            ganador = a if fa > fb else b
            motivo = "se acabó el tiempo" if info.get("cerrada_por_tiempo") else "quedó sin fichas"
        perdedor = b if ganador == a else a
        dato = {"codigo": codigo, "ganador": ganador, "perdedor": perdedor,
                "fichas": {a: fa, b: fb}, "manos": info.get("manos"), "motivo": motivo}
        self.registro.append(dato)
        return dato

    def etapa(self, titulo, cruces):
        """Juega en paralelo una lista de (codigo, a, b) y devuelve {codigo: resultado}."""
        if not cruces:
            return {}
        print(f"\n{titulo}", flush=True)
        resultados = {}
        with ThreadPoolExecutor(max_workers=self.args.paralelo) as ex:
            for d in ex.map(lambda c: self.partida(*c), cruces):
                resultados[d["codigo"]] = d
                g, p = d["ganador"], d["perdedor"]
                print(f"  {d['codigo']:<7} {etiqueta(g):<24} vence a {etiqueta(p):<24} "
                      f"({d['fichas'][g]:,} a {d['fichas'][p]:,}, {d['manos']} manos, {d['motivo']})".replace(",", " "),
                      flush=True)
        print(f"  ({(time.time() - self.inicio) / 60:.0f} min)", flush=True)
        return resultados

    # --- Doble eliminación ---------------------------------------------
    def jugar(self):
        sorteo = list(self.bots)
        random.shuffle(sorteo)
        print("Sorteo de dieciseisavos:")
        for i in range(16):
            print(f"  W1-{i + 1:02d}: {etiqueta(sorteo[2 * i])}  vs  {etiqueta(sorteo[2 * i + 1])}")

        puestos = {}
        desempates = Desempates(puestos)
        res = {}  # todos los resultados del bracket, por código

        def g(prefijo, n):
            return [res[f"{prefijo}-{i + 1:02d}"]["ganador"] for i in range(n)]

        def p(prefijo, n):
            return [res[f"{prefijo}-{i + 1:02d}"]["perdedor"] for i in range(n)]

        def cruzar(prefijo, lista):
            return [(f"{prefijo}-{i + 1:02d}", lista[2 * i], lista[2 * i + 1]) for i in range(len(lista) // 2)]

        def mezclar(prefijo, de_abajo, del_winner):
            # Los que bajan del winner bracket entran en orden inverso, para evitar
            # que se repitan enfrentamientos tempranos.
            del_winner = list(reversed(del_winner))
            return [(f"{prefijo}-{i + 1:02d}", de_abajo[i], del_winner[i]) for i in range(len(de_abajo))]

        # Cada tanda: (título, función que arma los cruces del bracket, grupo de
        # desempate que se forma al terminarla).
        tandas = [
            ("Dieciseisavos (W)", lambda: cruzar("W1", sorteo), None),
            ("Octavos (W) + Loser ronda 1",
             lambda: cruzar("W2", g("W1", 16)) + cruzar("L1", p("W1", 16)),
             lambda: (25, 32, p("L1", 8))),
            ("Cuartos (W) + Loser ronda 2",
             lambda: cruzar("W3", g("W2", 8)) + mezclar("L2", g("L1", 8), p("W2", 8)),
             lambda: (17, 24, p("L2", 8))),
            ("Semifinales (W) + Loser ronda 3",
             lambda: cruzar("W4", g("W3", 4)) + cruzar("L3", g("L2", 8)),
             lambda: (13, 16, p("L3", 4))),
            ("Final (W) + Loser ronda 4",
             lambda: cruzar("W5", g("W4", 2)) + mezclar("L4", g("L3", 4), p("W3", 4)),
             lambda: (9, 12, p("L4", 4))),
            ("Loser ronda 5", lambda: cruzar("L5", g("L4", 4)), lambda: (7, 8, p("L5", 2))),
            ("Loser ronda 6 (entran los perdedores de semifinales)",
             lambda: mezclar("L6", g("L5", 2), p("W4", 2)), lambda: (5, 6, p("L6", 2))),
            ("Semifinal del loser bracket", lambda: cruzar("L7", g("L6", 2)), None),
            ("Final del loser bracket (entra el perdedor de la final W)",
             lambda: [("L8-01", res["L7-01"]["ganador"], res["W5-01"]["perdedor"])], None),
            ("GRAN FINAL", lambda: [("GF-01", res["W5-01"]["ganador"], res["L8-01"]["ganador"])], None),
        ]

        n = 0
        for titulo, armar, grupo in tandas:
            n += 1
            bracket = armar()
            # Desde la tanda 4, como máximo 8 enfrentamientos por tanda en total.
            cupo = None if n <= 3 else max(0, self.args.max_tanda - len(bracket))
            extra = desempates.tomar(cupo)
            nombre = f"TANDA {n} - {titulo}"
            if extra:
                nombre += " + desempates " + desempates.describir(extra)
            jugados = self.etapa(nombre, bracket + extra)
            res.update({k: v for k, v in jugados.items() if not k.startswith("D")})
            desempates.registrar(jugados)
            if grupo:
                desempates.nuevo_grupo(*grupo())
        puestos[res["GF-01"]["ganador"]] = (1, 1)
        puestos[res["GF-01"]["perdedor"]] = (2, 2)
        puestos[res["L8-01"]["perdedor"]] = (3, 3)
        puestos[res["L7-01"]["perdedor"]] = (4, 4)

        # Si quedara algún desempate pendiente (no debería con 8 por tanda), se
        # juega en tandas extra.
        while desempates.pendientes():
            n += 1
            extra = desempates.tomar(self.args.max_tanda)
            self.etapa(f"TANDA {n} - desempates " + desempates.describir(extra), extra)
            desempates.registrar({d["codigo"]: d for d in self.registro if d["codigo"] in {c[0] for c in extra}})
        return puestos


class Desempates:
    """Ordena por completo cada grupo de empatados con rondas sucesivas.

    Un subgrupo de N jugadores (puestos desde..hasta) se empareja al azar: los
    ganadores pasan al subgrupo de arriba y los perdedores al de abajo. Un
    subgrupo de 2 define los dos puestos exactos. La siguiente ronda de un grupo
    empieza cuando termina la anterior. Al repartir cupos se priorizan siempre
    los puestos más altos.
    """

    def __init__(self, puestos):
        self.puestos = puestos
        self.grupos = []  # cada grupo: {"listos": [cruces], "en_juego": {codigo: sub}, "subgrupos": [...]}

    def nuevo_grupo(self, desde, hasta, jugadores):
        grupo = {"en_juego": {}, "resultados": [], "listos": []}
        self.grupos.append(grupo)
        self._abrir_ronda(grupo, [(desde, hasta, list(jugadores))])

    def _abrir_ronda(self, grupo, subgrupos):
        grupo["subgrupos"] = subgrupos
        grupo["resultados"] = []
        grupo["listos"] = []
        for desde, hasta, jug in subgrupos:
            jug = list(jug)
            random.shuffle(jug)
            for i in range(len(jug) // 2):
                cod = f"D{desde:02d}-{hasta:02d}-{i + 1}"
                grupo["listos"].append((cod, jug[2 * i], jug[2 * i + 1], desde, hasta))

    def pendientes(self):
        return any(g["listos"] or g["en_juego"] for g in self.grupos)

    def tomar(self, cupo):
        """Saca hasta `cupo` desempates listos para jugar, priorizando los puestos más altos."""
        listos = sorted(((c[3], c, g) for g in self.grupos for c in g["listos"]), key=lambda x: x[0])
        if cupo is not None:
            listos = listos[:cupo]
        cruces = []
        for _, c, g in listos:
            g["listos"].remove(c)
            g["en_juego"][c[0]] = c
            cruces.append(c[:3])
        return cruces

    def describir(self, cruces):
        cuenta = {}
        for cod, _, _ in cruces:
            d, h = cod[1:].split("-")[:2]
            clave = f"{int(d)}.º-{int(h)}.º"
            cuenta[clave] = cuenta.get(clave, 0) + 1
        return ", ".join(f"{k} ({v})" for k, v in cuenta.items())

    def registrar(self, resultados):
        for g in self.grupos:
            for cod in list(g["en_juego"]):
                if cod not in resultados:
                    continue
                _, _, _, desde, hasta = g["en_juego"].pop(cod)
                d = resultados[cod]
                g["resultados"].append((desde, hasta, d["ganador"], d["perdedor"]))
                if hasta - desde == 1:  # par: puestos exactos
                    self.puestos[d["ganador"]] = (desde, desde)
                    self.puestos[d["perdedor"]] = (hasta, hasta)
            # ¿Terminó la ronda de este grupo? Entonces se abre la siguiente.
            if not g["listos"] and not g["en_juego"] and g["resultados"]:
                siguientes = []
                for desde, hasta, jug in g["subgrupos"]:
                    if len(jug) <= 2:
                        continue
                    mitad = len(jug) // 2
                    gan = [r[2] for r in g["resultados"] if r[0] == desde and r[1] == hasta]
                    per = [r[3] for r in g["resultados"] if r[0] == desde and r[1] == hasta]
                    siguientes.append((desde, desde + mitad - 1, gan))
                    siguientes.append((desde + mitad, hasta, per))
                if siguientes:
                    self._abrir_ronda(g, siguientes)
                else:
                    g["resultados"] = []
                    g["subgrupos"] = []


def main():
    p = argparse.ArgumentParser(description="Torneo uno contra uno de doble eliminación (32 estilos)")
    p.add_argument("--bots", nargs="+", default=ESTILOS_POR_DEFECTO, choices=todos_los_bots(),
                   metavar="BOT", help="exactamente 32 estilos (por defecto, la lista elegida)")
    p.add_argument("--minutos", type=int, default=60,
                   help="tope de tiempo por partida; al cumplirse gana quien tenga más fichas (por defecto 60)")
    p.add_argument("--paralelo", type=int, default=6, help="partidas que se juegan a la vez (por defecto 6)")
    p.add_argument("--max-tanda", type=int, default=8,
                   help="máximo de enfrentamientos por tanda desde la tanda 4 (por defecto 8)")
    p.add_argument("--bin", default=os.path.join(AQUI, "bin"), help="carpeta con mesa-fichas")
    args = p.parse_args()

    bots = list(dict.fromkeys(args.bots))
    if len(bots) != 32:
        sys.exit(f"Hacen falta exactamente 32 estilos distintos (hay {len(bots)}).")
    carpeta = os.path.join(AQUI, "resultados", "doble-elim-" + time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(carpeta, exist_ok=True)
    print(f"Doble eliminación uno contra uno: 32 estilos, {FICHAS_UNO_CONTRA_UNO} fichas cada uno, "
          f"tope de {args.minutos} min por partida. Resultados en {carpeta}\n")

    torneo = Torneo(bots, args, carpeta)
    puestos = torneo.jugar()

    print("\n==================== CLASIFICACIÓN FINAL ====================")
    for b in sorted(bots, key=lambda x: puestos[x]):
        desde, hasta = puestos[b]
        texto = f"{desde}.º" if desde == hasta else f"{desde}.º-{hasta}.º"
        ganadas = sum(1 for d in torneo.registro if d["ganador"] == b)
        perdidas = sum(1 for d in torneo.registro if d["perdedor"] == b)
        print(f"  {texto:<10} {etiqueta(b):<24} {ganadas} ganadas, {perdidas} perdidas")
    campeon = min(bots, key=lambda x: puestos[x])
    print(f"\n  CAMPEÓN: {etiqueta(campeon)}   ({(time.time() - torneo.inicio) / 60:.0f} min en total)")

    with open(os.path.join(carpeta, "resumen.json"), "w", encoding="utf-8") as f:
        json.dump({"puestos": puestos, "partidas": torneo.registro}, f, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
