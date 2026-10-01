import numpy as np
from scipy.signal import find_peaks

def extraer_puntos_fiduciarios(sdppg, fs=250):
    resultados_latidos = []
    puntos_x = []
    puntos_y = []
    colores_puntos = []
    
    distancia_minima = int(fs * 0.4) 
    picos_a, _ = find_peaks(sdppg, distance=distancia_minima, prominence=np.max(sdppg)*0.3)
    
    for i in range(len(picos_a) - 1):
        idx_a = picos_a[i]
        idx_siguiente_a = picos_a[i+1]
        segmento_latido = sdppg[idx_a:idx_siguiente_a]
        
        maximos_locales, _ = find_peaks(segmento_latido)
        minimos_locales, _ = find_peaks(-segmento_latido)
        
        try:
            amp_a = sdppg[idx_a]
            
            idx_b = idx_a + minimos_locales[0]
            amp_b = sdppg[idx_b]
            
            max_despues_b = [m for m in maximos_locales if m > minimos_locales[0]]
            idx_c = idx_a + max_despues_b[0]
            amp_c = sdppg[idx_c]
            
            min_despues_c = [m for m in minimos_locales if m > max_despues_b[0]]
            idx_d = idx_a + min_despues_c[0]
            amp_d = sdppg[idx_d]
            
            max_despues_d = [m for m in max_despues_b if m > min_despues_c[0]]
            idx_e = idx_a + max_despues_d[0]
            amp_e = sdppg[idx_e]
            
            ratio_ba = amp_b / amp_a
            # MANTENEMOS EL AI PURO Y ADIMENSIONAL
            aging_index = (amp_b - amp_c - amp_d - amp_e) / amp_a
            
            resultados_latidos.append({
                'ratio_ba': ratio_ba,
                'aging_index': aging_index,
            })
            
            puntos_x.extend([idx_a, idx_b, idx_c, idx_d, idx_e])
            puntos_y.extend([amp_a, amp_b, amp_c, amp_d, amp_e])
            colores_puntos.extend(['b', 'r', 'g', 'y', 'm'])
            
        except IndexError:
            continue
            
    if resultados_latidos:
        distancias_muestras = np.diff(picos_a)
        promedio_muestras = np.mean(distancias_muestras)
        bpm = (fs / promedio_muestras) * 60 
        
        promedio_ratio_ba = np.mean([latido['ratio_ba'] for latido in resultados_latidos])
        promedio_ai = np.mean([latido['aging_index'] for latido in resultados_latidos])
        
        return promedio_ratio_ba, promedio_ai, puntos_x, puntos_y, colores_puntos, bpm
    else:
        return None, None, None, None, None, 0