"""Personalidades del bot. Se eligen al lanzarlo con -estilo.

Todas comparten el mismo cerebro (equidad por Monte Carlo, rangos según el
tamaño de las apuestas, memoria de rivales). Cada personalidad cambia
algunos números o activa algún comportamiento especial.

Números (1.0 / 0.0 = como el equilibrado):
  apertura     multiplica cuántas manos abre preflop
  tam_apuesta  multiplica el tamaño de apuestas y subidas
  valor        suma al umbral de equidad para apostar/subir por valor
  faroles      multiplica la frecuencia de faroles
  riesgo       multiplica el margen extra para jugarse la pila
  piso         suma a la equidad mínima para jugarse toda la pila

Comportamientos especiales (ver estrategia.py y controladores.py):
  ancho_max, ladron, antimaniaco, presion, evita_lider, cobrador, flotador,
  trampero, perfiles, aprende_rapido, neutral, gto, aleatorio, pushfold, icm,
  simulador, tamano, hu_experto, final, controlador
"""

BASE = dict(apertura=1.0, tam_apuesta=1.0, valor=0.0, faroles=1.0, riesgo=1.0, piso=0.0)


def _e(numero, nombre, descripcion, **cambios):
    d = dict(BASE)
    d.update(cambios)
    d["numero"] = numero
    d["nombre"] = nombre
    d["descripcion"] = descripcion
    return d


ESTILOS = {
    # --- A. Los cuatro originales ---------------------------------------
    "equilibrado": _e(1, "Equilibrado", "lee rivales y cuida la pila"),
    "agresivo": _e(2, "Agresivo", "abre más manos, apuesta más grande y presiona",
                   apertura=1.25, tam_apuesta=1.2, valor=-0.04, faroles=1.4, riesgo=0.7, piso=-0.04),
    "prudente": _e(3, "Prudente", "juega menos manos y casi nunca arriesga la pila",
                   apertura=0.85, tam_apuesta=0.9, valor=0.03, faroles=0.6, riesgo=1.5, piso=0.05),
    "farolero": _e(4, "Farolero", "farolea mucho más contra quien se retira seguido",
                   apertura=1.1, faroles=2.0),

    # --- B. Sobrevivir a la clasificatoria -------------------------------
    "tortuga": _e(5, "Tortuga", "solo juega el ~8 % de mejores manos; casi imposible de eliminar",
                  ancho_max=0.08, valor=0.05, faroles=0.2, riesgo=2.0, piso=0.10),
    "adaptativo": _e(6, "Sobreviviente adaptativo",
                     "prudente cuando va perdiendo, equilibrado cuando va ganando",
                     controlador="adaptativo"),
    "gestor": _e(7, "Gestor de pila", "al ganar 50 % sobre su pila inicial se cierra; si cae mucho, se cuida",
                 controlador="gestor"),
    "antimaniaco": _e(8, "Antimaníaco", "espera buenas manos y paga a los que van all-in sin motivo",
                      apertura=0.85, faroles=0.5, antimaniaco=True),
    "maton": _e(9, "Matón de pilas cortas", "presiona a quien tiene pocas fichas y teme quedar eliminado",
                presion=True),
    "esquivador": _e(10, "Esquivador del líder", "evita botes grandes contra quien lo cubre",
                     evita_lider=True),
    "cerrador": _e(11, "Cerrador de ronda", "cerca de la mano 50 se cierra si va ganando y arriesga si va perdiendo",
                   controlador="cerrador"),

    # --- C. Explotar a los rivales ---------------------------------------
    "clasificador": _e(12, "Clasificador de perfiles", "contraestrategia distinta para cada tipo de rival",
                       perfiles=1.0),
    "cobrador": _e(13, "Cobrador de valor", "no farolea a los pagadores y les cobra fuerte con buenas manos",
                   cobrador=True),
    "ladron": _e(14, "Ladrón de ciegas", "abre muchísimo desde las últimas posiciones",
                 ladron=1.6),
    "flotador": _e(15, "Flotador", "paga en posición y roba cuando el agresor se rinde",
                   flotador=True),
    "trampero": _e(16, "Trampero", "pasa con manos enormes para que el rival apueste, y luego sube",
                   trampero=True),
    "antikit": _e(17, "Anti-kit", "contraestrategias fuertes contra los estilos típicos de los bots de ejemplo",
                  perfiles=2.0, aprende_rapido=0.5),
    "huella": _e(18, "Huella dactilar", "reconoce al rival en pocas manos por sus tamaños de apuesta",
                 perfiles=1.0, aprende_rapido=0.3, huella=True),

    # --- D. Teoría de juegos ---------------------------------------------
    "gto": _e(19, "GTO-lite", "farolea en la proporción matemática según su apuesta; no explota lecturas",
              neutral=True, gto=True),
    "impredecible": _e(20, "Impredecible", "varía al azar sus decisiones dudosas y sus tamaños",
                       aleatorio=0.35),
    "pushfold": _e(21, "Push/fold", "con 15 ciegas o menos solo va all-in o se retira",
                   pushfold=15),
    "icm": _e(22, "ICM", "valora las fichas como un torneo: perder la pila cuesta más de lo que vale ganarla",
              icm=True),

    # --- E. Aprendizaje y adaptación -------------------------------------
    "metabot": _e(23, "Meta-bot", "elige entre 4 estilos según cuál le está dando más fichas",
                  controlador="metabot"),
    "lector": _e(24, "Lector de mesa", "mira a sus rivales y elige el estilo que mejor les gana",
                 controlador="lector"),
    "observador": _e(25, "Observador", "juega muy cerrado al llegar a una mesa y luego explota lo que vio",
                     controlador="observador"),
    "simulador": _e(26, "Simulador de respuestas", "antes de apostar estima cómo respondería el rival a cada tamaño",
                    simulador=True),
    "tamano": _e(27, "Tamaño óptimo", "ajusta el tamaño de cada apuesta a lo que el rival suele pagar",
                 tamano=True),

    # --- F. Fase del torneo ----------------------------------------------
    "unocontrauno": _e(28, "Especialista uno contra uno", "normal en mesa llena; cuando quedan 2, presiona todo",
                       hu_experto=True),
    "finalista": _e(29, "Finalista", "juega siempre como en la final: más agresivo para terminar primero",
                    final=True, apertura=1.15, riesgo=0.6, piso=-0.04),
    "meta": _e(30, "Meta de fichas", "se fija +3 000 por ronda y al lograrlo se cierra",
               controlador="meta"),

    # --- G. Creativos ----------------------------------------------------
    "entrenador": _e(31, "Con entrenador", "entre mesas revisa sus resultados y ajusta sus parámetros",
                     controlador="entrenador"),
    "explicable": _e(32, "Explicable", "solo reglas transparentes: equidad contra pot odds, sin faroles",
                     neutral=True, faroles=0.0),
    "comite": _e(33, "Comité", "tres estilos votan cada jugada y gana la mayoría",
                 controlador="comite"),
    "evolutivo": _e(34, "Evolutivo", "prueba variantes de sí mismo y se queda con las que más ganan",
                    controlador="evolutivo"),

    # --- Pedido especial -------------------------------------------------
    # --- Híbridos: un estilo base + el módulo de uno contra uno ------------
    # Juegan como su estilo base; cuando en la mesa quedan solo 2, cambian al
    # modo uno contra uno sin perder sus lecturas de rivales (ver controladores.py).
    "antikit_uno": _e(37, "Anti-kit + uno contra uno",
                      "anti-kit, y cuando quedan 2 en la mesa presiona como especialista",
                      perfiles=2.0, aprende_rapido=0.5, hu_experto=True),
    "icm_uno": _e(38, "ICM + uno contra uno",
                  "cuida el valor de torneo de sus fichas; cuando quedan 2, deja la cautela y presiona",
                  icm=True, hu_experto=True),
    "esquivador_uno": _e(39, "Esquivador + uno contra uno",
                         "evita al que lo cubre; cuando quedan 2, deja de esquivar y presiona",
                         evita_lider=True, hu_experto=True),

    # --- Híbridos por fases: un estilo para cada etapa del torneo ----------
    # fases: r1 = ronda 1, rondas = rondas 2 a 10, final = mesa final,
    # hu = en la final, cuando queda un solo rival, modo uno contra uno.
    # candado: si (fichas - rondas_que_faltan * ciegas_ronda) > candado, deja de
    # apostar hasta la final (solo desde la ronda "candado_desde").
    "hibrido1_esquivador": _e(40, "Híbrido 1.0", "esquivador en las 10 rondas; Anti-kit en la final; uno contra uno al final",
                              controlador="fases",
                              fases=dict(r1="esquivador", rondas="esquivador", final="antikit", hu=True)),
    "hibrido2_cerrador": _e(41, "Híbrido 2.0", "cerrador en las 10 rondas; Anti-kit en la final; uno contra uno al final",
                            controlador="fases",
                            fases=dict(r1="cerrador", rondas="cerrador", final="antikit", hu=True)),
    "hibrido3_tortuga": _e(42, "Híbrido 3.0", "tortuga en las 10 rondas; Anti-kit en la final; uno contra uno al final",
                           controlador="fases",
                           fases=dict(r1="tortuga", rondas="tortuga", final="antikit", hu=True)),
    "hibrido4_candado": _e(43, "Híbrido 4.0", "ICM en la ronda 1; esquivador con candado en las rondas 2-10; "
                           "Anti-kit en la final; uno contra uno al final",
                           controlador="fases",
                           fases=dict(r1="icm", rondas="esquivador", final="antikit", hu=True,
                                      candado=35000, candado_desde=2, ciegas_ronda=1750)),
    # Híbrido 5: en las rondas 2-10 elige el estilo según sus fichas al empezar
    # cada mesa (dentro del Top 6, cerca del corte o lejos). Umbrales medidos en
    # las simulaciones con 30 bots: (más de esto = dentro, desde esto = cerca).
    # En la final cambia según los jugadores que quedan.
    "hibrido5": _e(44, "Híbrido 5.0", "Antimaníaco en la ronda 1; en las rondas 2-10 Anti-kit con candado "
                   "(dentro del Top 6), Cerrador (cerca) o ICM (lejos); en la final Tortuga (6-4 vivos), "
                   "ICM (3) y Adaptativo (2)",
                   controlador="fases",
                   fases=dict(r1="antimaniaco", rondas="antikit", final="icm", hu=False,
                              situaciones=dict(dentro="antikit", cerca="cerrador", lejos="icm"),
                              umbrales={2: (12000, 7200), 3: (14400, 8560), 4: (16000, 9600),
                                        5: (17200, 10240), 6: (18000, 10800)},
                              final_fases=dict(temprana="tortuga", burbuja="icm", hu="adaptativo"),
                              candado=15500, candado_desde=2, ciegas_ronda=1750)),

    "kamikaze": _e(36, "Kamikaze", "all-in en su primera mano; luego solo ciegas salvo 90 % de equidad; "
                   "experto en uno contra uno", controlador="kamikaze"),
}
ESTILOS["precavido"] = ESTILOS["prudente"]

# Ajustes del modo uno contra uno (los usan unocontrauno, los híbridos y kamikaze).
HU_NUMEROS = dict(apertura=1.2, valor=-0.05, faroles=1.6, riesgo=0.6, piso=-0.05)
# Comportamientos de supervivencia que no tienen sentido cuando solo queda un rival.
HU_SIN = ("icm", "evita_lider", "ancho_max")

# Variante interna para el modo uno contra uno.
UNO_CONTRA_UNO = _e(0, "Uno contra uno", "modo interno", apertura=1.2, valor=-0.05, faroles=1.6,
                    riesgo=0.6, piso=-0.05, perfiles=1.0)

POR_DEFECTO = "hibrido5"  # el que juega si no se indica -estilo
