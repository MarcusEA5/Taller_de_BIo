"""
Procesador de flujo (sin Qt ni puerto serie, por eso es testeable offline).

Recibe muestras de a una (`agregar`) y, cada PASO_S segundos, procesa la última
ventana de VENTANA_S segundos. Devuelve un diccionario con:

  * resumen de la ventana (BPM, b/a, AI, SCL, SCR, calidad, fase);
  * las señales a graficar;
  * `latidos_confirmados`: solo los latidos de la mitad central de la ventana,
    de modo que cada latido se informa UNA sola vez (sin duplicados por el
    solapamiento del 50 %) y los bordes del filtrado quedan como contexto.

Si se detecta un salto en el contador de muestras (pérdida de datos) se
descarta la ventana en curso: derivar dos veces una señal con un hueco
produce picos espurios.
"""
from collections import deque

import numpy as np

import config
import procesamiento_gsr
import procesamiento_ppg as ppg


class ProcesadorStream:
    def __init__(self, fs=config.FS):
        self.fs = fs
        self.W = int(round(config.VENTANA_S * fs))
        self.paso = int(round(config.PASO_S * fs))
        self.perdidas = 0               # muestras perdidas detectadas por salto del contador
        self.reiniciar()

    def reiniciar(self):
        self._n = deque(maxlen=self.W)
        self._ppg = deque(maxlen=self.W)
        self._mv = deque(maxlen=self.W)
        self._fase = deque(maxlen=self.W)
        self._desde_ultima = 0
        self._n_esperado = None

    # ------------------------------------------------------------------
    def agregar(self, n, ppg_raw, gsr_mV, fase):
        """Agrega una muestra. Devuelve el resultado de la ventana si corresponde, si no None."""
        if self._n_esperado is not None and n != self._n_esperado:
            self.perdidas += max(n - self._n_esperado, 0)
            n_perd = self.perdidas
            self.reiniciar()
            self.perdidas = n_perd
        self._n_esperado = n + 1

        self._n.append(n)
        self._ppg.append(ppg_raw)
        self._mv.append(gsr_mV)
        self._fase.append(fase)
        self._desde_ultima += 1

        if len(self._ppg) == self.W and self._desde_ultima >= self.paso:
            self._desde_ultima = 0
            return self._procesar_ventana()
        return None

    # ------------------------------------------------------------------
    def _procesar_ventana(self):
        fs = self.fs
        raw = np.fromiter(self._ppg, dtype=float, count=len(self._ppg))
        mv = np.fromiter(self._mv, dtype=float, count=len(self._mv))
        fases = list(self._fase)
        n0 = self._n[0]

        fase_ventana = fases[0] if len(set(fases)) == 1 else config.FASE_TRANSICION
        dedo_ok = bool(np.median(raw) >= config.UMBRAL_DEDO_CUENTAS
                       and raw.max() < config.SATURACION_CUENTAS)

        res = dict(n_fin=int(self._n[-1]), t_fin_s=self._n[-1] / fs, fase=fase_ventana,
                   dedo_ok=dedo_ok, perdidas=self.perdidas, latidos_confirmados=[],
                   ppg_f=None, sdppg=None, puntos=([], [], []))

        # --- GSR --------------------------------------------------------
        g_uS = procesamiento_gsr.mV_a_uS(mv)
        res.update(procesamiento_gsr.analizar_ventana(g_uS, fs))

        # --- PPG --------------------------------------------------------
        res.update(n_latidos=0, n_validos=0, bpm=float("nan"), resumen_ok=False,
                   ba_med=float("nan"), ai_med=float("nan"), ba_iqr=float("nan"), ai_iqr=float("nan"))
        if not dedo_ok:
            return res

        xf = ppg.filtrar_ppg(ppg.invertir(raw), fs)
        sd = ppg.segunda_derivada(xf, fs)
        latidos = ppg.analizar_latidos(xf, sd, fs)
        res.update(ppg.resumir(latidos))
        res.update(ppg_f=xf, sdppg=sd, puntos=ppg.puntos_para_grafico(latidos, sd, fs))

        # --- Confirmación de latidos (mitad central de la ventana) -----------
        lo, hi = self.W / 4.0, 3.0 * self.W / 4.0
        for l in latidos:
            if lo <= l.idx_pico < hi:
                res["latidos_confirmados"].append(dict(
                    n_pico=int(n0 + l.idx_pico), t_s=(n0 + l.idx_pico) / fs,
                    fase=fases[l.idx_pico], valido=l.valido, motivo=l.motivo,
                    rr_s=l.rr_s, a=l.a, b=l.b, c=l.c, d=l.d, e=l.e, ba=l.ba, ai=l.ai))
        return res
