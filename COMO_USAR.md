# Cómo usar el bot (guía para el equipo)

Necesitas Python 3.6 o superior. No hay que instalar nada más.

## 1. Guarda tu token (una sola vez)

Crea un archivo `token.txt` en esta carpeta con tu token `pfb-...` dentro, solo el token.
Así no tienes que escribirlo en cada comando. `token.txt` está en `.gitignore`: **nunca lo subas a GitHub**.

## 2. Prueba en tu máquina contra los bots del kit

En la carpeta del kit (`pokerfight-arena-participantes`), ya compilado con `go build`:

**Una mesa como la clasificatoria** (5 terminales en PowerShell):

```
.\bin\mesa.exe -addr :9000 -jugadores 6 -min-jugadores 5 -rondas 50 -stack 10000 -ciega-chica 50 -ciega-grande 100 -timeout-ms 5000
.\bin\espia.exe -addr localhost:9000 -token rival-1
.\bin\darwin.exe -addr localhost:9000 -token rival-2
.\bin\estadistico.exe -addr localhost:9000 -token rival-3
python D:\Documentos\GitHub\pokerfight-bot\mi_bot.py -addr localhost:9000 -token mi-bot -una-vez
```

**Torneo contra todos (uno contra uno):** agrega esta línea a `participantes` en `torneo-go.json`
(es el único archivo del kit que puedes editar) y corre `.\bin\arena.exe correr -config torneo-go.json`:

```json
{ "id": "mi-bot", "nombre": "Mi Bot", "comando": ["python", "D:/Documentos/GitHub/pokerfight-bot/mi_bot.py", "-una-vez", "-silencioso"] }
```

En local el token puede ser cualquier texto.

## 3. Prueba en el servidor de práctica (antes del sábado 21)

Revisa la dirección vigente en la guía oficial y luego ejecuta:

```
python mi_bot.py -addr HOST:PUERTO
```

Si dice `Conectado como j-xxxxxx` y luego se queda en silencio, está bien: espera la siguiente ronda.
Conecta **un solo bot por equipo**: una segunda conexión con tu token reemplaza a la primera.

## 4. El día del torneo (domingo 22)

1. Desactiva la suspensión de la computadora y conéctala a la corriente y a una red estable.
2. Cierra cualquier otra copia del bot que use tu token.
3. Ejecuta `python mi_bot.py -addr HOST:PUERTO` con la dirección que anuncie la organización.
4. **No lo cierres** aunque no pase nada: entre rondas hay silencio. Si se cae la red, reconecta solo.
5. Para la final: si el bot sigue corriendo desde la clasificatoria, detecta la final solo. Si lo
   reinicias para la final, agrega `-modo final`.
6. Para detenerlo al terminar, presiona Ctrl+C.

## Elegir el estilo de juego

Agrega `-estilo` al comando para elegir la personalidad del bot:

```
python mi_bot.py -addr HOST:PUERTO -estilo prudente
python mi_bot.py -estilos          # lista las 42 personalidades
```

Hay 34 personalidades base (sobrevivir, explotar rivales, teoría de juegos, aprendizaje,
fase del torneo y creativas), el Kamikaze, 3 variantes "uno contra uno" y 4 híbridos por fases. Si no pones `-estilo`,
juega `hibrido4_candado`. Los números de cada una están en `pfbot/estilos.py`, y las
que cambian de estilo sobre la marcha (meta-bot, lector, entrenador, comité,
evolutivo, kamikaze...) en `pfbot/controladores.py`.

## Híbridos por fases y el candado

Los estilos `hibrido1_esquivador`, `hibrido2_cerrador`, `hibrido3_tortuga` y `hibrido4_candado`
usan un estilo distinto según la etapa: ronda 1, rondas 2 a 10, final y, en la final, modo uno
contra uno cuando queda un solo rival. En la final los cuatro juegan con `antikit`. Se definen en `pfbot/estilos.py` (campo `fases`): para
crear otro híbrido, copia uno y cambia los nombres de los estilos.

El `hibrido4_candado` deja de apostar (solo pasa o se retira) cuando
`fichas - (10 - ronda + 1) * 1750 > 35000`, desde la ronda 2 hasta la final.

El bot cuenta las rondas solo, porque usa una sola conexión para todo el torneo. **Si tienes
que reiniciarlo a mitad del torneo**, indica en qué ronda entra, por ejemplo `-ronda 6`, y si
lo reinicias para la final, usa `-modo final`.

## Enfrentar los estilos en tu laptop

La carpeta `pruebas/bin` trae la arena y los bots del kit oficial ya compilados para Windows.

```
python pruebas\torneo_estilos.py              # 10 mesas: los 4 estilos + un bot del kit
python pruebas\torneo_estilos.py --mesas 30   # más mesas = menos suerte
python pruebas\torneo_estilos.py --estilos prudente agresivo --rival ninguno
```

Cada mesa tarda alrededor de un minuto. Al final verás una tabla con las fichas promedio de cada
estilo y cuántas veces quedó eliminado. Los detalles quedan en `pruebas/resultados/`.

## Torneo completo en tu laptop (formato oficial)

```
python pruebas\torneo_completo.py                     # un torneo completo
python pruebas\torneo_completo.py --minutos-final 15  # final más corta
python pruebas\torneo_completo.py --torneos 3         # varios torneos y tabla de títulos
python pruebas\torneo_completo.py --sin-final         # solo las 10 rondas, sin la final
```

Juegan los bots de `pruebas\participantes.txt` (30 por defecto, como el torneo oficial).
Para sacar a uno, ponle `#` adelante; para meter uno, escribe su nombre en una línea nueva.
El simulador de finales usa la misma lista.

- **Clasificatoria:** 10 rondas. En cada una se sortean mesas de 5 (algunas de 6). Cada mesa
  termina a las 50 manos, a los 6 minutos o cuando queda uno con fichas. Cada bot conserva sus
  fichas entre rondas y el que llega a 0 queda eliminado.
- **Final:** los 6 con más fichas (o, si quedan menos de 6, los últimos eliminados) vuelven a
  10 000 y juegan hasta que quede uno o pase 1 hora.

Un torneo tarda alrededor de 30 minutos de clasificatoria más la final. Para acelerar, usa
`--minutos-final 15` o `--paralelo 6` si tu laptop tiene varios núcleos.
Las mesas usan `pruebas\bin\mesa-fichas.exe`: el mismo motor de mesa del kit oficial,
compilado con una opción extra para que cada bot empiece con sus propias fichas.

## Solo finales: quién es mejor en la mesa final

```
python pruebas\torneo_finales.py                  # los bots de participantes.txt, 3 ciclos
python pruebas\torneo_finales.py --ciclos 10 --bots equilibrado entrenador icm simulador prudente tamano
```

Cada final es como la oficial: 6 bots, todos con 10 000 fichas, hasta que quede uno (con tope
de 400 manos o 60 minutos; si se llega al tope, gana quien tenga más fichas). En cada ciclo los
bots se sortean en grupos de 6 y juegan una final por grupo. Al final verás, para cada bot,
cuántas finales jugó, cuántas ganó y su puesto medio (1 = siempre gana, 6 = siempre cae primero).

## Doble eliminación entre 32 estilos

```
python pruebas\torneo_doble_elim.py --paralelo 4
```

Cada partida es un uno contra uno con 30 000 fichas cada uno, hasta que uno se quede sin
fichas o pasen 60 minutos (`--minutos`); en ese caso gana el que tenga más. Quien pierde dos
partidas queda eliminado, y los empatados por puesto juegan desempates hasta ordenar los 32.
El resultado queda en `pruebas\resultados\doble-elim-...\resumen.json`.

Usa `--paralelo 4` o menos: con más partidas a la vez la laptop se satura, los bots dejan de
responder a tiempo y esas partidas no valen. No cierres la ventana hasta que termine.

## Usar dos computadoras

El código está en GitHub (repositorio privado). En la segunda computadora, clónalo una vez con
`git clone` y, antes de cada simulación, actualízalo con `git pull`. Cuando cambies algo, súbelo con
`git add .`, `git commit -m "..."` y `git push`. No copies `token.txt` a la otra computadora: las
simulaciones no lo necesitan y el bot real se conecta desde una sola máquina.

## Qué ves en pantalla

Cada jugada se explica en una línea, por ejemplo:

```
[mesa-3-mano-12] turn: Kh 9h | mesa Kc 7d Qc Ts | bote 2400 | equidad 41% vs 1 rival(es)
  | pagar 1800 (necesito 43%+5%) | apostó roca (40 manos, juega 18%, ...) -> ME RETIRO
```

Todo queda guardado en `logs/`. En `datos/rivales.json` está lo que el bot aprendió de cada rival.
Si quieres empezar el torneo con la memoria limpia, borra ese archivo antes.

## Ajustes rápidos

Lo más fácil es tocar los estilos en `pfbot/estilos.py`. Para cambios más profundos, en `pfbot/estrategia.py`:

- `APERTURA`: con qué fracción de manos abre según cuántos faltan por hablar.
- `_riesgo` y `_piso_supervivencia`: cuánta ventaja extra exige para jugarse la pila.
