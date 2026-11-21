# PokerFight Bot: el lector de apuestas

Bot de Texas Hold'em No-Limit para PokerFight, escrito en Python puro (3.6+, sin dependencias).
Su idea central: **no adivinar a ciegas, sino leer a cada rival y razonar con probabilidades**,
y explicar cada decisión en una bitácora legible.

## Cómo piensa

1. **Equidad por Monte Carlo con rangos.** En cada turno simula miles de finales posibles
   (unas 20 000 en menos de 0,7 s) con un evaluador propio. Cada rival recibe manos coherentes
   con lo que hizo, no cartas al azar.
2. **El tamaño de la apuesta cuenta una historia.** Medio bote, bote completo o una sobreapuesta
   implican rangos distintos: el bot ordena todas las manos posibles del rival según su fuerza en
   esa mesa y se queda con la franja que encaja con la apuesta (más estrecha si sube sobre otra apuesta).
3. **Memoria de rivales por alias.** Los alias son estables todo el torneo, así que el bot guarda
   para cada rival cuánto juega, cuánto sube, cuánto se retira y **cuánto farolea** (medido en los
   showdowns). Además aprende el ancho real de su rango con las cartas que muestra: si alguien sube
   con basura, lo detecta y lo paga más. La memoria se guarda en disco y sobrevive a reinicios.
4. **Decisión con pot odds.** Paga si su equidad supera lo que cuesta pagar más un margen que
   depende de la posición y del riesgo. Apuesta por valor con manos fuertes, farolea más contra
   quien se retira mucho y nunca contra quien paga todo.
5. **Supervivencia primero.** En la clasificatoria quedarse sin fichas es definitivo. Si una jugada
   arriesga toda la pila contra alguien que nos cubre, exige más ventaja. En la final, con las pilas
   reiniciadas, el bot lo detecta y se vuelve algo más agresivo.

## Estrategia por defecto: el Híbrido 4 con candado

El bot tiene 42 personalidades (una por estilo de juego) y por defecto juega por fases:

- **Ronda 1, ICM:** cuida el valor de torneo de sus fichas: perder la pila cuesta más de lo que vale ganarla.
- **Rondas 2 a 10, esquivador:** evita los botes grandes contra quien tiene más fichas que él.
- **Candado:** si `fichas - rondas_que_faltan × 1 750 > 35 000`, la clasificación ya está asegurada
  aunque pierda todas las ciegas que quedan, así que deja de apostar hasta la final.
- **Final, Anti-kit:** aplica contraestrategias a los estilos típicos de bots; fue el que mejor rindió
  en las finales simuladas. Con un solo rival,
  pasa a modo uno contra uno.

Todo se eligió simulando en local el torneo en el formato oficial, finales y duelos entre estilos.

## Robustez

- Responde siempre a tiempo (mediana de 0,25 s y máximo observado de 0,8 s, con un plazo de 5 s)
  y valida cada acción contra `acciones_validas`, con `monto` como total de la ronda.
- Si algo falla internamente, juega la acción segura en vez de quedarse callado.
- Reconexión automática con espera creciente; nunca envía `abandono`.

## Resultados en pruebas locales

Mesas de 5 jugadores con las condiciones de la clasificatoria (10 000 fichas, 50/100, 50 manos)
contra 4 bots del kit elegidos al azar, en las mismas 80 mesas para cada bot (estilo base):

| Bot | Fichas promedio por mesa | Mesas en que quedó eliminado |
|---|---|---|
| **Este bot** | **+4 343** | **11 / 80** |
| Darwin (kit) | +1 493 | 40 / 80 |
| Espía (kit) | +485 | 33 / 80 |


## Uso

```
python mi_bot.py -addr HOST:PUERTO -token TU_TOKEN
```

El token también puede ir en la variable `POKERFIGHT_TOKEN` o en un archivo `token.txt`, que no se sube
al repositorio. Opciones: `-estilo NOMBRE` elige una de sus 42 personalidades (por defecto `hibrido4_candado`; `-estilos` las lista),
incluidas un meta-bot que elige su estilo según la mesa, un comité que vota cada jugada y un
evolutivo que muta sus propios parámetros. `-modo final` fuerza el modo final, `-ronda N` indica
la ronda si se reinicia a mitad del torneo, `-silencioso` oculta la bitácora en consola y
`-una-vez` desactiva la reconexión (para la arena local). La bitácora queda en `logs/`
y la memoria de rivales en `datos/rivales.json`.

## Estructura

`pfbot/cartas.py` (evaluador) · `equidad.py` (Monte Carlo y rangos) · `rivales.py` (memoria) ·
`estrategia.py` (decisiones) · `estilos.py` y `controladores.py` (personalidades y fases) ·
`bot.py` (protocolo y reconexión) · `tablas.py` (fuerza preflop precalculada) ·
`pruebas/` (simuladores locales del torneo).
