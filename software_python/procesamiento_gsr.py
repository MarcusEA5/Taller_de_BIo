"""
Procesamiento de la señal GSR/EDA.

El firmware envía la tensión del pin del ADC en milivoltios (ya calibrada por el
ADC del ESP32-C3 con `analogReadMilliVolts`). Acá se la convierte a
conductancia (µS) usando los parámetros del circuito de config.py.

La señal cruda en mV se guarda siempre en el CSV, así que si más adelante se
corrigen los valores del circuito (R1, VEXC, divisor) la conductancia se puede
recalcular sin repetir las mediciones.
"""
import numpy as np
from scipy.signal import butter, filtfilt, find_peaks

import config


def mV_a_uS(mV):
    """Convierte la tensión del ADC [mV] a conductancia de la piel [µS].

    Devuelve NaN donde la tensión está fuera del rango físico (0 < V < VEXC),
    por ejemplo si los electrodos están desconectados (V ≈ 0) o en corto.
    """
    v = np.asarray(mV, dtype=float) / 1000.0 * config.GSR_K_DIV   # tensión en el nodo
    r1, vex = config.GSR_R1_OHM, config.GSR_VEXC_V
    with np.errstate(divide="ignore", invalid="ignore"):
        g = v / (r1 * (vex - v)) * 1e6
    g = np.where((v > 0) & (v < vex), g, np.nan)
    return g if g.ndim else float(g)


def uS_a_mV(g_uS):
    """Inversa de mV_a_uS. Útil para calibrar con resistencias patrón."""
    g = np.asarray(g_uS, dtype=float) * 1e-6
    r1, vex = config.GSR_R1_OHM, config.GSR_VEXC_V
    v_nodo = vex * (g * r1) / (1.0 + g * r1)
    return v_nodo / config.GSR_K_DIV * 1000.0


def corriente_piel_uA(mV):
    """Corriente continua que circula por la piel [µA] (para verificar el límite de 10 µA)."""
    v = np.asarray(mV, dtype=float) / 1000.0 * config.GSR_K_DIV
    return v / config.GSR_R1_OHM * 1e6


def analizar_ventana(g_uS, fs=config.FS):
    """Extrae SCL y actividad fásica (SCR) de una ventana de conductancia.

    Devuelve un dict:
      contacto_ok : bool   (suficientes muestras válidas)
      scl_uS      : float  mediana de la señal suavizada (nivel tónico)
      scr_n       : int    cantidad de picos fásicos (prominencia >= SCR_PROMINENCIA_uS)
      scr_amp_uS  : float  mayor prominencia de la ventana
    Nota: para el análisis final conviene reprocesar la señal cruda completa con una
    descomposición tónico/fásica propia (p. ej. cvxEDA); esto es una estimación rápida.
    """
    g = np.asarray(g_uS, dtype=float)
    valido = np.isfinite(g)
    if g.size == 0 or valido.mean() < config.GSR_CONTACTO_MIN:
        return dict(contacto_ok=False, scl_uS=float("nan"), scr_n=0, scr_amp_uS=float("nan"))

    if not valido.all():                       # rellenar huecos aislados por interpolación
        idx = np.arange(g.size)
        g = np.interp(idx, idx[valido], g[valido])

    b, a = butter(2, 1.0 / (0.5 * fs), btype="low")
    lp = filtfilt(b, a, g)
    picos, props = find_peaks(lp, prominence=config.SCR_PROMINENCIA_uS)
    amp = float(props["prominences"].max()) if len(picos) else 0.0
    return dict(contacto_ok=True, scl_uS=float(np.median(lp)), scr_n=int(len(picos)), scr_amp_uS=amp)
