"""
Análisis offline de las sesiones grabadas.

Uso:
    python analisis_offline.py registros_csv/V01_..._muestras.csv       # resumen de una sesión
    python analisis_offline.py registros_csv/viejo.csv --legacy         # CSV del formato anterior
    python analisis_offline.py --grupo registros_csv                    # estadística de grupo

Reprocesa las muestras CRUDAS con el mismo pipeline que la interfaz en vivo
(pipeline.ProcesadorStream), así que se puede repetir el análisis con parámetros nuevos
(config.py) sin volver a medir. La señal GSR en mV también permite recalcular µS si se
corrigen los valores del circuito.

POR QUÉ LA ESTADÍSTICA SE HACE POR SUJETO
Las ventanas de 10 s se solapan y los latidos de un mismo sujeto no son independientes.
Tratarlos como observaciones independientes infla la significancia (pseudo-replicación).
Por eso cada sujeto se resume en UN valor por fase (mediana de sus latidos válidos) y los
tests (t pareada / Wilcoxon, correlación) se hacen sobre esos valores: n = cantidad de sujetos.
"""
import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd

import config
import procesamiento_gsr
from pipeline import ProcesadorStream

COL_VENTANAS = ["n_fin", "t_fin_s", "fase", "dedo_ok", "contacto_ok", "n_latidos", "n_validos",
                "bpm", "ba_med", "ai_med", "scl_uS", "scr_n", "scr_amp_uS", "perdidas"]


# ----------------------------------------------------------------------------
# Lectura
# ----------------------------------------------------------------------------
def cargar_muestras(ruta, legacy=False):
    """DataFrame con columnas n, fase, ppg_raw, gsr_mV."""
    if legacy:
        return _cargar_legacy(ruta)
    df = pd.read_csv(ruta, encoding="utf-8-sig")
    return df[["n", "fase", "ppg_raw", "gsr_mV"]]


def _cargar_legacy(ruta):
    """Formato anterior (Timestamp, Fase, PPG_Crudo ya invertido, ..., GSR en cuentas del ADC).

    ADVERTENCIA: no tiene contador de muestras (se usa el índice) y el GSR está en cuentas;
    se lo pasa a mV suponiendo el fondo de escala de ~2,5 V de ADC_11db. Sirve para comparar
    el algoritmo, no para mediciones definitivas.
    """
    filas = []
    with open(ruta, encoding="cp1252", errors="replace") as f:
        for linea in f:
            partes = linea.rstrip("\r\n").split(",")
            if len(partes) >= 5 and not linea.startswith("#") and partes[0] != "Timestamp":
                try:
                    filas.append((partes[1], float(partes[2]), float(partes[4])))
                except ValueError:
                    continue
    df = pd.DataFrame(filas, columns=["fase", "ppg_inv", "gsr_cuentas"])
    return pd.DataFrame(dict(n=np.arange(len(df)), fase=df["fase"], ppg_raw=-df["ppg_inv"],
                             gsr_mV=df["gsr_cuentas"] * 2500.0 / 4095.0))


# ----------------------------------------------------------------------------
# Reprocesado
# ----------------------------------------------------------------------------
def reprocesar(df, fs=config.FS):
    """Pasa las muestras por el pipeline. Devuelve (df_ventanas, df_latidos)."""
    proc = ProcesadorStream(fs)
    ventanas, latidos = [], []
    for n, fase, ppg, mv in zip(df["n"].to_numpy(), df["fase"].to_numpy(),
                                df["ppg_raw"].to_numpy(), df["gsr_mV"].to_numpy()):
        res = proc.agregar(int(n), float(ppg), float(mv), fase)
        if res is not None:
            ventanas.append({c: res.get(c) for c in COL_VENTANAS})
            latidos.extend(res["latidos_confirmados"])
    return pd.DataFrame(ventanas), pd.DataFrame(latidos)


def resumen_por_fase(df_ventanas, df_latidos):
    """Un renglón por fase con medianas robustas. Las ventanas de transición se excluyen."""
    filas = []
    ventanas = df_ventanas[df_ventanas["fase"] != config.FASE_TRANSICION]
    for fase, lat in df_latidos.groupby("fase"):
        if fase in (config.FASE_INACTIVA, config.FASE_TRANSICION):
            continue
        val = lat[lat["valido"]]
        vent = ventanas[ventanas["fase"] == fase]
        rr = lat["rr_s"].dropna()
        rr = rr[(rr >= config.RR_MIN_S) & (rr <= config.RR_MAX_S)]
        filas.append(dict(
            fase=fase, n_latidos=len(lat), n_validos=len(val),
            pct_validos=100.0 * len(val) / max(len(lat), 1),
            bpm=60.0 / rr.median() if len(rr) else np.nan,
            ba_mediana=val["ba"].median(), ba_sd=val["ba"].std(),
            ai_mediana=val["ai"].median(), ai_sd=val["ai"].std(),
            scl_uS=vent["scl_uS"].median(), scr_por_min=vent["scr_n"].median() * 60.0 / config.VENTANA_S,
            scr_amp_uS=vent["scr_amp_uS"].median()))
    return pd.DataFrame(filas).set_index("fase")


# ----------------------------------------------------------------------------
# Estadística de grupo
# ----------------------------------------------------------------------------
def _holm(pvals):
    """Corrección de Holm-Bonferroni (controla el error de tipo I con varias pruebas)."""
    p = np.asarray(pvals, dtype=float)
    orden = np.argsort(p)
    ajust = np.empty_like(p)
    previo = 0.0
    for rango, i in enumerate(orden):
        previo = max(previo, (len(p) - rango) * p[i])
        ajust[i] = min(previo, 1.0)
    return ajust


def estadistica_grupo(resumenes, variable="ba_mediana", fases_estres=None):
    """Compara cada fase de estrés contra el basal (pareado por sujeto) y correlaciona con el GSR.

    resumenes: dict {id_sujeto: DataFrame de resumen_por_fase}
    """
    from scipy import stats
    fases_estres = fases_estres or [config.PROTOCOLO[1][0], config.PROTOCOLO[3][0]]
    basal = config.FASE_BASAL
    filas = []
    for fase in fases_estres:
        pares = [(r.loc[basal, variable], r.loc[fase, variable],
                  r.loc[basal, "scl_uS"], r.loc[fase, "scl_uS"])
                 for r in resumenes.values() if basal in r.index and fase in r.index]
        pares = [p for p in pares if np.all(np.isfinite(p))]
        n = len(pares)
        if n < 3:
            filas.append(dict(fase=fase, n=n, nota="menos de 3 sujetos con datos completos"))
            continue
        b, f, sb, sf = (np.array(c) for c in zip(*pares))
        d = f - b
        t, p_t = stats.ttest_rel(f, b)
        p_w = stats.wilcoxon(d).pvalue if n >= 6 and np.any(d != 0) else np.nan
        p_norm = stats.shapiro(d).pvalue if n >= 3 and np.ptp(d) > 0 else np.nan
        fila = dict(fase=fase, n=n, **{f"{variable}_basal": b.mean(), f"{variable}_fase": f.mean()},
                    delta_medio=d.mean(), dz_cohen=d.mean() / d.std(ddof=1) if d.std(ddof=1) > 0 else np.nan,
                    p_t_pareada=p_t, p_wilcoxon=p_w, p_shapiro_dif=p_norm)
        dscl = sf - sb
        if np.ptp(dscl) > 0 and np.ptp(d) > 0:
            fila.update(r_pearson_dSCL_dVar=stats.pearsonr(dscl, d)[0], p_pearson=stats.pearsonr(dscl, d)[1],
                        rho_spearman=stats.spearmanr(dscl, d)[0], p_spearman=stats.spearmanr(dscl, d)[1])
        filas.append(fila)
    tabla = pd.DataFrame(filas).set_index("fase")
    if "p_t_pareada" in tabla:
        validos = tabla["p_t_pareada"].notna()
        if validos.any():
            tabla.loc[validos, "p_t_holm"] = _holm(tabla.loc[validos, "p_t_pareada"].to_numpy())
    return tabla


# ----------------------------------------------------------------------------
def _imprimir(df, titulo):
    print(f"\n=== {titulo} ===")
    with pd.option_context("display.width", 200, "display.max_columns", 30, "display.float_format", "{:.3f}".format):
        print(df.to_string())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archivo", nargs="?", help="CSV *_muestras.csv de una sesión")
    ap.add_argument("--legacy", action="store_true", help="CSV con el formato anterior")
    ap.add_argument("--fs", type=float, default=config.FS, help="frecuencia de muestreo [Hz]")
    ap.add_argument("--grupo", metavar="CARPETA", help="estadística de grupo sobre todos los *_muestras.csv")
    a = ap.parse_args(argv)

    if a.grupo:
        resumenes = {}
        for ruta in sorted(glob.glob(os.path.join(a.grupo, "*_muestras.csv"))):
            sujeto = os.path.basename(ruta).split("_")[0]
            vent, lat = reprocesar(cargar_muestras(ruta), a.fs)
            res = resumen_por_fase(vent, lat)
            if sujeto in resumenes:                       # varias sesiones del mismo sujeto: se usa la última
                print(f"AVISO: {sujeto} tiene más de una sesión; se usa {os.path.basename(ruta)}")
            resumenes[sujeto] = res
        if not resumenes:
            print("No hay archivos *_muestras.csv en", a.grupo)
            return 1
        for var in ("ba_mediana", "ai_mediana"):
            _imprimir(estadistica_grupo(resumenes, var), f"{var}: fase de estrés vs basal (n = sujetos)")
        return 0

    if not a.archivo:
        ap.error("indicá un archivo o --grupo CARPETA")
    vent, lat = reprocesar(cargar_muestras(a.archivo, a.legacy), a.fs)
    res = resumen_por_fase(vent, lat)
    _imprimir(res, f"Resumen por fase - {os.path.basename(a.archivo)}")
    salida = os.path.splitext(a.archivo)[0] + "_resumen.csv"
    res.to_csv(salida, encoding="utf-8-sig")
    print(f"\nGuardado en {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
