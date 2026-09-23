import serial
import sys
import time
from collections import deque

# Importas tus módulos separados
import graficador
import filtro
import sdppg
import procesamiento 
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
    
    print("Iniciando monitor bimodal PPG + GSR... Presione Ctrl+C para salir.")
    
    try:
        with serial.Serial('COM11', 115200, timeout=1) as puerto_serial:
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
                        elif len(datos) >= 2:
                            ppg_crudo, gsr_crudo = datos[0] * -1, datos[1]
                            
                        # Llenamos ambos búferes
                        buffer_ppg.append(ppg_crudo)
                        buffer_gsr.append(gsr_crudo)
                        
                        # Actualizamos el osciloscopio rápido superior (PPG crudo)
                        interfaz.actualizar_tiempo_real(ppg_crudo, gsr_crudo)

                        # --- CONTROL DINÁMICO DE GRABACIÓN POR BOTÓN ---
                        estado_actual_boton = interfaz.is_recording
                        
                        if estado_actual_boton and not grabando_anterior:
                            # Al hacer clic en grabar, se abre el diálogo de Edad y Género
                            logger = almacenamiento_csv.GestorCSV(
                                id_sujeto="Voluntario_Prueba", 
                                edad=getattr(interfaz, 'edad_sujeto', "N/D"), 
                                genero=getattr(interfaz, 'genero_sujeto', "N/D")
                            )
                            print("\n>>> [GRABACIÓN INICIADA] Archivo CSV creado con metadatos.")
                            
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
                                ratio_ba, aging_index, pts_x, pts_y, colores, bpm = procesamiento.extraer_puntos_fiduciarios(segunda_derivada, fs=FRECUENCIA_MUESTREO)

                                # Procesamiento del bloque de GSR (Extracción de SCL)
                                scl_valor, _ = procesamiento.procesar_gsr_ventana(list(buffer_gsr), fs=FRECUENCIA_MUESTREO)

                                if ratio_ba is not None:
                                    # Actualizamos gráficos y el panel izquierdo con los biomarcadores (incluyendo SCL)
                                    interfaz.actualizar_procesado(
                                        ppg_limpio, segunda_derivada, ratio_ba, aging_index, scl_valor, 
                                        puntos_x=pts_x, puntos_y=pts_y, colores=colores, bpm=bpm
                                    )

                                    # Si estamos grabando, guardamos la fila con los biomarcadores calculados
                                    if logger is not None:
                                        logger.guardar_fila(
                                            fase=getattr(interfaz, 'fase_actual', "Sin_Fase"),
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
        print(f"Error abriendo el puerto serie COM11: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nPrograma detenido por el usuario.")
        sys.exit(0)

if __name__ == '__main__':
    main()