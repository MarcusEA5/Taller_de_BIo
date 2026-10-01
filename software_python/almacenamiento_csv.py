import csv
import os
from datetime import datetime

class GestorCSV:
    def __init__(self, id_sujeto="Voluntario_Prueba", edad="N/D", genero="N/D"):
        # Crea la carpeta si no existe
        if not os.path.exists("registros_csv"):
            os.makedirs("registros_csv")
            
        # Genera un nombre de archivo único con la fecha y hora
        timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.ruta_archivo = f"registros_csv/{id_sujeto}_{timestamp_str}.csv"
        
        # Crea el archivo y escribe los encabezados
        with open(self.ruta_archivo, mode='w', newline='') as f:
            writer = csv.writer(f)
            # 1. Metadatos demográficos (Edad y Género)
            writer.writerow(["# EDAD:", edad, "# GENERO:", genero])
            # 2. Encabezado de columnas
            writer.writerow([
                "Timestamp", "Fase_Experimento", "PPG_Crudo", "PPG_Filtrado", 
                "GSR_Crudo", "BPM", "Ratio_ba", "Aging_Index", "SCL_MicroSiemens"
            ])
            
    def guardar_fila(self, fase, ppg_crudo, ppg_filtrado="", gsr_crudo=0.0, bpm="", ratio_ba="", ai="", scl=""):
        # Timestamp con precisión de milisegundos
        tiempo_actual = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        
        # Modo 'a' (append) para añadir datos sin sobreescribir
        with open(self.ruta_archivo, mode='a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                tiempo_actual, fase, ppg_crudo, ppg_filtrado, gsr_crudo, 
                bpm, ratio_ba, ai, scl
            ])