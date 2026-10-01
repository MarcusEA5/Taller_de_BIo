from scipy.signal import butter, filtfilt
import numpy as np

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

    b_clean, a_clean = butter(2, 1.0 / nyq, btype='low')
    gsr_filtrado = filtfilt(b_clean, a_clean, senal)
    
    # El SCL actual es el promedio de la tendencia en la ventana
    scl_actual = float(np.mean(gsr_filtrado))

    senal_fasica = gsr_filtrado - scl_actual
    
    # Actividad transitoria (desviación estándar local)
    scr_actividad = float(np.std(senal_fasica))
    
    return scl_actual, scr_actividad