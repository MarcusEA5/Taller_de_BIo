"""
Calibración del circuito GSR con resistencias patrón (reemplazan a la piel).

Uso:   python calibrar_gsr.py 100000 220000 470000 1000000
       (valores en ohm de las resistencias que tengas, medidas con tester si es posible)

Para cada resistencia el programa te pide conectarla en lugar de los electrodos, mide ~10 s
el GSR del ESP32 (mV) y al final ajusta el modelo del circuito:

        mV = 1000 * V0 * R1 / (R1 + R_patron)          con  V0 = VEXC / K

Nota: la conversión a µS depende de VEXC y K SOLO a través de V0 = VEXC / K, así que
alcanza con ajustar V0 y R1. Al terminar imprime los valores para pegar en config.py
(con GSR_K_DIV = 1.0 y GSR_VEXC_V = V0). Con 3 o más resistencias de valores distintos
también se ve cuán bien describe el circuito el modelo (error residual).

Además muestra la corriente que circularía por la piel con cada resistencia, para
comprobar el límite de 10 µA.
"""
import queue
import sys
import time

import numpy as np

import config


def ajustar(rs_ohm, mv_medidos):
    """Ajusta (V0 [V], R1 [ohm]) a partir de pares (R patrón, mV medidos). Devuelve (V0, R1, residuo_mV)."""
    from scipy.optimize import curve_fit
    rs = np.asarray(rs_ohm, dtype=float)
    mv = np.asarray(mv_medidos, dtype=float)
    if len(rs) < 2:
        raise ValueError("Hacen falta al menos 2 resistencias distintas para ajustar V0 y R1.")

    def modelo(r, v0, r1):
        return 1000.0 * v0 * r1 / (r1 + r)

    (v0, r1), _ = curve_fit(modelo, rs, mv, p0=[config.GSR_VEXC_V / config.GSR_K_DIV, config.GSR_R1_OHM])
    residuo = float(np.max(np.abs(modelo(rs, v0, r1) - mv)))
    return float(v0), float(r1), residuo


def medir_mv(cola, segundos):
    """Mediana de gsr_mV de los datos que llegan durante `segundos` segundos."""
    vistos, t_fin = [], time.time() + segundos
    while time.time() < t_fin:
        try:
            item = cola.get(timeout=0.5)
        except queue.Empty:
            continue
        if item[0] == "dato":
            vistos.append(item[4])
        elif item[0] == "error":
            raise RuntimeError(item[1])
    if not vistos:
        raise RuntimeError("No llegaron datos del ESP32.")
    return float(np.median(vistos))


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    rs = [float(v) for v in argv[1:]]
    import adquisicion
    cola = queue.Queue()
    lector = adquisicion.LectorSerie(cola)
    lector.start()
    medidos = []
    try:
        for r in rs:
            input(f"\nConectá la resistencia de {r:,.0f} ohm en lugar de los electrodos y presioná Enter... ")
            mv = medir_mv(cola, 10)
            medidos.append(mv)
            print(f"   medido: {mv:.1f} mV")
    finally:
        lector.detener()
    v0, r1, residuo = ajustar(rs, medidos)
    print("\n================ RESULTADO ================")
    print(f"R1 ajustada = {r1:,.0f} ohm      (config actual: {config.GSR_R1_OHM:,.0f})")
    print(f"V0 = VEXC/K = {v0:.4f} V         (config actual: {config.GSR_VEXC_V / config.GSR_K_DIV:.4f})")
    print(f"Error máximo del ajuste: {residuo:.1f} mV")
    print("\nPegá esto en config.py:\n"
          f"    GSR_R1_OHM = {r1:.0f}.0\n    GSR_VEXC_V = {v0:.4f}\n    GSR_K_DIV = 1.0")
    print(f"\nCorriente por la piel con R_piel = 50 kohm: {1e6 * v0 / (r1 + 50e3):.1f} uA | "
          f"con electrodos en corto: {1e6 * v0 / r1:.1f} uA   (límite que declararon: 10 uA)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
