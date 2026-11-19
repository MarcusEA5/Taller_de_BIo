import pandas as pd
import numpy as np
from scipy import signal
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats
import os

def generar_reporte_individual(ruta_csv):
    nombre_archivo = os.path.basename(ruta_csv).replace('.csv', '')
    print(f"\n========================================")
    print(f"ANALIZANDO VOLUNTARIO: {nombre_archivo}")
    print(f"========================================\n")
    
    df = pd.read_csv(ruta_csv)
    fs = 200
    
    # Diseño del Filtro Butterworth Pasabanda (0.5 a 15 Hz)
    b, a_filt = signal.butter(2, [0.5, 15], btype='bandpass', fs=fs)

    # ---------------------------------------------------------
    # 1. GRÁFICOS DE DETALLE (Morfología de un latido en Reposo)
    # ---------------------------------------------------------
    # Tomamos 3 segundos de la fase basal para mostrar cómo trabaja el algoritmo
    df_basal = df[df['fase'] == '1. Reposo Basal'].iloc[fs*10 : fs*13] 
    
    t_detalle = df_basal['t_s'].values
    ppg_crudo_det = df_basal['ppg_raw'].values
    ppg_filt_det = signal.filtfilt(b, a_filt, -ppg_crudo_det)
    sdppg_det = signal.savgol_filter(ppg_filt_det, window_length=21, polyorder=3, deriv=2)
    
    # Gráfico 1: PPG Crudo vs Filtrado
    plt.figure(figsize=(10, 5))
    plt.subplot(2, 1, 1)
    plt.plot(t_detalle, ppg_crudo_det, color='gray')
    plt.title('Señal PPG Cruda (Sensor MAX30102)')
    plt.subplot(2, 1, 2)
    plt.plot(t_detalle, ppg_filt_det, color='black')
    plt.title('Señal PPG Filtrada (Fase Cero, 0.5 - 15 Hz)')
    plt.tight_layout()
    plt.savefig(f'1_Filtro_{nombre_archivo}.png', dpi=300)
    plt.close()

    # Gráfico 2: SDPPG y Puntos Fiduciarios (a, b, c, d, e)
    plt.figure(figsize=(10, 4))
    plt.plot(t_detalle, sdppg_det, color='black', label='SDPPG')
    
    # Algoritmo de detección visual para el latido de ejemplo
    picos_a, _ = signal.find_peaks(sdppg_det, distance=fs*0.4, prominence=np.max(sdppg_det)*0.2)
    for pa in picos_a:
        try:
            # Buscar b, c, d, e secuencialmente
            ib = pa + np.argmin(sdppg_det[pa : pa + int(fs*0.15)])
            ic = ib + np.argmax(sdppg_det[ib : ib + int(fs*0.10)])
            id_ = ic + np.argmin(sdppg_det[ic : ic + int(fs*0.10)])
            ie = id_ + np.argmax(sdppg_det[id_ : id_ + int(fs*0.15)])
            
            # Pintar los puntos con los colores de la GUI
            plt.plot(t_detalle[pa], sdppg_det[pa], 'bo', label='a (Sístole inicial)' if pa==picos_a[0] else "")
            plt.plot(t_detalle[ib], sdppg_det[ib], 'ro', label='b (Rigidez temprana)' if pa==picos_a[0] else "")
            plt.plot(t_detalle[ic], sdppg_det[ic], 'go', label='c' if pa==picos_a[0] else "")
            plt.plot(t_detalle[id_], sdppg_det[id_], 'yo', label='d (Onda refleja)' if pa==picos_a[0] else "")
            plt.plot(t_detalle[ie], sdppg_det[ie], 'mo', label='e (Incisura dícrota)' if pa==picos_a[0] else "")
        except ValueError:
            pass # Si el latido está cortado en el borde, lo ignora

    plt.title('Segunda Derivada (SDPPG) y Puntos Fiduciarios')
    plt.xlabel('Tiempo (s)')
    plt.legend(loc='upper right', fontsize='small')
    plt.tight_layout()
    plt.savefig(f'2_Puntos_Takazawa_{nombre_archivo}.png', dpi=300)
    plt.close()

    # ---------------------------------------------------------
    # 2. PROCESAMIENTO COMPLETO POR VENTANAS (10s, 50% overlap)
    # ---------------------------------------------------------
    window_size = 10 * fs
    step_size = 5 * fs
    resultados = []

    for start in range(0, len(df) - window_size, step_size):
        window_df = df.iloc[start:start+window_size]
        if len(window_df['fase'].unique()) > 1:
            continue # Ignorar ventanas que cruzan cambios de fase
            
        fase = window_df['fase'].iloc[0]
        scl = window_df['gsr_uS'].mean()
        
        ppg_crudo = window_df['ppg_raw'].values
        ppg_filt = signal.filtfilt(b, a_filt, -ppg_crudo)
        sdppg = signal.savgol_filter(ppg_filt, window_length=21, polyorder=3, deriv=2)
        
        picos_a, _ = signal.find_peaks(sdppg, distance=fs*0.4, prominence=np.max(sdppg)*0.3)
        ba_ratios = []
        
        for pa in picos_a:
            search_window = int(fs * 0.15)
            if pa + search_window < len(sdppg):
                val_a = sdppg[pa]
                idx_b = pa + np.argmin(sdppg[pa:pa+search_window])
                val_b = sdppg[idx_b]
                if val_a > 0 and val_b < 0:
                    ba_ratios.append(val_b / val_a)
        
        if len(ba_ratios) > 0:
            resultados.append({
                't_s': window_df['t_s'].iloc[window_size//2],
                'fase': fase,
                'SCL_uS': scl,
                'Ratio_ba': np.median(ba_ratios)
            })

    df_res = pd.DataFrame(resultados).dropna()

    # ---------------------------------------------------------
    # 3. GRÁFICOS DE RESULTADOS EXPERIMENTALES
    # ---------------------------------------------------------
    # Gráfico 3: Evolución Bimodal (GSR vs Rigidez)
    fig, ax1 = plt.subplots(figsize=(12, 6))
    
    color_scl = 'tab:blue'
    ax1.set_xlabel('Tiempo (s)')
    ax1.set_ylabel('Conductancia SCL (µS)', color=color_scl)
    ax1.plot(df_res['t_s'], df_res['SCL_uS'], color=color_scl, linewidth=2)
    ax1.tick_params(axis='y', labelcolor=color_scl)

    ax2 = ax1.twinx()
    color_ba = 'tab:red'
    ax2.set_ylabel('Ratio Rigidez b/a', color=color_ba)
    ax2.plot(df_res['t_s'], df_res['Ratio_ba'], color=color_ba, linewidth=2, marker='o')
    ax2.tick_params(axis='y', labelcolor=color_ba)

    colores_fase = {'1. Reposo Basal': '#d3d3d3', '2. Test Stroop': '#ffcccb', '5. Recuperación': '#add8e6'}
    for f in df_res['fase'].unique():
        datos_f = df_res[df_res['fase'] == f]
        if not datos_f.empty:
            ax1.axvspan(datos_f['t_s'].min(), datos_f['t_s'].max(), alpha=0.3, color=colores_fase.get(f, 'white'), label=f)

    plt.title(f'Evolución Bimodal: SCL y Ratio b/a - {nombre_archivo}')
    fig.tight_layout()
    plt.savefig(f'3_Evolucion_Bimodal_{nombre_archivo}.png', dpi=300)
    plt.close()

    # Gráfico 4: Boxplot de Distribución
    plt.figure(figsize=(8, 6))
    sns.boxplot(x='fase', y='Ratio_ba', data=df_res, order=['1. Reposo Basal', '2. Test Stroop', '5. Recuperación'])
    plt.title(f'Distribución del Ratio b/a por Fase - {nombre_archivo}')
    plt.ylabel('Ratio b/a')
    plt.xlabel('Fase del Experimento')
    plt.savefig(f'4_Distribucion_Boxplot_{nombre_archivo}.png', dpi=300)
    plt.close()

    # ---------------------------------------------------------
    # 4. ESTADÍSTICA INFERENCIAL
    # ---------------------------------------------------------
    print("--- PROMEDIOS POR FASE ---")
    print(df_res.groupby('fase')[['SCL_uS', 'Ratio_ba']].mean())

    basal = df_res[df_res['fase'] == '1. Reposo Basal']['Ratio_ba']
    stroop = df_res[df_res['fase'] == '2. Test Stroop']['Ratio_ba']
    
    if not basal.empty and not stroop.empty:
        t_stat, p_val = stats.ttest_ind(basal, stroop, equal_var=False)
        print(f"\n[Prueba T de Student] Basal vs Stroop -> t: {t_stat:.3f}, p-value: {p_val:.5f}")
        if p_val < 0.05:
            print("  >> CONCLUSIÓN: El aumento de rigidez (cambio en b/a) es ESTADÍSTICAMENTE SIGNIFICATIVO.")
        else:
            print("  >> CONCLUSIÓN: El cambio en la rigidez NO es estadísticamente significativo.")

    corr, p_corr = stats.pearsonr(df_res['SCL_uS'], df_res['Ratio_ba'])
    print(f"\n[Correlación de Pearson] GSR (SCL) vs Rigidez (b/a) -> r: {corr:.3f}, p-value: {p_corr:.5f}")
    if p_corr < 0.05:
        print("  >> CONCLUSIÓN: Existe una correlación significativa entre la transpiración y la vasoconstricción.")

    print(f"\nProceso finalizado. Se generaron 4 imágenes en tu carpeta.")

# ==========================================
# EJECUCIÓN (Cambia aquí el nombre de tu archivo)
# ==========================================
if __name__ == "__main__":
    archivo_a_analizar = "./registros_csv/05_2026-11-08_22-53-00_muestras.csv"
    generar_reporte_individual(archivo_a_analizar)