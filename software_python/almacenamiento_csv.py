import csv
import os
from datetime import datetime

class GestorCSV:
    def __init__(self, id_sujeto="Voluntario_Prueba", datos_medicos=None):
        if not os.path.exists("registros_csv"):
            os.makedirs("registros_csv")
            
        timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.ruta_archivo = f"registros_csv/{id_sujeto}_{timestamp_str}.csv"
        
        with open(self.ruta_archivo, mode='w', newline='') as f:
            writer = csv.writer(f)
            # 1. Escribimos la anamnesis (Metadatos) al inicio
            writer.writerow(["### ANAMNESIS DEL VOLUNTARIO ###"])
            if datos_medicos:
                for clave, valor in datos_medicos.items():
                    writer.writerow([f"# {clave}:", valor])
            writer.writerow([]) # Fila en blanco para separar
            
            # 2. Encabezado de columnas de datos
            writer.writerow([
                "Timestamp", "Fase_Experimento", "PPG_Crudo", "PPG_Filtrado", 
                "GSR_Crudo", "BPM", "Ratio_ba", "Aging_Index", "SCL_MicroSiemens"
            ])
            
    def guardar_fila(self, fase, ppg_crudo, ppg_filtrado="", gsr_crudo=0.0, bpm="", ratio_ba="", ai="", scl=""):
        tiempo_actual = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        with open(self.ruta_archivo, mode='a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                tiempo_actual, fase, ppg_crudo, ppg_filtrado, gsr_crudo, 
                bpm, ratio_ba, ai, scl
            ])