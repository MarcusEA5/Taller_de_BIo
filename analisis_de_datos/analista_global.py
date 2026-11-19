import os
import glob
import numpy as np
import pandas as pd
from scipy import signal, stats
import matplotlib.pyplot as plt
import seaborn as sns

# Configuración estética general para gráficos de reporte (300 DPI)
sns.set_theme(style="whitegrid")
ORDEN_FASES = ['1. Reposo Basal', '2. Test Stroop', '3. Recuperación']


def normalizar_fase(nombre_fase):
    """Unifica nombres de fases (ej. '5. Recuperación' -> '3. Recuperación') e ignora pausas intermedias."""
    texto = str(nombre_fase).lower()
    if 'basal' in texto:
        return '1. Reposo Basal'
    if 'stroop' in texto:
        return '2. Test Stroop'
    if 'recuperaci' in texto:
        return '3. Recuperación'
    return None


def procesar_voluntario(ruta_csv, fs=200):
    """Aplica el pipeline DSP (Butterworth fase cero + Savitzky-Golay) en ventanas de 10 s (50% overlap)."""
    nombre_archivo = os.path.basename(ruta_csv)
    id_vol = nombre_archivo.split('_')[0]
    print(f"Procesando Voluntario {id_vol} ({nombre_archivo})...")

    df = pd.read_csv(ruta_csv, encoding='utf-8-sig')
    df['fase_norm'] = df['fase'].apply(normalizar_fase)
    df = df.dropna(subset=['fase_norm']).reset_index(drop=True)

    window_size = 10 * fs  # 2000 muestras (10 s)
    step_size = 5 * fs     # 1000 muestras (avance cada 5 s)
    b, a_filt = signal.butter(2, [0.5, 15], btype='bandpass', fs=fs)

    ventanas = []
    for start in range(0, len(df) - window_size + 1, step_size):
        w = df.iloc[start:start + window_size]

        # Descartar ventanas que cruzan un cambio de fase
        if w['fase_norm'].nunique() > 1:
            continue

        fase = w['fase_norm'].iloc[0]
        scl = w['gsr_uS'].mean()

        # Filtrado bidireccional de fase cero + 2da derivada Savitzky-Golay
        ppg_filt = signal.filtfilt(b, a_filt, -w['ppg_raw'].values)
        sdppg = signal.savgol_filter(ppg_filt, window_length=21, polyorder=3, deriv=2)

        # Detección de picos 'a' y valles 'b'
        picos_a, _ = signal.find_peaks(sdppg, distance=int(fs * 0.4), prominence=np.max(sdppg) * 0.3)

        # BPM estimado por ventana
        bpm = np.nan
        if len(picos_a) >= 2:
            rr_seg = np.diff(picos_a) / fs
            rr_validos = rr_seg[(rr_seg > 0.35) & (rr_seg < 1.5)]
            if len(rr_validos) > 0:
                bpm = 60.0 / np.median(rr_validos)

        ba_ratios = []
        search_w = int(fs * 0.15)
        for pa in picos_a:
            if pa + search_w < len(sdppg):
                val_a = sdppg[pa]
                val_b = np.min(sdppg[pa:pa + search_w])
                if val_a > 0 and val_b < 0:
                    ba_ratios.append(val_b / val_a)

        if len(ba_ratios) > 0:
            ventanas.append({
                'Voluntario': f"Vol {id_vol}",
                't_s': w['t_s'].iloc[window_size // 2],
                'fase': fase,
                'SCL_uS': scl,
                'Ratio_ba': np.median(ba_ratios),
                'BPM': bpm
            })

    df_vol = pd.DataFrame(ventanas).dropna(subset=['Ratio_ba', 'SCL_uS'])

    # Normalización intra-sujeto respecto a su propia mediana basal
    basal_vol = df_vol[df_vol['fase'] == '1. Reposo Basal']
    if not basal_vol.empty:
        scl_ref = basal_vol['SCL_uS'].median()
        ba_ref = basal_vol['Ratio_ba'].median()
        df_vol['Delta_SCL_pct'] = ((df_vol['SCL_uS'] - scl_ref) / scl_ref) * 100.0
        df_vol['Delta_ba'] = df_vol['Ratio_ba'] - ba_ref
    else:
        df_vol['Delta_SCL_pct'] = np.nan
        df_vol['Delta_ba'] = np.nan

    return df_vol


def construir_curva_promedio_temporal(df_global):
    """
    Alinea las fases de todos los voluntarios sobre una línea de tiempo estándar:
    Basal: 0-3 min | Stroop: 3-5 min | Recuperación: 5-10 min.
    Devuelve media y error estándar (SEM) punto a punto entre los 5 voluntarios.
    """
    esquema_fases = [
        ('1. Reposo Basal', 0.0, 3.0, 36),
        ('2. Test Stroop', 3.0, 5.0, 24),
        ('3. Recuperación', 5.0, 10.0, 60)
    ]

    filas_interp = []
    for vol, df_v in df_global.groupby('Voluntario'):
        for fase, t_ini, t_fin, n_pts in esquema_fases:
            sub = df_v[df_v['fase'] == fase].sort_values('t_s')
            if len(sub) < 2:
                continue

            # Progreso normalizado [0, 1] dentro de la fase
            t_norm_orig = (sub['t_s'] - sub['t_s'].min()) / (sub['t_s'].max() - sub['t_s'].min())
            t_grid_norm = np.linspace(0, 1, n_pts)
            t_grid_min = np.linspace(t_ini, t_fin, n_pts)

            interp_scl = np.interp(t_grid_norm, t_norm_orig, sub['Delta_SCL_pct'])
            interp_ba = np.interp(t_grid_norm, t_norm_orig, sub['Ratio_ba'])
            interp_dba = np.interp(t_grid_norm, t_norm_orig, sub['Delta_ba'])

            for tm, scl_v, ba_v, dba_v in zip(t_grid_min, interp_scl, interp_ba, interp_dba):
                filas_interp.append({
                    'Voluntario': vol,
                    'fase': fase,
                    't_min': tm,
                    'Delta_SCL_pct': scl_v,
                    'Ratio_ba': ba_v,
                    'Delta_ba': dba_v
                })

    df_interp = pd.DataFrame(filas_interp)
    resumen_t = df_interp.groupby(['fase', 't_min']).agg(
        SCL_mean=('Delta_SCL_pct', 'mean'),
        SCL_sem=('Delta_SCL_pct', lambda x: x.std(ddof=1) / np.sqrt(len(x))),
        ba_mean=('Ratio_ba', 'mean'),
        ba_sem=('Ratio_ba', lambda x: x.std(ddof=1) / np.sqrt(len(x))),
        dba_mean=('Delta_ba', 'mean'),
        dba_sem=('Delta_ba', lambda x: x.std(ddof=1) / np.sqrt(len(x))),
    ).reset_index().sort_values('t_min')

    return resumen_t


def graficar_todo(df_global, df_sujetos, resumen_t, carpeta_salida):
    os.makedirs(carpeta_salida, exist_ok=True)

    # ---------------------------------------------------------
    # GRÁFICO 1: Evolución Temporal Promedio (Media ± SEM, N=5)
    # ---------------------------------------------------------
    fig, ax1 = plt.subplots(figsize=(12, 6))

    c_scl = '#1f77b4'
    c_ba = '#d62728'

    # Sombrear las 3 fases normalizadas
    ax1.axvspan(0, 3, color='#d3d3d3', alpha=0.35, label='1. Reposo Basal')
    ax1.axvspan(3, 5, color='#ffcccb', alpha=0.40, label='2. Test Stroop')
    ax1.axvspan(5, 10, color='#add8e6', alpha=0.35, label='3. Recuperación')

    # Curva ΔSCL % (Eje izquierdo)
    ax1.plot(resumen_t['t_min'], resumen_t['SCL_mean'], color=c_scl, lw=2.5, label='ΔSCL promedio (%)')
    ax1.fill_between(
        resumen_t['t_min'],
        resumen_t['SCL_mean'] - resumen_t['SCL_sem'],
        resumen_t['SCL_mean'] + resumen_t['SCL_sem'],
        color=c_scl, alpha=0.2
    )
    ax1.set_xlabel('Tiempo Normalizado del Protocolo (minutos)')
    ax1.set_ylabel('Cambio en Conductancia ΔSCL respecto a Basal (%)', color=c_scl, fontweight='bold')
    ax1.tick_params(axis='y', labelcolor=c_scl)
    ax1.axhline(0, color=c_scl, ls='--', lw=0.8, alpha=0.5)

    # Curva Ratio b/a (Eje derecho)
    ax2 = ax1.twinx()
    ax2.plot(resumen_t['t_min'], resumen_t['ba_mean'], color=c_ba, lw=2.5, label='Ratio b/a promedio')
    ax2.fill_between(
        resumen_t['t_min'],
        resumen_t['ba_mean'] - resumen_t['ba_sem'],
        resumen_t['ba_mean'] + resumen_t['ba_sem'],
        color=c_ba, alpha=0.2
    )
    ax2.set_ylabel('Ratio de Rigidez Arterial b/a', color=c_ba, fontweight='bold')
    ax2.tick_params(axis='y', labelcolor=c_ba)

    # Leyenda combinada
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc='upper right', fontsize=9, frameon=True)

    plt.title('Evolución Temporal Promedio de los 5 Voluntarios (Media ± Error Estándar)', fontsize=13, fontweight='bold')
    fig.tight_layout()
    plt.savefig(os.path.join(carpeta_salida, '1_Evolucion_Promedio_Grupal.png'), dpi=300)
    plt.close()

    # ---------------------------------------------------------
    # GRÁFICO 2: Promedios por Fase + Trayectorias Individuales
    # ---------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))

    # Panel A: ΔSCL (%)
    sns.barplot(
        data=df_sujetos, x='fase', y='Delta_SCL_pct', order=ORDEN_FASES,
        errorbar='sd', capsize=0.12, color='#a6cee3', alpha=0.75, ax=axes[0]
    )
    sns.lineplot(
        data=df_sujetos, x='fase', y='Delta_SCL_pct', hue='Voluntario',
        marker='o', linewidth=1.8, markersize=7, ax=axes[0]
    )
    axes[0].axhline(0, color='gray', ls='--', lw=0.8)
    axes[0].set_title('A) Activación Simpática (ΔSCL % vs. Basal)', fontweight='bold')
    axes[0].set_xlabel('')
    axes[0].set_ylabel('Variación de Conductancia (%)')
    axes[0].legend(title='Sujeto', fontsize=8)

    # Panel B: Ratio b/a
    sns.barplot(
        data=df_sujetos, x='fase', y='Ratio_ba', order=ORDEN_FASES,
        errorbar='sd', capsize=0.12, color='#fb9a99', alpha=0.75, ax=axes[1]
    )
    sns.lineplot(
        data=df_sujetos, x='fase', y='Ratio_ba', hue='Voluntario',
        marker='o', linewidth=1.8, markersize=7, ax=axes[1]
    )
    axes[1].set_title('B) Rigidez Arterial Periférica (Ratio b/a)', fontweight='bold')
    axes[1].set_xlabel('')
    axes[1].set_ylabel('Ratio b/a (mediana por fase)')
    axes[1].legend(title='Sujeto', fontsize=8)

    plt.suptitle('Comparación Grupal (Barras = Media ± DE) y Respuesta Individual (N = 5)', fontsize=13, fontweight='bold')
    fig.tight_layout()
    plt.savefig(os.path.join(carpeta_salida, '2_Promedios_y_Trayectorias_Individuales.png'), dpi=300)
    plt.close()

    # ---------------------------------------------------------
    # GRÁFICO 3: Boxplots Consolidados (Todas las Ventanas)
    # ---------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))

    sns.boxplot(data=df_global, x='fase', y='Delta_SCL_pct', order=ORDEN_FASES, palette='Blues', ax=axes[0])
    axes[0].axhline(0, color='gray', ls='--', lw=0.8)
    axes[0].set_title('A) Distribución Global de ΔSCL (%)', fontweight='bold')
    axes[0].set_xlabel('')
    axes[0].set_ylabel('Cambio de Conductancia respecto a Basal (%)')

    sns.boxplot(data=df_global, x='fase', y='Ratio_ba', order=ORDEN_FASES, palette='Reds', ax=axes[1])
    axes[1].set_title('B) Distribución Global del Ratio b/a', fontweight='bold')
    axes[1].set_xlabel('')
    axes[1].set_ylabel('Ratio b/a')

    plt.suptitle('Distribución Consolidada de Todas las Ventanas (5 Voluntarios)', fontsize=13, fontweight='bold')
    fig.tight_layout()
    plt.savefig(os.path.join(carpeta_salida, '3_Boxplots_Grupales.png'), dpi=300)
    plt.close()

    # ---------------------------------------------------------
    # GRÁFICO 4: Cambio Neto en Stroop (Δb/a vs ΔSCL %) por Sujeto
    # ---------------------------------------------------------
    stroop_suj = df_sujetos[df_sujetos['fase'] == '2. Test Stroop'].sort_values('Voluntario')

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))

    axes[0].bar(stroop_suj['Voluntario'], stroop_suj['Delta_SCL_pct'], color='#1f77b4', alpha=0.85)
    axes[0].axhline(stroop_suj['Delta_SCL_pct'].mean(), color='black', ls='--', lw=1.5,
                    label=f"Promedio: {stroop_suj['Delta_SCL_pct'].mean():+.1f}%")
    axes[0].set_title('A) Incremento de Conductancia en Stroop', fontweight='bold')
    axes[0].set_ylabel('ΔSCL (%)')
    axes[0].legend()

    colores_ba = ['#d62728' if v > 0 else '#2ca02c' for v in stroop_suj['Delta_ba']]
    axes[1].bar(stroop_suj['Voluntario'], stroop_suj['Delta_ba'], color=colores_ba, alpha=0.85)
    axes[1].axhline(0, color='gray', lw=1)
    axes[1].axhline(stroop_suj['Delta_ba'].mean(), color='black', ls='--', lw=1.5,
                    label=f"Promedio: {stroop_suj['Delta_ba'].mean():+.3f}")
    axes[1].set_title('B) Cambio de Rigidez Δ(b/a) en Stroop\n(Rojo: vasoconstricción | Verde: índice inverso)', fontweight='bold')
    axes[1].set_ylabel('Δ(b/a) = Stroop - Basal')
    axes[1].legend()

    fig.tight_layout()
    plt.savefig(os.path.join(carpeta_salida, '4_Cambio_Neto_Stroop_por_Voluntario.png'), dpi=300)
    plt.close()


def ejecutar_estadistica(df_global, df_sujetos, carpeta_salida):
    print("\n" + "=" * 65)
    print("RESUMEN POR VOLUNTARIO (MEDIANAS POR FASE)")
    print("=" * 65)
    tabla_pivot = df_sujetos.pivot(index='Voluntario', columns='fase', values=['SCL_uS', 'Delta_SCL_pct', 'Ratio_ba', 'BPM'])
    print(tabla_pivot.round(3))

    # Guardar tabla resumen en CSV para copiar fácil a Word/Google Docs
    ruta_tabla = os.path.join(carpeta_salida, 'resumen_grupal_5_voluntarios.csv')
    df_sujetos.to_csv(ruta_tabla, index=False, encoding='utf-8-sig')

    print("\n" + "=" * 65)
    print("PROMEDIO GRUPAL DE LOS 5 VOLUNTARIOS (MEDIA ± DESVÍO ESTÁNDAR)")
    print("=" * 65)
    resumen_grupo = df_sujetos.groupby('fase')[['SCL_uS', 'Delta_SCL_pct', 'Ratio_ba', 'Delta_ba', 'BPM']].agg(['mean', 'std'])
    print(resumen_grupo.reindex(ORDEN_FASES).round(3))

    # Prueba t de Student para muestras emparejadas (N = 5 voluntarios)
    print("\n" + "=" * 65)
    print("PRUEBA T DE STUDENT EMPAREJADA (NIVEL SUJETO, N = 5)")
    print("=" * 65)
    piv_ba = df_sujetos.pivot(index='Voluntario', columns='fase', values='Ratio_ba').dropna()
    piv_scl = df_sujetos.pivot(index='Voluntario', columns='fase', values='Delta_SCL_pct').dropna()

    for var_nombre, piv in [('Ratio b/a', piv_ba), ('ΔSCL (%)', piv_scl)]:
        if '1. Reposo Basal' in piv.columns and '2. Test Stroop' in piv.columns:
            t_st, p_st = stats.ttest_rel(piv['1. Reposo Basal'], piv['2. Test Stroop'])
            print(f"{var_nombre:10s} | Basal vs. Stroop       -> t = {t_st:+.3f}, p = {p_st:.4f}")
        if '1. Reposo Basal' in piv.columns and '3. Recuperación' in piv.columns:
            t_rc, p_rc = stats.ttest_rel(piv['1. Reposo Basal'], piv['3. Recuperación'])
            print(f"{var_nombre:10s} | Basal vs. Recuperación -> t = {t_rc:+.3f}, p = {p_rc:.4f}")

    # Correlación de Pearson global usando variables normalizadas (evita sesgo de escala entre sujetos)
    df_corr = df_global.dropna(subset=['Delta_SCL_pct', 'Delta_ba'])
    r, p_r = stats.pearsonr(df_corr['Delta_SCL_pct'], df_corr['Delta_ba'])
    print("\n" + "=" * 65)
    print(f"CORRELACIÓN DE PEARSON GLOBAL (ΔSCL % vs. Δb/a): r = {r:+.3f}, p = {p_r:.5f}")
    print("=" * 65)


if __name__ == "__main__":
    # Resuelve las rutas automáticamente sin importar desde dónde ejecutes VS Code
    dir_actual = os.path.dirname(os.path.abspath(__file__))
    carpeta_csv = os.path.join(dir_actual, '..', 'registros_csv')
    carpeta_salida = os.path.join(dir_actual, 'resultados_grupales')
    os.makedirs(carpeta_salida, exist_ok=True)

    # Busca todos los archivos *_muestras.csv ordenados del 01 al 05
    archivos = sorted(glob.glob(os.path.join(carpeta_csv, '*_muestras.csv')))
    if not archivos:
        archivos = sorted(glob.glob(os.path.join(carpeta_csv, '*.csv')))

    if not archivos:
        print(f"No se encontraron archivos CSV en: {carpeta_csv}")
    else:
        print(f"Se encontraron {len(archivos)} archivos:\n  " + "\n  ".join(os.path.basename(a) for a in archivos))
        print("-" * 65)

        lista_dfs = [procesar_voluntario(a) for a in archivos]
        df_global = pd.concat(lista_dfs, ignore_index=True)

        # Agregación a nivel sujeto (1 valor por voluntario y por fase) para promedios y t-test emparejado
        df_sujetos = df_global.groupby(['Voluntario', 'fase']).agg(
            SCL_uS=('SCL_uS', 'median'),
            Delta_SCL_pct=('Delta_SCL_pct', 'median'),
            Ratio_ba=('Ratio_ba', 'median'),
            Delta_ba=('Delta_ba', 'median'),
            BPM=('BPM', 'median')
        ).reset_index()

        resumen_t = construir_curva_promedio_temporal(df_global)
        ejecutar_estadistica(df_global, df_sujetos, carpeta_salida)
        graficar_todo(df_global, df_sujetos, resumen_t, carpeta_salida)

        print(f"\nListo. Los 4 gráficos y la tabla CSV se guardaron en:\n{carpeta_salida}")