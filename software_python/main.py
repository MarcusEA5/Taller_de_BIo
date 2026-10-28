"""
Punto de entrada.   Uso:   python main.py

Arquitectura:
    LectorSerie (hilo)  ──cola──►  QTimer (hilo de la GUI)  ──►  Orquestador  ──►  Graficador
    lee el puerto y parsea         drena la cola cada 40 ms     procesa/guarda     solo dibuja

Antes la GUI leía el puerto y redibujaba en cada muestra: cualquier demora de dibujo frenaba
la adquisición. Ahora el hilo lector nunca espera a la interfaz.
"""
import queue
import sys
from collections import deque

import numpy as np
from pyqtgraph.Qt import QtCore

import adquisicion
import config
import graficador
import orquestador
import procesamiento_gsr

MAX_ITEMS_POR_TICK = 4000        # tope de seguridad: ~20 s de datos a 200 Hz


def main():
    ui = graficador.Graficador()
    cola = queue.Queue()
    lector = adquisicion.LectorSerie(cola)
    orq = orquestador.Orquestador(ui, config.FS)

    ui.on_comenzar = orq.comenzar
    ui.on_finalizar = orq.finalizar

    ring_ppg = deque(maxlen=5 * config.FS)         # últimos 5 s
    ring_gsr = deque(maxlen=30 * config.FS)        # últimos 30 s

    def tick():
        for _ in range(MAX_ITEMS_POR_TICK):
            try:
                item = cola.get_nowait()
            except queue.Empty:
                break
            orq.procesar_item(item)
            if item[0] == "dato":
                _, _n, _t, ppg_raw, mv = item
                ring_ppg.append(-float(ppg_raw))
                ring_gsr.append(procesamiento_gsr.mV_a_uS(mv))
        ppg = np.fromiter(ring_ppg, dtype=float, count=len(ring_ppg))
        if ppg.size:
            ppg -= ppg.mean()                      # se muestra solo la componente pulsátil
        gsr = np.fromiter(ring_gsr, dtype=float, count=len(ring_gsr))
        ui.actualizar_tiempo_real(ppg, gsr, config.FS)

    timer = QtCore.QTimer()
    timer.timeout.connect(tick)
    timer.start(40)

    def al_salir():
        lector.detener()
        orq.finalizar()                            # cierra los CSV aunque se cierre la ventana grabando

    ui.app.aboutToQuit.connect(al_salir)
    lector.start()
    return ui.ejecutar()


if __name__ == "__main__":
    sys.exit(main())
