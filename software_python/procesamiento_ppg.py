"""
Procesamiento de la señal PPG: filtrado, segunda derivada (SDPPG) y extracción
de los puntos fiduciarios a, b, c, d, e latido a latido.

Cadena de procesamiento (todo offline/en la PC, ventana de VENTANA_S segundos):

  1. PPG crudo (cuentas IR, el sensor da MENOS luz con MÁS sangre) -> se invierte.
  2. Pasa-banda Butterworth de fase cero (filtfilt), 0,5-15 Hz.
  3. Segunda derivada con Savitzky-Golay (suaviza y deriva en un solo paso,
     en vez de aplicar dos diferencias finitas que amplifican el ruido).
  4. Detección de picos sistólicos en el PPG filtrado (1 por latido).
  5. Por cada latido, búsqueda de a, b, c, d, e en la SDPPG con ventanas
     temporales fisiológicas y prominencia mínima relativa a la onda 'a'.
  6. Validación del latido (orden, amplitudes, RR, b/a plausible).

Convención:  b/a es NEGATIVO.  AI = (b - c - d - e) / a  (Takazawa et al., 1998).
"""
from dataclasses import dataclass

import numpy as np
from scipy.signal import butter, correlate, filtfilt, find_peaks, savgol_filter

import config

NAN = float("nan")


# ----------------------------------------------------------------------------
# Filtrado y derivada
# ----------------------------------------------------------------------------
def _impar(n):
    n = int(round(n))
    return n if n % 2 == 1 else n + 1


def invertir(ppg_raw):
    """El MAX30102 devuelve menos cuentas cuando hay más sangre: se invierte la polaridad."""
    return -np.asarray(ppg_raw, dtype=float)


def filtrar_ppg(x, fs=config.FS):
    """Pasa-banda Butterworth de fase cero (no introduce desfase en los puntos fiduciarios)."""
    nyq = 0.5 * fs
    lo, hi = config.BANDA_PPG_HZ
    b, a = butter(config.ORDEN_BUTTER, [lo / nyq, hi / nyq], btype="band")
    return filtfilt(b, a, np.asarray(x, dtype=float))


def segunda_derivada(xf, fs=config.FS):
    """SDPPG por Savitzky-Golay (unidades: cuentas/s²; las razones entre ondas no dependen de la escala)."""
    ventana = _impar(config.SG_VENTANA_MS / 1000.0 * fs)
    return savgol_filter(xf, ventana, config.SG_ORDEN, deriv=2, delta=1.0 / fs)


def primera_derivada(xf, fs=config.FS):
    """Velocidad del PPG (VPG) por Savitzky-Golay; se usa solo para localizar la subida del pulso."""
    ventana = _impar(config.SG_VENTANA_MS / 1000.0 * fs)
    return savgol_filter(xf, ventana, config.SG_ORDEN, deriv=1, delta=1.0 / fs)


# ----------------------------------------------------------------------------
# Detección de latidos
# ----------------------------------------------------------------------------
@dataclass
class Latido:
    idx_pico: int                 # índice del pico sistólico en la ventana
    rr_s: float = NAN             # intervalo desde el pico anterior
    idx_a: int = -1
    idx_b: int = -1
    idx_c: int = -1
    idx_d: int = -1
    idx_e: int = -1
    a: float = NAN
    b: float = NAN
    c: float = NAN
    d: float = NAN
    e: float = NAN
    ba: float = NAN
    ai: float = NAN
    valido: bool = False
    motivo: str = "sin_medir"     # "" si es válido; si no, la causa del descarte


def periodo_dominante(xf, fs=config.FS):
    """Período cardíaco [s] por autocorrelación, o None si la señal no es periódica.

    Sirve para fijar la separación mínima entre picos: cuando la onda diastólica es
    casi tan alta como la sistólica (típico en arterias rígidas) un detector basado
    solo en prominencia contaría dos latidos por ciclo.
    """
    x = np.asarray(xf, dtype=float) - np.mean(xf)
    if len(x) < int(2 * config.RR_MAX_S * fs) or np.std(x) == 0:
        return None
    ac = correlate(x, x, mode="full", method="fft")[len(x) - 1:]
    ac = ac / ac[0]
    lo, hi = int(config.RR_MIN_S * fs), int(config.RR_MAX_S * fs)
    lag = lo + int(np.argmax(ac[lo:hi]))
    return lag / fs if ac[lag] >= config.AUTOCORR_MIN else None


def detectar_picos_sistolicos(xf, fs=config.FS):
    """Picos sistólicos del PPG filtrado (descarta picos diastólicos/ruido)."""
    if len(xf) < 3:
        return np.array([], dtype=int)
    distancia = config.PICO_DISTANCIA_MIN_S
    T0 = periodo_dominante(xf, fs)
    if T0 is not None:
        distancia = max(distancia, config.PICO_DISTANCIA_REL_T0 * T0)
    p, props = find_peaks(xf, distance=int(distancia * fs), prominence=0.1 * np.std(xf))
    if len(p) == 0:
        return p
    prom = props["prominences"]
    return p[prom >= config.PICO_PROMINENCIA_REL * np.median(prom)]


def _buscar_a(vel, sd, inicio, k, fs):
    """Índice de la onda 'a': máximo de aceleración justo antes de la máxima velocidad de subida.

    Se ancla a la UPSTROKE (entre el pie del pulso y el pico sistólico) y no a una distancia
    fija antes del pico, porque la posición del pico respecto de 'a' varía con la rigidez
    arterial y con la forma del pulso.
    """
    if k <= inicio + 2:
        return -1
    iv = inicio + int(np.argmax(vel[inicio:k + 1]))              # máxima velocidad de ascenso
    desde = max(inicio, iv - int(config.A_ANTES_DE_VMAX_S * fs))
    return desde + int(np.argmax(sd[desde:iv + 1]))


def _medir_fiduciarios(l, sd, fs, ia):
    """Completa b-e del latido `l` a partir de la SDPPG `sd` y de la onda 'a' ya localizada (`ia`).

    Deja la causa en `l.motivo` si el latido no se puede medir.
    """
    if ia < 0:
        l.motivo = "sin_a"
        return
    A = sd[ia]
    if A <= 0:
        l.motivo = "sin_a"
        return
    fin = ia + int(config.SEGMENTO_MAX_S * fs)
    if fin > len(sd):
        l.motivo = "borde"
        return

    seg = sd[ia:fin]
    umbral = config.PROMINENCIA_ONDAS_REL * A
    maximos, _ = find_peaks(seg, prominence=umbral)
    minimos, _ = find_peaks(-seg, prominence=umbral)

    cand_b = [m for m in minimos if 0 < m <= int(config.B_MAX_DESDE_A_S * fs)]
    if not cand_b:
        l.motivo = "sin_b"
        return
    ib = min(cand_b, key=lambda m: seg[m])            # el mínimo más profundo tras 'a'

    cand_c = [m for m in maximos if ib < m <= ib + int(config.C_MAX_DESDE_B_S * fs)]
    if not cand_c:
        l.motivo = "sin_c"
        return
    ic = cand_c[0]

    cand_d = [m for m in minimos if ic < m <= ic + int(config.D_MAX_DESDE_C_S * fs)]
    if not cand_d:
        l.motivo = "sin_d"
        return
    id_ = cand_d[0]

    cand_e = [m for m in maximos if id_ < m <= id_ + int(config.E_MAX_DESDE_D_S * fs)]
    if not cand_e:
        l.motivo = "sin_e"
        return
    ie = cand_e[0]

    l.idx_a, l.idx_b, l.idx_c, l.idx_d, l.idx_e = (ia, ia + ib, ia + ic, ia + id_, ia + ie)
    l.a, l.b, l.c, l.d, l.e = A, seg[ib], seg[ic], seg[id_], seg[ie]
    l.ba = l.b / l.a
    l.ai = (l.b - l.c - l.d - l.e) / l.a
    l.motivo = ""                                       # medido; falta validar


def _validar(latidos):
    """Marca como válidos solo los latidos fisiológicamente coherentes con el resto de la ventana."""
    medidos = [l for l in latidos if l.motivo == ""]
    if not medidos:
        return
    a_med = np.median([l.a for l in medidos])
    rr_ok = [l.rr_s for l in latidos if np.isfinite(l.rr_s)
             and config.RR_MIN_S <= l.rr_s <= config.RR_MAX_S]
    rr_med = float(np.median(rr_ok)) if rr_ok else NAN

    for l in medidos:
        if not (config.BA_RANGO[0] <= l.ba <= config.BA_RANGO[1]):
            l.motivo = "ba_fuera_de_rango"
        elif not (config.AMP_A_RANGO[0] * a_med <= l.a <= config.AMP_A_RANGO[1] * a_med):
            l.motivo = "amplitud_a"
        elif np.isfinite(l.rr_s) and np.isfinite(rr_med) and \
                abs(l.rr_s - rr_med) > config.RR_TOLERANCIA * rr_med:
            l.motivo = "rr_irregular"
        else:
            l.valido = True


def _aplicar_sqi(xf, latidos, fs):
    """Índice de calidad por forma de onda: correlación de cada latido con la plantilla mediana.

    Un latido real se parece a sus vecinos (correlación ~0,95+). El ruido, un
    movimiento del dedo o un pulso mal apoyado no. Los latidos que no superan
    SQI_CORR_MIN dejan de ser válidos aunque tengan a-e "detectables".
    """
    pre, post = int(0.25 * fs), int(0.55 * fs)
    cand = [l for l in latidos if l.valido and l.idx_pico - pre >= 0 and l.idx_pico + post <= len(xf)]
    if len(cand) < 3:
        return
    segs = np.array([xf[l.idx_pico - pre:l.idx_pico + post] for l in cand])
    z = (segs - segs.mean(1, keepdims=True)) / (segs.std(1, keepdims=True) + 1e-12)
    plantilla = np.median(z, axis=0)
    plantilla = (plantilla - plantilla.mean()) / (plantilla.std() + 1e-12)
    corr = (z * plantilla).mean(1)
    for l, c in zip(cand, corr):
        if c < config.SQI_CORR_MIN:
            l.valido = False
            l.motivo = "forma_anomala"


def analizar_latidos(xf, sd, fs=config.FS):
    """Devuelve la lista de `Latido` (válidos o no, con su motivo de descarte)."""
    picos = detectar_picos_sistolicos(xf, fs)
    vel = primera_derivada(xf, fs)
    latidos = []
    for i, k in enumerate(picos):
        l = Latido(idx_pico=int(k))
        if i > 0:
            l.rr_s = (k - picos[i - 1]) / fs
            inicio_busqueda = int(picos[i - 1])
        else:
            inicio_busqueda = max(0, int(k) - int(config.A_BUSQUEDA_PREVIA_S * 2 * fs))
        if inicio_busqueda >= k:
            l.motivo = "borde"
            latidos.append(l)
            continue
        pie = inicio_busqueda + int(np.argmin(xf[inicio_busqueda:k + 1]))   # pie del pulso
        if i == 0 and pie - 1 <= 0:
            l.motivo = "borde"                                              # ventana cortó el latido
        else:
            _medir_fiduciarios(l, sd, fs, _buscar_a(vel, sd, pie, int(k), fs))
        latidos.append(l)
    _validar(latidos)
    _aplicar_sqi(xf, latidos, fs)
    return latidos


def resumir(latidos):
    """Resumen robusto (medianas) de una ventana. `resumen_ok` indica si es confiable."""
    n_det = len(latidos)
    validos = [l for l in latidos if l.valido]
    rr = [l.rr_s for l in latidos if np.isfinite(l.rr_s)
          and config.RR_MIN_S <= l.rr_s <= config.RR_MAX_S]
    bpm = 60.0 / float(np.median(rr)) if rr else NAN
    out = dict(n_latidos=n_det, n_validos=len(validos), bpm=bpm, resumen_ok=False,
               ba_med=NAN, ai_med=NAN, ba_iqr=NAN, ai_iqr=NAN)
    if len(validos) < config.MIN_LATIDOS_VALIDOS or len(validos) < config.FRACCION_MIN_VALIDOS * n_det:
        return out
    ba = np.array([l.ba for l in validos])
    ai = np.array([l.ai for l in validos])
    out.update(resumen_ok=True,
               ba_med=float(np.median(ba)), ai_med=float(np.median(ai)),
               ba_iqr=float(np.subtract(*np.percentile(ba, [75, 25]))),
               ai_iqr=float(np.subtract(*np.percentile(ai, [75, 25]))))
    return out


# ----------------------------------------------------------------------------
# Ayuda para graficar
# ----------------------------------------------------------------------------
COLORES_ONDAS = ("b", "r", "g", "y", "m")        # a, b, c, d, e (igual que la interfaz original)


def puntos_para_grafico(latidos, sd, fs=config.FS):
    """Coordenadas (tiempo [s], amplitud, color) de los puntos fiduciarios de los latidos válidos."""
    xs, ys, cs = [], [], []
    for l in latidos:
        if not l.valido:
            continue
        for idx, col in zip((l.idx_a, l.idx_b, l.idx_c, l.idx_d, l.idx_e), COLORES_ONDAS):
            xs.append(idx / fs)
            ys.append(float(sd[idx]))
            cs.append(col)
    return xs, ys, cs
