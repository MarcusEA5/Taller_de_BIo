import os
import serial
import sys
import time
from collections import deque

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Importas tus módulos separados
import graficador
import filtro
import sdppg
import procesamiento_ppg 
import procesamiento_gsr
import almacenamiento_csv

# Configuraciones basadas en el anteproyecto
FRECUENCIA_MUESTREO = 250  
TAMANO_VENTANA = FRECUENCIA_MUESTREO * 10  # 10 segundos (2500 muestras)
AVANCE_VENTANA = TAMANO_VENTANA // 2       # Solapamiento del 50%

def main():
    # 1. Inicializamos la pantalla a través del módulo graficador
    interfaz = graficador.Graficador()
    
    # Preparamos los búferes independientes para ambas señales
    buffer_ppg = deque(maxlen=TAMANO_VENTANA)
    buffer_gsr = deque(maxlen=TAMANO_VENTANA)
    
    # Variables de control para la grabación dinámica y las fases
    logger = None
    grabando_anterior = False
    
    # Variables para el acumulador de la Edad Vascular
    lista_ai_basal = []
    edad_ya_calculada = False
    
    print("Iniciando monitor bimodal PPG + GSR... Presione Ctrl+C para salir.")
    
    try:
        with serial.Serial('COM7', 115200, timeout=1) as puerto_serial:
            puerto_serial.reset_input_buffer()
            time.sleep(2)
            
            while True:
                # 2. Leemos la trama enviada por el ESP32-C3
                linea = puerto_serial.readline().decode('utf-8', errors='ignore').strip()

                if linea:
                    try:
                        # Esperamos datos separados por coma: ppg, gsr
                        datos = [float(v) for v in linea.split(',')]

                        if len(datos) == 1:
                            ppg_crudo, gsr_crudo = datos[0] * -1, 0.0
                            gsr_microsiemens = 0.0
                        elif len(datos) >= 2:
                            ppg_crudo, gsr_crudo = datos[0] * -1, datos[1]
                            
                            # --- CONVERSIÓN FÍSICA A MICROSIEMENS (DIVISOR ORIGINAL) ---
                            v_out = gsr_crudo * (3.3 / 4095.0)
                            
                            # Evitamos división por cero si el voltaje cae a 0V o llega a 3.3V
                            if 0 < v_out < 3.3: 
                                r_piel = 197800.0 * ((3.3 - v_out) / v_out)
                                gsr_microsiemens = (1.0 / r_piel) * 1000000.0
                            else:
                                gsr_microsiemens = 0.0
                                
                        # Llenamos ambos búferes (PPG va crudo, GSR ya va convertido a uS)
                        buffer_ppg.append(ppg_crudo)
                        buffer_gsr.append(gsr_microsiemens)
                        
                        # Actualizamos el osciloscopio rápido superior pasando los microSiemens
                        interfaz.actualizar_tiempo_real(ppg_crudo, gsr_microsiemens)
                        
                        # --- CONTROL DINÁMICO DE GRABACIÓN POR BOTÓN ---
                        estado_actual_boton = interfaz.is_recording
                        
                        if estado_actual_boton and not grabando_anterior:
                            try:
                                # Al hacer clic en grabar, se crea un archivo CSV con los metadatos del sujeto
                                logger = almacenamiento_csv.GestorCSV(
                                    id_sujeto="Voluntario_Prueba",
                                    datos_medicos=getattr(interfaz, 'datos_medicos', {})
                                )
                                print("\n>>> [GRABACIÓN INICIADA] Archivo CSV creado con metadatos.")
                                
                                # Al iniciar una nueva prueba, reseteamos el acumulador de edad vascular
                                lista_ai_basal = []
                                edad_ya_calculada = False
                                
                            except Exception as exc:
                                logger = None
                                print(f"\n>>> [ERROR AL INICIAR GRABACIÓN] {exc}")

                        elif not estado_actual_boton and grabando_anterior:
                            logger = None
                            print("\n>>> [GRABACIÓN DETENIDA] Archivo cerrado de forma segura.")
                            
                        grabando_anterior = estado_actual_boton

                        # --- GUARDADO CONTINUO (Alta frecuencia - Muestra a muestra) ---
                        if logger is not None:
                            fase_actual = getattr(interfaz, 'fase_actual', "Sin_Fase")
                            logger.guardar_fila(
                                fase=fase_actual, 
                                ppg_crudo=ppg_crudo, 
                                ppg_filtrado="", 
                                gsr_crudo=gsr_crudo
                            )
                        
                        # --- RASTREADOR DE VELOCIDAD EN CONSOLA ---
                        if len(buffer_ppg) % 250 == 0:
                            fase_txt = getattr(interfaz, 'fase_actual', 'Inactivo')
                            print(f"[{fase_txt}] Acumulando datos: {len(buffer_ppg)} / {TAMANO_VENTANA}")
                        
                        # 4. Si se llenó la ventana de 10 segundos, procesamos bloques
                        if len(buffer_ppg) == TAMANO_VENTANA:
                            try:
                                # Procesamiento matemático del PPG y la SDPPG
                                ppg_limpio = filtro.procesar_ventana(list(buffer_ppg))
                                segunda_derivada = sdppg.sdppg(ppg_limpio)
                                ratio_ba, aging_index, pts_x, pts_y, colores, bpm = procesamiento_ppg.extraer_puntos_fiduciarios(segunda_derivada, fs=FRECUENCIA_MUESTREO)

                                # Procesamiento del bloque de GSR (Extracción de SCL)
                                scl_valor, _ = procesamiento_gsr.procesar_gsr_ventana(list(buffer_gsr), fs=FRECUENCIA_MUESTREO)

                                if ratio_ba is not None:
                                    
                                    # =================================================================
                                    # --- LÓGICA DE CÁLCULO DE EDAD VASCULAR BASAL (NUEVO BLOQUE) ---
                                    # =================================================================
                                    fase_actual = getattr(interfaz, 'fase_actual', "Sin_Fase")
                                    
                                    # Si estamos en reposo, acumulamos el AI crudo
                                    if fase_actual == "1. Reposo Basal":
                                        lista_ai_basal.append(aging_index)
                                        interfaz.edad_vascular_fija = None # Lo mantenemos oculto (dice "Calculando...")
                                        edad_ya_calculada = False
                                        
                                    # Si cambiamos a otra fase (ej. Stroop) y aún no calculamos la edad
                                    elif fase_actual not in ["Inactivo", "1. Reposo Basal", "Sin_Fase"] and not edad_ya_calculada:
                                        if len(lista_ai_basal) > 0:
                                            # Promediamos todo el AI acumulado en los minutos de reposo
                                            ai_promedio_basal = sum(lista_ai_basal) / len(lista_ai_basal)
                                            # Aplicamos la ecuación de Takazawa UNA SOLA VEZ
                                            edad_estimada = (ai_promedio_basal + 1.515) / 0.023
                                            interfaz.edad_vascular_fija = edad_estimada
                                        else:
                                            # Por si el usuario saltó la fase 1 de reposo y fue directo al Stroop
                                            interfaz.edad_vascular_fija = 0.0 
                                        edad_ya_calculada = True
                                    # =================================================================
                                    
                                    # Actualizamos gráficos y el panel izquierdo con los biomarcadores (incluyendo SCL)
                                    interfaz.actualizar_procesado(
                                        ppg_limpio, segunda_derivada, ratio_ba, aging_index, scl_valor, 
                                        puntos_x=pts_x, puntos_y=pts_y, colores=colores, bpm=bpm
                                    )

                                    # Si estamos grabando, guardamos la fila con los biomarcadores calculados
                                    if logger is not None:
                                        logger.guardar_fila(
                                            fase=fase_actual,
                                            ppg_crudo=ppg_crudo, 
                                            ppg_filtrado=ppg_limpio[-1], 
                                            gsr_crudo=gsr_crudo, 
                                            bpm=bpm, 
                                            ratio_ba=ratio_ba, 
                                            ai=aging_index, 
                                            scl=scl_valor
                                        )

                                    print("¡Ventana procesada y biomarcadores actualizados con éxito!")
                                else:
                                    print("Ventana descartada por exceso de ruido. Esperando siguiente bloque...")

                                # Avance de la ventana (Solapamiento del 50%)
                                for _ in range(AVANCE_VENTANA):
                                    buffer_ppg.popleft()
                                    buffer_gsr.popleft()
                                    
                            except Exception as e_math:
                                print(f"ERROR MATEMÁTICO AL PROCESAR: {e_math}")
                                buffer_ppg.popleft() 
                                buffer_gsr.popleft()

                    except ValueError:
                        pass # Ignora tramas corruptas o incompletas del puerto serie
                        
                # Mantener la interfaz viva en todo momento
                interfaz.procesar_eventos()
                
    except serial.SerialException as e:
        print(f"Error abriendo el puerto serie: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nPrograma detenido por el usuario.")
        sys.exit(0)

if __name__ == '__main__':
    main()