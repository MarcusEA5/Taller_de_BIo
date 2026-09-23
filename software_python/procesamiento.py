import numpy as np
from scipy.signal import find_peaks
from scipy.signal import butter, filtfilt

def extraer_puntos_fiduciarios(sdppg, fs=250):
    resultados_latidos = []
    
    # Listas para guardar las coordenadas y colores de los puntos a graficar
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
            # Identificamos el EJE X (índice de tiempo) y el EJE Y (amplitud) de cada onda
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
            aging_index = (amp_b - amp_c - amp_d - amp_e) / amp_a
            
            resultados_latidos.append({
                'ratio_ba': ratio_ba,
                'aging_index': aging_index
            })
            
            # GUARDAMOS LAS COORDENADAS PARA EL GRAFICADOR
            puntos_x.extend([idx_a, idx_b, idx_c, idx_d, idx_e])
            puntos_y.extend([amp_a, amp_b, amp_c, amp_d, amp_e])
            # Asignamos un color específico a cada onda (a=azul, b=rojo, c=verde, d=amarillo, e=magenta)
            colores_puntos.extend(['b', 'r', 'g', 'y', 'm'])
            
        except IndexError:
            continue
            
    if resultados_latidos:
        # Calcular distancias entre picos 'a' consecutivos
        distancias_muestras = np.diff(picos_a)
        promedio_muestras = np.mean(distancias_muestras)
        # Convertir muestras a segundos, y luego a latidos por minuto
        bpm = (fs / promedio_muestras) * 60 
        
        promedio_ratio_ba = np.mean([latido['ratio_ba'] for latido in resultados_latidos])
        promedio_ai = np.mean([latido['aging_index'] for latido in resultados_latidos])
        
        return promedio_ratio_ba, promedio_ai, puntos_x, puntos_y, colores_puntos, bpm
    else:
        return None, None, None, None, None, 0

def procesar_gsr_ventana(vector_gsr, fs=250):
    """
    Procesa un bloque de GSR para extraer el nivel base (SCL) 
    y la actividad transitoria (SCR).
    """
    if not vector_gsr or len(vector_gsr) < fs:
        return 0.0, 0.0
        
    senal = np.array(vector_gsr, dtype=float)
    
    # Filtro pasa-bajos muy suave (1 Hz) para aislar la componente lenta (SCL)
    nyq = 0.5 * fs
    b, a = butter(2, 1.0 / nyq, btype='low')
    scl_filtrado = filtfilt(b, a, senal)
    
    # El SCL actual es el promedio de la tendencia en la ventana
    scl_actual = float(np.mean(scl_filtrado))
    
    # Actividad transitoria (desviación estándar local)
    scr_actividad = float(np.std(senal - scl_filtrado))
    
    return scl_actual, scr_actividad