import numpy as np
from scipy.signal import butter, filtfilt
from scipy.signal import butter, lfilter, lfilter_zi

# Configuración del filtro según el anteproyecto
FRECUENCIA_MUESTREO = 250
CORTE_BAJO = 0.5   # Hz
CORTE_ALTO = 15.0  # Hz
ORDEN_FILTRO = 2

def crear_filtro_butterworth():
    # Frecuencia de Nyquist es la mitad de la frecuencia de muestreo
    nyquist = 0.5 * FRECUENCIA_MUESTREO
    bajo = CORTE_BAJO / nyquist
    alto = CORTE_ALTO / nyquist
    b, a = butter(ORDEN_FILTRO, [bajo, alto], btype='band')
    return b, a

# Instanciamos los coeficientes una sola vez al cargar el módulo
B_COEF, A_COEF = crear_filtro_butterworth()

def procesar_ventana(vector_ppg_crudo):
    """
    Recibe una ventana de 10 segundos de señal PPG cruda.
    Aplica el filtro de fase cero y devuelve la señal limpia y su segunda derivada (SDPPG).
    """
    # 1. Convertir la lista a un arreglo de NumPy para operaciones vectoriales
    senal_numpy = np.array(vector_ppg_crudo)
    
    # 2. Filtrado bidireccional de fase cero (Zero-Phase Filtering)
    ppg_filtrado = filtfilt(B_COEF, A_COEF, senal_numpy)
    
    # 3. Derivación numérica para obtener la pletismografía de aceleración (SDPPG)
    # np.gradient calcula la derivada central discreta
    return ppg_filtrado
