"""
Configuración central del sistema PPG + GSR.

TODOS los parámetros que afectan a las mediciones viven acá, para que:
  * el firmware, la adquisición y el análisis offline usen los mismos valores;
  * se puedan reportar tal cual en la sección de métodos del informe final.

IMPORTANTE: el índice de envejecimiento (AI) depende del suavizado (SG_VENTANA_MS)
y de la banda del filtro. Si cambian estos valores, los resultados NO son
comparables con los de sesiones anteriores. Por eso cada sesión guarda un
snapshot de esta configuración en su archivo *_meta.json.
"""

# ----------------------------------------------------------------------------
# Adquisición
# ----------------------------------------------------------------------------
FS = 200                  # Hz. Debe coincidir con FS_HZ del firmware (main.cpp).
BAUDRATE = 115200         # Irrelevante para USB-CDC nativo, se deja por compatibilidad.
PUERTO = None             # None = autodetectar el ESP32-C3; o fijar, p. ej., "COM7".
VID_ESPRESSIF = 0x303A    # Vendor ID del USB nativo del ESP32-C3.
TOLERANCIA_FS = 0.03      # Aviso si la fs medida se desvía más de este 3 % de FS.

# ----------------------------------------------------------------------------
# Ventaneo
# ----------------------------------------------------------------------------
VENTANA_S = 10            # Longitud de la ventana de análisis.
PASO_S = 5                # Avance entre ventanas (50 % de solapamiento).
# Los latidos se "confirman" (se guardan) solo si caen en la mitad central de la
# ventana. Con 50 % de solapamiento las mitades centrales de ventanas
# consecutivas se apoyan sin superponerse: cada latido se guarda una sola vez y
# los bordes (donde el filtro es menos fiable) se usan solo como contexto.

# ----------------------------------------------------------------------------
# PPG: filtrado y segunda derivada
# ----------------------------------------------------------------------------
BANDA_PPG_HZ = (0.5, 15.0)   # Butterworth pasa-banda, fase cero (filtfilt).
ORDEN_BUTTER = 2
SG_VENTANA_MS = 85           # Ventana del Savitzky-Golay (a 200 Hz = 17 muestras).
SG_ORDEN = 3                 # Orden del polinomio del Savitzky-Golay.

# ----------------------------------------------------------------------------
# PPG: detección de latidos y puntos fiduciarios (todo en segundos / relativo)
# ----------------------------------------------------------------------------
PICO_DISTANCIA_MIN_S = 0.30      # Separación mínima entre picos sistólicos.
PICO_DISTANCIA_REL_T0 = 0.60     # Separación mínima = 60 % del período dominante (autocorrelación).
AUTOCORR_MIN = 0.30              # Autocorrelación mínima para aceptar el período estimado.
PICO_PROMINENCIA_REL = 0.40      # Se descartan picos con < 40 % de la prominencia mediana.
A_BUSQUEDA_PREVIA_S = 0.30       # Solo para el primer latido de la ventana (sin pico previo).
A_ANTES_DE_VMAX_S = 0.15         # 'a' se busca hasta 0,15 s antes de la máxima velocidad de subida.
SEGMENTO_MAX_S = 0.60            # Largo máximo del segmento a-e analizado.
B_MAX_DESDE_A_S = 0.20
C_MAX_DESDE_B_S = 0.20
D_MAX_DESDE_C_S = 0.20
E_MAX_DESDE_D_S = 0.25
PROMINENCIA_ONDAS_REL = 0.04     # Un extremo cuenta como onda si supera el 4 % de 'a'.

# Validación de latidos
RR_MIN_S, RR_MAX_S = 0.33, 1.50  # ~40-180 lpm
RR_TOLERANCIA = 0.30             # Desvío máx. respecto del RR mediano de la ventana.
AMP_A_RANGO = (0.5, 2.0)         # Amplitud de 'a' respecto de la mediana de la ventana.
BA_RANGO = (-2.5, -0.1)          # b/a fisiológicamente plausible.
SQI_CORR_MIN = 0.85              # Correlación mínima del latido con la plantilla mediana de la ventana.
MIN_LATIDOS_VALIDOS = 5          # Mínimo por ventana para reportar resumen.
FRACCION_MIN_VALIDOS = 0.5       # Y al menos la mitad de los latidos detectados.

# Calidad de la señal cruda (cuentas del MAX30102, 18 bits)
UMBRAL_DEDO_CUENTAS = 30000      # Mediana del IR por debajo => no hay dedo.
SATURACION_CUENTAS = 262143      # Máximo de 18 bits.

# ----------------------------------------------------------------------------
# GSR: conversión de tensión a conductancia
# ----------------------------------------------------------------------------
# Topología que asume el cálculo (la misma que usaba main.py original):
#     VEXC ──[ piel ]──┬── (nodo) ──[ R1 ]── GND
#                      └─► buffer LM358 ─► (divisor opcional) ─► ADC
# V_nodo = VEXC * R1 / (R1 + R_piel)    =>   G = V_nodo / (R1 * (VEXC - V_nodo))
GSR_R1_OHM = 197_800.0     # Valor MEDIDO de R1.
GSR_VEXC_V = 3.3           # Medir con tester el valor real de VEXC.
GSR_K_DIV = 1.0            # Factor del divisor extra antes del ADC:
                           #   K = (Ra + Rb) / Rb   (K = 1.0 si no hay divisor).
                           # COMPLETAR con los valores reales del divisor armado.
SCR_PROMINENCIA_uS = 0.03  # Prominencia mínima para contar una SCR en la ventana.
GSR_CONTACTO_MIN = 0.80    # Fracción mínima de muestras válidas en la ventana.

# ----------------------------------------------------------------------------
# Protocolo experimental (duración mínima sugerida por fase, en segundos)
# ----------------------------------------------------------------------------
# VALORES PROVISORIOS: acordarlos con el asesor y fijarlos en el protocolo.
PROTOCOLO = [
    ("1. Reposo Basal", 180),
    ("2. Test Stroop", 180),
    ("3. Pausa", 120),
    ("4. Aim Trainer", 180),
    ("5. Recuperación", 180),
]
FASE_BASAL = "1. Reposo Basal"
FASE_INACTIVA = "Inactivo"
FASE_TRANSICION = "Transicion"   # Ventanas que cruzan dos fases: no entran en estadística.

# ----------------------------------------------------------------------------
# Edad vascular (ecuación publicada de Takazawa et al., 1998)
# ----------------------------------------------------------------------------
# AI = EDAD_TAKAZAWA[0] * edad + EDAD_TAKAZAWA[1]
# NO está validada para este sensor/filtro. Mientras no se calibre con
# voluntarios de distintas edades, no se muestra en pantalla.
EDAD_TAKAZAWA = (0.023, -1.515)
MOSTRAR_EDAD_VASCULAR = False
MIN_LATIDOS_EDAD = 60
