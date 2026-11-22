# PokerFight Bot: Híbrido 5.0, el bot que se arma con lo mejor de cada estilo

Bot de Texas Hold'em No-Limit para PokerFight, escrito en Python puro (3.8+, sin dependencias).
No es un solo estilo de juego: es una **fusión de varios bots**, la quinta versión de nuestros híbridos por fases (1.0 a 5.0). Primero creamos 43 personalidades,
las enfrentamos entre sí en miles de manos con el formato oficial y medimos cuál rinde mejor en
cada fase del torneo. El bot final usa, en cada momento, la que ganó esa fase.

## Cómo juega cada mano (el motor común)

1. **Equidad por Monte Carlo con rangos.** En cada turno simula hasta 20 000 finales posibles
   (en menos de 0,8 s) con un evaluador propio. A cada rival le asigna manos coherentes con lo que hizo.
2. **El tamaño de la apuesta cuenta una historia.** Medio bote, bote completo o una sobreapuesta
   implican rangos distintos: el bot se queda con la franja de manos que encaja con esa apuesta.
3. **Memoria de rivales por alias.** Para cada rival guarda cuánto juega, sube, se retira y farolea
   (medido en los showdowns), y aprende el ancho real de su rango. Sobrevive a reinicios.
4. **Pot odds y supervivencia.** Paga si su equidad supera el precio más un margen que crece cuando
   se juega la pila contra alguien que lo cubre: en la clasificatoria, quedarse sin fichas es definitivo.

## La fusión: qué estilo usa en cada fase y por qué

| Fase | Estilo | Por qué lo elegimos (datos de nuestras simulaciones) |
|---|---|---|
| Ronda 1 | **Antimaníaco** | Nunca eliminado en 23 rondas 1 simuladas; ganó fichas en 15 de 23 mesas. |
| Rondas 2-10, **dentro** del Top 6 | **Anti-kit + candado** | Desde esa situación terminó clasificando el 94 % de las veces. |
| Rondas 2-10, **cerca** del Top 6 | **Cerrador** | Entró al Top 6 el 65 % de las veces (el promedio fue 28 %). |
| Rondas 2-10, **lejos** del corte | **ICM** | El que más remonta: 43 % (el promedio fue 10 %). |
| Final con 6 a 4 vivos | **Tortuga** | Llegó al podio en 7 de 8 finales. |
| Final con 3 vivos (burbuja) | **ICM** | Las 7 veces que llegó al podio terminó 1.º o 2.º. |
| Final con 2 vivos | **Adaptativo** | Campeón invicto del torneo uno contra uno de 32 estilos (9-2 en total). |

**¿Cómo sabe en qué situación está?** El servidor no informa el puesto ni las fichas de otras mesas,
así que al empezar cada mesa compara sus fichas con el corte del Top 6 que medimos ronda por ronda:

| Ronda | Dentro si tiene más de | Cerca si tiene desde | Si no, lejos |
|---|---|---|---|
| 2 | 12 000 | 7 200 | |
| 3 | 14 400 | 8 560 | |
| 4 | 16 000 | 9 600 | |
| 5 | 17 200 | 10 240 | |
| 6 a 10 | 18 000 | 10 800 | |

Cuenta las rondas por los cambios de mesa (una sola conexión para todo el torneo) y, en la final,
los rivales vivos con `en_torneo`. El **candado** deja de apostar cuando
`fichas − rondas_que_faltan × 1 750 > 15 500`: la clasificación está asegurada aunque pierda
todas las ciegas restantes.

## Lo creativo: un torneo de bots para elegir al bot

- **43 personalidades** propias: conservadoras, agresivas, lectoras de rivales, de teoría de juegos,
  un meta-bot que aprende qué estilo le da más fichas, un comité que vota cada jugada y un
  evolutivo que muta sus propios parámetros.
- **Simuladores propios** que reproducen el torneo oficial en local: clasificatoria con fichas
  acumuladas, finales y un torneo uno contra uno de doble eliminación.
- **Decisiones con datos, no con intuición:** 23 torneos simulados (138 mesas de ronda 1),
  77 rondas analizadas según la posición de cada bot frente al corte, 43 mesas finales y
  170 duelos uno contra uno. Así vimos, por ejemplo, que el puesto más peligroso de la burbuja
  es el del medio y no el más corto, y que el estilo que mejor clasifica no es el que mejor
  cierra una final.
- **Bitácora que explica cada decisión**, incluidos los cambios de estilo
  (`Híbrido 5.0: ronda 3, cerca del Top 6 -> juego como cerrador`).

## Robustez

Responde siempre a tiempo (máximo observado 0,8 s de 5 s), valida cada acción contra
`acciones_validas` (`monto` es el total de la ronda), juega la acción segura si algo falla,
se reconecta sola con espera creciente y nunca envía `abandono`.

## Uso

```
python mi_bot.py -addr HOST:PUERTO -token TU_TOKEN
```

Juega el Híbrido 5.0 por defecto (`-estilo hibrido5`). El token también puede ir en `POKERFIGHT_TOKEN` o en `token.txt` (no se sube al repositorio).
`-escala 1.2` sube los umbrales si hay más equipos de los previstos (18), `-ronda N` indica la ronda
si se reinicia a mitad del torneo, `-modo final` fuerza la final y `-estilos` lista las 43
personalidades. Bitácora en `logs/`; memoria de rivales en `datos/rivales.json`.

**Estructura:** `pfbot/cartas.py` (evaluador) · `equidad.py` (Monte Carlo) · `rivales.py` (memoria) ·
`estrategia.py` (decisiones) · `estilos.py` y `controladores.py` (personalidades y fases) ·
`bot.py` (protocolo) · `pruebas/` (simuladores).
