import numpy as np

def sdppg(ppg_filtrado):
    primera_derivada = np.gradient(ppg_filtrado)
    sdppg = np.gradient(primera_derivada)
    return sdppg