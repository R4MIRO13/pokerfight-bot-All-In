"""Conexión con la arena: handshake, bucle de mensajes y reconexión.

Reglas del torneo que este archivo cuida:
- Una sola conexión para todo el torneo; entre rondas el socket queda en
  silencio y NO hay que cerrarlo.
- Si la conexión se cae, reconectar con el mismo token (se retoma la silla).
- Responder siempre a tiempo y solo con acciones de `acciones_validas`.
- Nunca enviar "abandono".
"""

import json
import os
import random
import socket
import sys
import time
import traceback
from datetime import datetime

from .cartas import desde_protocolo, legibles
from .estrategia import Contexto, decidir, validar
from .estilos import ESTILOS
from . import controladores
from .rivales import Memoria

VERSION = "1.0.0"
PASAJERO = "demasiadas conexiones esperando el saludo"


class ErrorDefinitivo(Exception):
    """La mesa rechazó la conexión por algo que reintentar no arregla."""


class Bitacora:
    """Registro legible de cada decisión: el 'por qué' de cada jugada."""

    def __init__(self, carpeta, silencioso=False):
        self.silencioso = silencioso
        self.archivo = None
        if carpeta:
            os.makedirs(carpeta, exist_ok=True)
            nombre = datetime.now().strftime("bitacora-%Y%m%d-%H%M%S") + f"-{os.getpid()}.log"
            self.archivo = open(os.path.join(carpeta, nombre), "a", encoding="utf-8")

    def __call__(self, texto, consola=True):
        linea = f"{datetime.now():%H:%M:%S} {texto}"
        if self.archivo:
            self.archivo.write(linea + "\n")
            self.archivo.flush()
        if consola and not self.silencioso:
            try:
                print(linea, flush=True)
            except UnicodeEncodeError:
                try:
                    print(linea.encode("ascii", "replace").decode(), flush=True)
                except OSError:
                    self.silencioso = True
            except OSError:
                # La consola ya no acepta texto (ventana cerrada, tubería rota):
                # seguimos jugando y escribiendo solo en el archivo.
                self.silencioso = True


class Bot:
    def __init__(self, direccion, token, carpeta_datos="datos", carpeta_logs="logs",
                 modo="auto", silencioso=False, estilo="equilibrado", ronda=0):
        self.direccion = direccion
        self.token = token
        self.memoria = Memoria(os.path.join(carpeta_datos, "rivales.json") if carpeta_datos else None,
                               factor_prior=ESTILOS[estilo].get("aprende_rapido", 1.0))
        self.log = Bitacora(carpeta_logs, silencioso)
        self.controlador = controladores.crear(estilo, self.memoria, self.log)
        # Ronda de la clasificatoria: la mesa que estamos jugando en esta sesión,
        # o la que se indique con -ronda (si el bot se reinició a mitad del torneo).
        self.ronda_inicial = ronda
        self.mano_mesa = 0
        self.pila_inicio_mesa = None
        self.pila_previa = None
        self.modo_forzado = None if modo == "auto" else modo
        self.estilo = estilo
        self.modo = self.modo_forzado or "clasificatoria"
        self.id_jugador = None
        self.cartas = []
        self.estado_inicio = None
        self.ultimo_estado = None
        self.mesa_actual = None
        self.ids_mesa = None
        self.ultima_pila = None
        self.mesas = 0
        self.manos = 0
        self.timeouts_propios = 0

    # --- Conexión -----------------------------------------------------
    def _conectar(self):
        host, puerto = self.direccion.rsplit(":", 1)
        s = socket.create_connection((host, int(puerto)), timeout=15)
        s.settimeout(None)  # entre rondas puede haber minutos de silencio
        s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return s

    def _enviar(self, s, mensaje):
        s.sendall((json.dumps(mensaje) + "\n").encode("utf-8"))

    def jugar_una_conexion(self):
        """Juega hasta que la mesa cierre el socket. Devuelve True si hubo bienvenida."""
        s = self._conectar()
        entrada = s.makefile("r", encoding="utf-8", newline="\n")
        try:
            self._enviar(s, {"tipo": "saludo", "version": VERSION, "token": self.token})
            linea = entrada.readline()
            if not linea:
                raise ConnectionError("la mesa cerró la conexión durante el saludo")
            msg = json.loads(linea)
            if msg.get("tipo") == "error":
                texto = msg.get("mensaje", "")
                if PASAJERO in texto:
                    raise ConnectionError(texto)
                raise ErrorDefinitivo(texto)
            if msg.get("tipo") != "bienvenida":
                raise ConnectionError(f"se esperaba bienvenida, llegó {msg.get('tipo')}")
            self.id_jugador = msg.get("id_jugador") or self.token
            self.log(f"Conectado como {self.id_jugador} (silla {msg.get('silla')}), estilo {self.estilo}. "
                     f"Esperando mesa... (el silencio entre rondas es normal)")

            for linea in entrada:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    msg = json.loads(linea)
                except ValueError:
                    continue
                self._procesar(s, msg)
            return True
        finally:
            try:
                s.close()
            except OSError:
                pass

    # --- Mensajes -----------------------------------------------------
    def _procesar(self, s, msg):
        tipo = msg.get("tipo")
        if tipo == "mano_inicio":
            self.cartas = [desde_protocolo(c) for c in msg.get("cartas", [])]
            self.estado_inicio = msg.get("estado") or {}
            self.ultimo_estado = self.estado_inicio
            self.pila_previa = self._mi_pila(self.estado_inicio)
            self._detectar_mesa(self.estado_inicio)
            self.manos += 1
            self.mano_mesa += 1
        elif tipo == "estado":
            self.ultimo_estado = msg.get("estado") or self.ultimo_estado
        elif tipo == "solicitar_accion":
            self.ultimo_estado = msg.get("estado") or self.ultimo_estado
            self._responder(s, msg)
        elif tipo == "mano_fin":
            self._fin_de_mano(msg.get("resultado") or {})
        elif tipo == "error":
            self.log(f"Mensaje de error de la mesa: {msg.get('mensaje')}")
        # Cualquier otro tipo se ignora, como pide el protocolo.

    def _detectar_mesa(self, estado):
        id_mano = estado.get("id_mano", "")
        mesa = id_mano.rsplit("-mano-", 1)[0] if "-mano-" in id_mano else id_mano
        jugadores = estado.get("jugadores") or []
        ids = frozenset(j.get("id") for j in jugadores)
        # Cambio de mesa: otro identificador o, por si acaso, otros jugadores sentados.
        if mesa == self.mesa_actual and ids == self.ids_mesa:
            return
        self.mesa_actual = mesa
        self.ids_mesa = ids
        self.mesas += 1
        self.mano_mesa = 0
        self.pila_inicio_mesa = self._mi_pila(estado)
        vivos = [j for j in jugadores if j.get("en_torneo", True)]
        pilas = [j.get("saldo", 0) + j.get("apuesta_ronda", 0) for j in vivos]
        if not self.modo_forzado:
            # La final: después de varias rondas en esta misma sesión, una mesa de
            # hasta 6 donde todos vuelven a empezar con la misma pila, distinta de
            # la que teníamos. Si reinicias el bot para la final, usa -modo final.
            iguales = len(pilas) >= 2 and len(set(pilas)) == 1
            mi_pila_antes = self.ultima_pila
            if (iguales and self.mesas >= 4 and len(pilas) <= 6
                    and mi_pila_antes is not None and mi_pila_antes != pilas[0]):
                self.modo = "final"
            elif self.modo != "final":
                self.modo = "clasificatoria"
        self.memoria.meta["mesas_jugadas"] = self.memoria.meta.get("mesas_jugadas", 0) + 1
        rivales = [j["id"] for j in vivos if j.get("id") != self.id_jugador]
        conocidos = [r for r in rivales if self.memoria.perfil(r).manos >= 8]
        etapa = "final" if self.modo == "final" else f"ronda {self.ronda()}"
        self.log(f"=== Nueva mesa {mesa} ({len(vivos)} jugadores, {etapa}). "
                 f"Rivales ya conocidos: {len(conocidos)}/{len(rivales)} ===")
        for r in conocidos:
            self.log(f"    {r}: {self.memoria.perfil(r).resumen()}")
        try:
            self.controlador.nueva_mesa(self._info(estado))
        except Exception:
            self.log("Error en el controlador (nueva mesa):\n" + traceback.format_exc(), consola=False)

    def _mi_pila(self, estado):
        yo = next((j for j in ((estado or {}).get("jugadores") or []) if j.get("id") == self.id_jugador), {})
        return yo.get("saldo", 0) + yo.get("apuesta_ronda", 0)

    def _info(self, estado, pila=None):
        jugadores = (estado or {}).get("jugadores") or []
        vivos = [j for j in jugadores if j.get("en_torneo", True)]
        return {
            "pila": self._mi_pila(estado) if pila is None else pila,
            "pila_previa": self.pila_previa if self.pila_previa is not None else 0,
            "pila_inicio_mesa": self.pila_inicio_mesa or self._mi_pila(estado) or 1,
            "mano_mesa": self.mano_mesa,
            "vivos": len(vivos),
            "rivales": [j["id"] for j in vivos if j.get("id") != self.id_jugador],
            "bb": (estado or {}).get("ciega_grande") or 100,
            "ronda": self.ronda(),
            "modo": self.modo,
        }

    def ronda(self):
        if self.ronda_inicial:
            return self.ronda_inicial + max(0, self.mesas - 1)
        return max(1, self.mesas)

    def _responder(self, s, msg):
        inicio = time.perf_counter()
        estado = msg.get("estado") or {}
        ctx = None
        try:
            info = self._info(estado)
            estilo = self.controlador.estilo(info)
            ctx = Contexto(msg, self.cartas, self.id_jugador, self.estado_inicio,
                           self.memoria, self.modo, estilo, self.mano_mesa, self.pila_inicio_mesa)
            especial = self.controlador.decidir(ctx)
            if especial:
                accion, razon = validar(ctx, especial[0]), especial[1]
            else:
                accion, razon = decidir(ctx)
            if self.controlador.actual != self.estilo:
                razon = f"[{self.controlador.actual}] {razon}"
        except Exception:  # nunca dejar de responder
            self.log("Error en la estrategia, juego seguro:\n" + traceback.format_exc())
            validas = msg.get("acciones_validas") or []
            accion = {"tipo": "check"} if "check" in validas else {"tipo": "fold"}
            razon = "error interno"
        self._enviar(s, {"tipo": "accion", "version": VERSION,
                         "id_mano": estado.get("id_mano"), "accion": accion})
        ms = (time.perf_counter() - inicio) * 1000
        monto = f" {accion['monto']}" if "monto" in accion else ""
        self.log(f"[{estado.get('id_mano')}] {estado.get('etapa')}: {razon} "
                 f"=> {accion['tipo'].upper()}{monto} ({ms:.0f} ms)")

    def _fin_de_mano(self, resultado):
        historial = (self.ultimo_estado or {}).get("historial_acciones")
        ganado = sum(r.get("monto", 0) for r in resultado.get("repartos", [])
                     if r.get("id_jugador") == self.id_jugador)
        yo = next((j for j in ((self.ultimo_estado or {}).get("jugadores") or [])
                   if j.get("id") == self.id_jugador), {})
        try:
            self.controlador.fin_mano(self._info(self.ultimo_estado, yo.get("saldo", 0) + ganado))
        except Exception:
            self.log("Error en el controlador (fin de mano):\n" + traceback.format_exc(), consola=False)
        try:
            self.memoria.aprender(self.id_jugador, self.estado_inicio, historial, resultado)
            self.memoria.guardar()
        except Exception:
            self.log("No pude actualizar la memoria:\n" + traceback.format_exc(), consola=False)
        extra = ""
        mostradas = resultado.get("mostradas") or {}
        if mostradas:
            extra = " | showdown: " + ", ".join(
                f"{pid} {legibles([desde_protocolo(c) for c in cs])}"
                for pid, cs in mostradas.items())
        self.ultima_pila = yo.get("saldo", 0) + ganado
        self.log(f"[{resultado.get('id_mano')}] fin: me llevo {ganado}, "
                 f"me quedan ~{yo.get('saldo', 0) + ganado}{extra}")


def correr(direccion, token, reconectar=True, **opciones):
    bot = Bot(direccion, token, **opciones)
    espera = 0.5
    while True:
        try:
            bot.jugar_una_conexion()
            bot.log("La mesa cerró la conexión (fin de partida, de sesión o del torneo).")
            espera = 0.5
            if not reconectar:
                return 0
        except ErrorDefinitivo as e:
            bot.log(f"La mesa rechazó la conexión: {e}")
            if "credencial" in str(e).lower() or "token" in str(e).lower():
                bot.log("Revisa tu token: cópialo completo, sin espacios.")
            return 1
        except KeyboardInterrupt:
            bot.log("Detenido a mano.")
            return 0
        except (OSError, ConnectionError, ValueError) as e:
            bot.log(f"Conexión perdida o rechazada: {e}")
            # Sin reconexión, igual damos unos segundos si la mesa aún no abrió.
            if not reconectar and (bot.id_jugador is not None or espera >= 4):
                return 1
        try:
            pausa = espera * (1 + random.random() * 0.5)
            bot.log(f"Reintentando en {pausa:.1f} s... (Ctrl+C para detener)")
            time.sleep(pausa)
            espera = min(espera * 2, 10)
        except KeyboardInterrupt:
            bot.log("Detenido a mano.")
            return 0
