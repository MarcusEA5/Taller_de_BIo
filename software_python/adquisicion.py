"""
Adquisición desde el ESP32-C3.

Protocolo (una línea de texto por muestra, generada en firmware/src/main.cpp):

    n,t_us,ppg_ir,gsr_mV*HH
      n       contador de muestras (0,1,2,...) -> el tiempo real es n / FS
      t_us    micros() del ESP32 desde el inicio (solo para verificar la fs)
      ppg_ir  cuentas crudas del canal IR del MAX30102
      gsr_mV  tensión del pin del ADC en mV (calibrada)
      HH      checksum XOR de los caracteres anteriores, en hexadecimal

Las líneas que empiezan con '#' son informativas (p. ej. "# fs=200").

La lectura serie corre en un hilo separado y deja los datos en una cola, de modo
que un redibujado lento de la interfaz ya no frena la adquisición.
"""
import queue
import re
import threading
import time

import config

_RE_DATO = re.compile(r"^\d+,\d+,\d+,\d+$")


def parsear_linea(texto):
    """Interpreta una línea del ESP32.

    Devuelve:
      ("dato", n, t_us, ppg, mV)   muestra válida
      ("info", texto)              línea informativa ('# ...')
      None                         línea corrupta o incompleta (se descarta)
    """
    texto = texto.strip()
    if not texto:
        return None
    if texto.startswith("#"):
        return ("info", texto.lstrip("# ").strip())
    if "*" not in texto:
        return None
    cuerpo, _, chk = texto.rpartition("*")
    try:
        esperado = int(chk, 16)
    except ValueError:
        return None
    calc = 0
    for ch in cuerpo:
        calc ^= ord(ch)
    if calc != esperado or not _RE_DATO.match(cuerpo):
        return None
    n, t_us, ppg, mv = (int(v) for v in cuerpo.split(","))
    return ("dato", n, t_us, ppg, mv)


def encontrar_puerto():
    """Puerto configurado o, si es None, el primer dispositivo Espressif (ESP32-C3) conectado."""
    if config.PUERTO:
        return config.PUERTO
    from serial.tools import list_ports
    for p in list_ports.comports():
        if p.vid == config.VID_ESPRESSIF:
            return p.device
    raise RuntimeError("No se encontró el ESP32-C3. Conectalo o fijá config.PUERTO (p. ej. 'COM7').")


class ControlTiempo:
    """Compara el contador de muestras con el reloj del ESP32 para detectar pérdidas o fs incorrecta."""

    def __init__(self, fs=config.FS):
        self.fs = fs
        self.n0 = self.t0 = None
        self.n_ult = self.t_ult = 0
        self._t_prev = None
        self._t_wraps = 0
        self.fs_declarada = None

    def actualizar(self, n, t_us):
        if self._t_prev is not None and t_us < self._t_prev:     # micros() es de 32 bits (~71 min)
            self._t_wraps += 1
        self._t_prev = t_us
        t = t_us + self._t_wraps * (1 << 32)
        if self.n0 is None:
            self.n0, self.t0 = n, t
        self.n_ult, self.t_ult = n, t

    def fs_medida(self):
        """fs efectiva (muestras/seg del reloj del ESP32). None hasta tener >= 2 s de datos."""
        if self.n0 is None or (self.t_ult - self.t0) < 2e6:
            return None
        return (self.n_ult - self.n0) / ((self.t_ult - self.t0) / 1e6)

    def estado(self):
        """(ok: bool, texto: str) para mostrar en la interfaz."""
        if self.fs_declarada is not None and abs(self.fs_declarada - self.fs) > 1e-6:
            return False, f"Firmware a {self.fs_declarada:g} Hz pero config.FS = {self.fs:g} Hz"
        fm = self.fs_medida()
        if fm is None:
            return True, "Adquiriendo..."
        desvio = abs(fm - self.fs) / self.fs
        if desvio > config.TOLERANCIA_FS:
            return False, f"fs medida {fm:.1f} Hz (esperada {self.fs:g}): posible pérdida de muestras"
        return True, f"fs = {fm:.1f} Hz"


class LectorSerie(threading.Thread):
    """Hilo lector. Pone en `cola` tuplas ("dato", ...), ("info", txt) o ("error", txt)."""

    def __init__(self, cola, puerto=None):
        super().__init__(daemon=True)
        self.cola = cola
        self.puerto = puerto
        self._parar = threading.Event()

    def detener(self):
        self._parar.set()

    def run(self):
        try:
            import serial
            puerto = self.puerto or encontrar_puerto()
            with serial.Serial(puerto, config.BAUDRATE, timeout=0.1) as ser:
                ser.reset_input_buffer()
                self.cola.put(("info", f"Conectado a {puerto}"))
                resto = b""
                while not self._parar.is_set():
                    bloque = ser.read(max(1, ser.in_waiting))
                    if not bloque:
                        continue
                    resto += bloque
                    lineas = resto.split(b"\n")
                    resto = lineas.pop()                  # última línea, posiblemente incompleta
                    for crudo in lineas:
                        item = parsear_linea(crudo.decode("utf-8", errors="ignore"))
                        if item is not None:
                            self.cola.put(item)
        except Exception as exc:                          # puerto ocupado, desconexión, etc.
            self.cola.put(("error", f"Adquisición detenida: {exc}"))
            time.sleep(0.1)
