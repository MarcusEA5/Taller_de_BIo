"""
Tests automáticos (no requieren hardware ni Qt):   python test_pipeline.py
También funcionan con pytest.

Verifican, con señales de verdad conocida, que:
  * el parseo del protocolo serie rechaza líneas corruptas;
  * el control de tiempo detecta pérdidas de muestras;
  * la conversión de GSR es consistente con el circuito;
  * el detector recupera BPM, b/a y AI de un PPG sintético con ruido y, sobre todo,
    DETECTA DIFERENCIAS entre condiciones (lo que importa en el estudio);
  * el ruido no produce "latidos válidos" y las arterias con onda diastólica alta
    no duplican los lpm;
  * el ventaneo no duplica latidos y descarta ventanas con huecos;
  * el guardado produce CSV legibles.

NOTA SOBRE EL SESGO: el suavizado Savitzky-Golay atenúa las ondas angostas de la SDPPG
(más 'a' que 'b', y casi borra 'c'). Con los parámetros por defecto el b/a medido queda
~0,1 por debajo del real. Es un sesgo sistemático y estable: sirve para comparar
condiciones, pero los valores absolutos dependen de SG_VENTANA_MS (ver config.py).
"""
import os
import tempfile

import numpy as np

import adquisicion
import config
import pipeline
import procesamiento_gsr as gsr
import procesamiento_ppg as ppg

FS = config.FS
FS_HI = 1200                      # frecuencia de la síntesis (múltiplo entero de FS=200)

# Lóbulos de la SDPPG: (onda, amplitud, instante [s], sigma [s])
# 'b' es más ANCHO que 'a' (área mayor): así la velocidad se vuelve negativa tras el pico y el pulso
# tiene la forma fisiológica (subida rápida, pico, caída con onda dicrota).
LOBULOS = [("a", +1.00, 0.050, 0.024), ("b", -0.75, 0.120, 0.042), ("c", +0.15, 0.200, 0.030),
           ("d", -0.15, 0.260, 0.030), ("e", +0.30, 0.340, 0.035)]


F_INSTANTE, F_SIGMA = 0.50, 0.07          # onda 'f' tardía: cierra el área de la SDPPG


def _sdppg_periodica(ph, lobulos):
    """SDPPG periódica: lóbulos a-e + una onda 'f' negativa que hace nula el área del ciclo.

    Sin ese cierre la aceleración tendría media distinta de cero y no existiría un PPG
    periódico: al integrar aparecería una parábola en cada latido y el pulso saldría deforme.
    """
    area = sum(A * s * np.sqrt(2 * np.pi) for _, A, _, s in lobulos)
    f_amp = -area / (F_SIGMA * np.sqrt(2 * np.pi))
    sd = sum(A * np.exp(-(ph - m) ** 2 / (2 * s ** 2)) for _, A, m, s in lobulos)
    return sd + f_amp * np.exp(-(ph - F_INSTANTE) ** 2 / (2 * F_SIGMA ** 2))


def ppg_sintetico(dur_s, bpm=75, ruido=0.01, lobulos=None, semilla=1):
    """PPG construido integrando DOS veces (en frecuencia) una SDPPG con a-e conocidos.

    bpm debe dar un período de muestras enteras a FS_HI (50, 60, 75, 80, 100...).
    """
    lobulos = lobulos or LOBULOS
    T = 60.0 / bpm
    n = int(round(dur_s / T)) * int(round(T * FS_HI))
    ph = np.mod(np.arange(n) / FS_HI, T)
    sd = _sdppg_periodica(ph, lobulos)
    F = np.fft.rfft(sd)
    w = 2 * np.pi * np.fft.rfftfreq(n, 1 / FS_HI)
    G = np.zeros_like(F)
    G[1:] = F[1:] / (-(w[1:] ** 2))
    x = np.fft.irfft(G, n)[:: FS_HI // FS]
    rng = np.random.default_rng(semilla)
    return x + ruido * np.std(x) * rng.standard_normal(x.size)


def verdad(bpm=75, lobulos=None):
    """b/a y AI reales: extremos de la SDPPG analítica a alta resolución, sin ruido ni suavizado."""
    lobulos = lobulos or LOBULOS
    T = 60.0 / bpm
    ph = np.mod(np.arange(int(3 * T * FS_HI)) / FS_HI, T)
    sd = _sdppg_periodica(ph, lobulos)
    l = ppg.Latido(idx_pico=int((T + 0.16) * FS_HI))
    desde = int((T + 0.01) * FS_HI)                       # 'a' del 2.º ciclo: máximo de la SDPPG en su inicio
    ia = desde + int(np.argmax(sd[desde:desde + int(0.08 * FS_HI)]))
    ppg._medir_fiduciarios(l, sd, FS_HI, ia)
    assert l.motivo == "", l.motivo
    return l.ba, l.ai


def _resumen(x):
    xf = ppg.filtrar_ppg(x, FS)
    return ppg.resumir(ppg.analizar_latidos(xf, ppg.segunda_derivada(xf, FS), FS))


# ----------------------------------------------------------------------------
def test_parseo_linea():
    def linea(n, t, p, g):
        cuerpo = f"{n},{t},{p},{g}"
        c = 0
        for ch in cuerpo:
            c ^= ord(ch)
        return f"{cuerpo}*{c:02X}"

    assert adquisicion.parsear_linea(linea(5, 25000, 87654, 912)) == ("dato", 5, 25000, 87654, 912)
    assert adquisicion.parsear_linea("# fs=200") == ("info", "fs=200")
    corrupta = linea(5, 25000, 87654, 912).replace("87654", "87655")
    assert adquisicion.parsear_linea(corrupta) is None
    assert adquisicion.parsear_linea("5,25000,87654") is None
    assert adquisicion.parsear_linea("5,25000,87654,91*ZZ") is None
    assert adquisicion.parsear_linea("") is None


def test_control_tiempo():
    ct = adquisicion.ControlTiempo(200)
    for n in range(2000):
        ct.actualizar(n, int(n * 5000))
    assert abs(ct.fs_medida() - 200) < 0.1 and ct.estado()[0]
    ct2 = adquisicion.ControlTiempo(200)
    for n in range(2000):
        ct2.actualizar(n, int(n * 5000 * 1.25))          # 160 Hz: se perdió el 20 % de las muestras
    assert not ct2.estado()[0]
    ct3 = adquisicion.ControlTiempo(200)                 # desborde de micros() a los 71 min
    for n in range(2000):
        ct3.actualizar(n, (int(n * 5000) + (2 ** 32 - 3_000_000)) % (2 ** 32))
    assert abs(ct3.fs_medida() - 200) < 0.5
    ct4 = adquisicion.ControlTiempo(200)
    ct4.fs_declarada = 250.0                             # firmware y config.py desalineados
    assert not ct4.estado()[0]


def test_gsr_ida_y_vuelta():
    for r_piel in (50e3, 200e3, 500e3, 1e6, 2e6):
        g = 1e6 / r_piel
        assert abs(gsr.mV_a_uS(gsr.uS_a_mV(g)) - g) / g < 1e-6
    assert np.isnan(gsr.mV_a_uS(0.0))                    # electrodos sueltos
    assert np.isnan(gsr.mV_a_uS(config.GSR_VEXC_V * 1000 / config.GSR_K_DIV + 1))
    # corriente por la piel: debe poder verificarse contra el límite de 10 µA
    assert gsr.corriente_piel_uA(config.GSR_VEXC_V * 1000 / 2) > 0


def test_gsr_scr_detecta_pico():
    t = np.arange(10 * FS) / FS
    g = 2.0 + 0.4 * np.exp(-(t - 5) ** 2 / (2 * 0.8 ** 2))
    r = gsr.analizar_ventana(g, FS)
    assert r["contacto_ok"] and r["scr_n"] == 1 and 0.3 < r["scr_amp_uS"] < 0.45
    assert abs(r["scl_uS"] - 2.0) < 0.1
    assert not gsr.analizar_ventana(np.full(10 * FS, np.nan), FS)["contacto_ok"]


def test_detector_recupera_bpm_y_calidad():
    r = _resumen(ppg_sintetico(30, bpm=75, ruido=0.02))
    assert r["resumen_ok"], r
    assert abs(r["bpm"] - 75) < 1.0, r["bpm"]
    assert r["n_validos"] >= 0.9 * r["n_latidos"], r


def test_respuesta_lineal_y_sesgo_conocido():
    """b/a y AI medidos deben ser una función LINEAL y creciente de los reales.

    Con los parámetros por defecto el suavizado hace b/a medido ≈ 1,28 × real + 0,07
    (sesgo sistemático y estable). Mientras sea lineal, las diferencias entre condiciones
    (Δ b/a entre basal y estrés) se detectan con una ganancia constante conocida.
    """
    lob_b = lambda b: [(n, (b if n == "b" else A), m, s) for n, A, m, s in LOBULOS]
    ba_r, ba_m, ai_r, ai_m = [], [], [], []
    for b in (-0.45, -0.55, -0.65, -0.75):
        real = verdad(75, lob_b(b))
        r = _resumen(ppg_sintetico(30, bpm=75, ruido=0.02, lobulos=lob_b(b)))
        assert r["resumen_ok"] and r["n_validos"] >= 0.9 * r["n_latidos"], (b, r)
        ba_r.append(real[0]); ai_r.append(real[1]); ba_m.append(r["ba_med"]); ai_m.append(r["ai_med"])
    for real, med in ((ba_r, ba_m), (ai_r, ai_m)):
        pend, _ = np.polyfit(real, med, 1)
        assert np.corrcoef(real, med)[0, 1] > 0.995, (real, med)
        assert 1.1 < pend < 1.5, pend                                  # ganancia conocida ≈ 1,28
    assert all(m < r for m, r in zip(ba_m, ba_r)), "el sesgo conocido es hacia valores más negativos"


def test_detector_varias_frecuencias():
    for bpm in (50, 75, 100):
        r = _resumen(ppg_sintetico(30, bpm=bpm, ruido=0.02, semilla=bpm))
        assert r["resumen_ok"] and abs(r["bpm"] - bpm) < 2, (bpm, r)


def test_onda_diastolica_alta_no_duplica_latidos():
    """Con 'e' grande el PPG tiene dos picos por ciclo; no deben contarse como dos latidos."""
    lob = [(n, (0.55 if n == "e" else A), m, (0.045 if n == "e" else s)) for n, A, m, s in LOBULOS]
    r = _resumen(ppg_sintetico(30, bpm=75, ruido=0.01, lobulos=lob))
    assert abs(r["bpm"] - 75) < 2, r["bpm"]


def test_ruido_puro_no_genera_resumen():
    for semilla in range(1, 6):
        rng = np.random.default_rng(semilla)
        xf = ppg.filtrar_ppg(rng.standard_normal(10 * FS), FS)
        r = ppg.resumir(ppg.analizar_latidos(xf, ppg.segunda_derivada(xf, FS), FS))
        assert not r["resumen_ok"], f"semilla {semilla}: se reportó b/a a partir de ruido"


def _correr_stream(x_raw, mv, fase="X", salto=None):
    proc = pipeline.ProcesadorStream(FS)
    salidas = []
    for i in range(len(x_raw)):
        n = i if (salto is None or i < salto[0]) else i + salto[1]
        r = proc.agregar(n, x_raw[i], mv[i], fase)
        if r is not None:
            salidas.append(r)
    return proc, salidas


def _a_cuentas_max30102(x):
    return 90000 - 2000 * x                    # menos cuentas = más sangre (polaridad del sensor)


def test_stream_no_duplica_latidos():
    raw = _a_cuentas_max30102(ppg_sintetico(60, bpm=75, ruido=0.01))
    _, salidas = _correr_stream(raw, np.full(len(raw), 900.0))
    picos = [l["n_pico"] for r in salidas for l in r["latidos_confirmados"]]
    assert len(picos) == len(set(picos)), "hay latidos duplicados"
    assert picos == sorted(picos)
    esperados = (60 - config.VENTANA_S / 2) * 75 / 60      # se excluyen los cuartos extremos de borde
    assert 0.85 * esperados <= len(picos) <= 1.1 * esperados, (len(picos), esperados)
    assert np.mean([l["valido"] for r in salidas for l in r["latidos_confirmados"]]) > 0.9


def test_stream_descarta_ventana_con_hueco():
    raw = _a_cuentas_max30102(ppg_sintetico(40, bpm=75, ruido=0.01))
    proc, salidas = _correr_stream(raw, np.full(len(raw), 900.0), salto=(15 * FS, 50))
    assert proc.perdidas == 50
    n_fin = [r["n_fin"] for r in salidas]
    # ninguna ventana puede contener el hueco que va de la muestra 3000 a la 3050
    assert not any(3000 < n < 3000 + config.VENTANA_S * FS for n in n_fin), n_fin
    assert any(n > 3050 + config.VENTANA_S * FS - 5 for n in n_fin), "debe reanudar tras el hueco"


def test_stream_sin_dedo():
    raw = np.full(20 * FS, 500.0)                        # IR ~ 0: no hay dedo
    _, salidas = _correr_stream(raw, np.full(len(raw), 900.0))
    assert salidas and all(not r["dedo_ok"] and not r["resumen_ok"] for r in salidas)


def test_stream_marca_transicion():
    raw = _a_cuentas_max30102(ppg_sintetico(30, bpm=75, ruido=0.01))
    proc = pipeline.ProcesadorStream(FS)
    fases = []
    for i in range(len(raw)):
        r = proc.agregar(i, raw[i], 900.0, "A" if i < 18 * FS else "B")
        if r is not None:
            fases.append(r["fase"])
    assert "A" in fases and "B" in fases and config.FASE_TRANSICION in fases


def test_orquestador_flujo_completo():
    """Sesión completa simulada: basal -> Stroop. Comprueba guardado y AI basal."""
    import orquestador

    class UI:
        is_recording = False
        fase_actual = config.FASE_INACTIVA
        edad_vascular_texto = ""
        ventanas = []
        def mostrar_ventana(self, res): self.ventanas.append(res)
        def set_estado_adquisicion(self, ok, texto): self.estado = (ok, texto)

    ui = UI()
    with tempfile.TemporaryDirectory() as d:
        o = orquestador.Orquestador(ui, FS, carpeta=d)
        raw = _a_cuentas_max30102(ppg_sintetico(90, bpm=75, ruido=0.01))
        o.comenzar({"Codigo": "V07", "Edad": "22"})
        ui.is_recording = True
        for i, v in enumerate(raw):
            ui.fase_actual = config.FASE_BASAL if i < 60 * FS else "2. Test Stroop"
            o.procesar_item(("dato", i, int(i * 5000), int(v), 900))
        o.finalizar()
        import json, pandas as pd
        base = [f for f in os.listdir(d) if f.endswith("_meta.json")][0][:-10]
        meta = json.load(open(os.path.join(d, base + "_meta.json"), encoding="utf-8"))
        assert meta["cierre"]["n_latidos_basales"] > 40, meta["cierre"]
        assert meta["cierre"]["muestras_perdidas"] == 0
        assert abs(meta["cierre"]["fs_medida_hz"] - 200) < 0.5
        assert "AI basal" in ui.edad_vascular_texto            # edad en años oculta por defecto
        lat = pd.read_csv(os.path.join(d, base + "_latidos.csv"), encoding="utf-8-sig")
        assert set(lat["fase"]) >= {config.FASE_BASAL, "2. Test Stroop"}
        assert lat["n_pico"].is_unique
        mu = pd.read_csv(os.path.join(d, base + "_muestras.csv"), encoding="utf-8-sig")
        assert len(mu) == len(raw)


def test_guardado_csv():
    import json
    import pandas as pd
    from almacenamiento_csv import GestorSesion, id_valido
    assert id_valido("V01") and not id_valido("Juan Perez") and not id_valido("")
    with tempfile.TemporaryDirectory() as d:
        s = GestorSesion("V01", {"Codigo": "V01", "Edad": "22"}, d)
        s.guardar_muestra(0, FS, "1. Reposo Basal", 87000, 900, 2.0)
        s.guardar_muestra(1, FS, "1. Reposo Basal", 87010, 901, float("nan"))
        s.guardar_latidos([dict(n_pico=10, t_s=0.05, fase="1. Reposo Basal", valido=True, motivo="",
                                rr_s=0.8, a=1.0, b=-0.7, c=0.1, d=-0.1, e=0.3, ba=-0.7, ai=-1.1)])
        s.cerrar({"muestras_perdidas": 0})
        m = pd.read_csv(f"{s.base}_muestras.csv", encoding="utf-8-sig")
        assert list(m.columns)[:4] == ["n", "t_s", "t_pc", "fase"] and len(m) == 2
        assert np.isnan(m.loc[1, "gsr_uS"]) and m.loc[0, "fase"] == "1. Reposo Basal"
        la = pd.read_csv(f"{s.base}_latidos.csv", encoding="utf-8-sig")
        assert la.loc[0, "ai"] == -1.1
        meta = json.load(open(f"{s.base}_meta.json", encoding="utf-8"))
        assert meta["config"]["FS"] == config.FS and "fin" in meta["cierre"]


if __name__ == "__main__":
    pruebas = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fallos = 0
    for nombre, f in pruebas:
        try:
            f()
            print(f"  OK    {nombre}")
        except Exception as exc:                          # noqa: BLE001
            fallos += 1
            print(f"  FALLA {nombre}: {type(exc).__name__}: {exc}")
    print(f"\n{len(pruebas) - fallos}/{len(pruebas)} tests OK")
    raise SystemExit(1 if fallos else 0)
