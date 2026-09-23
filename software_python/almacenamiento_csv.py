import csv
import os
from datetime import datetime

class GestorCSV:
    def __init__(self, id_sujeto="prueba"):
        # Crear la carpeta de registros si no existe
        if not os.path.exists("registros_csv"):
            os.makedirs("registros_csv")
            
        # Nombre de archivo único con fecha y hora
        timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.ruta_archivo = f"registros_csv/{id_sujeto}_{timestamp_str}.csv"
        
        # Inicializar el archivo y escribir losencabezados
        with open(self.ruta_archivo, mode='w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Timestamp", "PPG_Crudo", "PPG_Filtrado", "GSR_Crudo", 
                "BPM", "Ratio_ba", "Aging_Index", "SCL"
            ])
            
    def guardar_fila(self, ppg_crudo, ppg_filtrado, gsr_crudo, bpm="", ratio_ba="", ai="", scl=""):
        """
        Guarda una muestra en el CSV. 
        Los biomarcadores se pasan vacíos si no coinciden con el cierre de la ventana.
        """
        tiempo_actual = datetime.now().strftime("%H:%M:%S.%f")[:-3] # Hora con milisegundos
        
        with open(self.ruta_archivo, mode='a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                tiempo_actual, ppg_crudo, ppg_filtrado, gsr_crudo, 
                bpm, ratio_ba, ai, scl
            ])