"""
Almacenamiento de una sesión de medición. Se crean 4 archivos con el mismo prefijo:

  <id>_<fecha>_muestras.csv  cada muestra cruda (n, t_s, PPG crudo en cuentas, GSR en mV y µS, fase)
  <id>_<fecha>_latidos.csv   cada latido confirmado, con a-e, b/a, AI, validez y motivo de descarte
  <id>_<fecha>_ventanas.csv  resumen por ventana de 10 s (BPM, b/a, AI, SCL, SCR, calidad)
  <id>_<fecha>_meta.json     planilla del voluntario + snapshot de config.py + notas de cierre

Los archivos se abren UNA vez (antes se abría y cerraba el CSV en cada muestra,
lo que frenaba la adquisición) y se vuelcan a disco cada ~1 s.
Codificación UTF-8 con BOM (se abre bien en Excel; en pandas: encoding="utf-8-sig").
"""
import csv
import json
import math
import os
import re
import time
from datetime import datetime

import config

COL_MUESTRAS = ["n", "t_s", "t_pc", "fase", "ppg_raw", "gsr_mV", "gsr_uS"]
COL_LATIDOS = ["n_pico", "t_s", "fase", "valido", "motivo", "rr_s",
               "a", "b", "c", "d", "e", "ba", "ai"]
COL_VENTANAS = ["n_fin", "t_fin_s", "fase", "dedo_ok", "contacto_ok", "n_latidos", "n_validos",
                "bpm", "ba_med", "ai_med", "ba_iqr", "ai_iqr", "scl_uS", "scr_n", "scr_amp_uS", "perdidas"]

_RE_ID = re.compile(r"^[A-Za-z0-9_-]{2,20}$")


def id_valido(id_sujeto):
    """Códigos tipo 'V01', 'S-12'. No usar nombres ni DNI: es un código seudonimizado."""
    return bool(_RE_ID.match(id_sujeto or ""))


def _f(x):
    """Formatea un número para CSV; NaN/None -> vacío (pandas lo lee como NaN)."""
    if x is None:
        return ""
    if isinstance(x, float):
        return "" if not math.isfinite(x) else f"{x:.6g}"
    return x


def snapshot_config():
    return {k: v for k, v in vars(config).items()
            if k.isupper() and isinstance(v, (int, float, str, bool, list, tuple, type(None)))}


class GestorSesion:
    def __init__(self, id_sujeto, planilla=None, carpeta="registros_csv"):
        if not id_valido(id_sujeto):
            raise ValueError("Código de sujeto inválido (2-20 caracteres: letras, números, '_' o '-').")
        os.makedirs(carpeta, exist_ok=True)
        self.base = os.path.join(carpeta, f"{id_sujeto}_{datetime.now():%Y-%m-%d_%H-%M-%S}")
        self._archivos = {}
        self._writers = {}
        for sufijo, cols in (("muestras", COL_MUESTRAS), ("latidos", COL_LATIDOS), ("ventanas", COL_VENTANAS)):
            f = open(f"{self.base}_{sufijo}.csv", "w", newline="", encoding="utf-8-sig")
            w = csv.writer(f)
            w.writerow(cols)
            self._archivos[sufijo], self._writers[sufijo] = f, w
        self._meta = dict(version_formato=2, id_sujeto=id_sujeto, inicio=datetime.now().isoformat(timespec="seconds"),
                          planilla=planilla or {}, config=snapshot_config(), cierre={})
        self._escribir_meta()
        self._ult_flush = time.monotonic()

    # ------------------------------------------------------------------
    def guardar_muestra(self, n, fs, fase, ppg_raw, gsr_mV, gsr_uS):
        self._writers["muestras"].writerow([n, f"{n / fs:.4f}", f"{time.time():.3f}", fase,
                                            ppg_raw, gsr_mV, _f(float(gsr_uS))])
        self._flush_si_corresponde()

    def guardar_ventana(self, res):
        self._writers["ventanas"].writerow([_f(res.get(c)) for c in COL_VENTANAS])

    def guardar_latidos(self, latidos):
        for l in latidos:
            self._writers["latidos"].writerow([_f(l.get(c)) for c in COL_LATIDOS])

    # ------------------------------------------------------------------
    def _flush_si_corresponde(self):
        if time.monotonic() - self._ult_flush >= 1.0:
            for f in self._archivos.values():
                f.flush()
            self._ult_flush = time.monotonic()

    def _escribir_meta(self):
        with open(f"{self.base}_meta.json", "w", encoding="utf-8") as f:
            json.dump(self._meta, f, ensure_ascii=False, indent=2)

    def cerrar(self, notas_cierre=None):
        """Cierra los archivos y registra datos de cierre (fin, pérdidas, AI basal, etc.)."""
        for f in self._archivos.values():
            f.flush()
            f.close()
        cierre = dict(fin=datetime.now().isoformat(timespec="seconds"))
        cierre.update(notas_cierre or {})
        self._meta["cierre"] = cierre
        self._escribir_meta()
