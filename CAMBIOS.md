# Correcciones al código del proyecto (firmware + Python)

## Cómo aplicarlo
1. En `software_python/` **borrá** `filtro.py` y `sdppg.py` (su función ahora está en `procesamiento_ppg.py`) y
   renombrá `requeriments.txt` → `requirements.txt` (usá el nuevo).
2. Copiá todos los archivos de este paquete sobre tu repo y flasheá `firmware_esp32/src/main.cpp`.
3. `pip install -r requirements.txt`, luego `python test_pipeline.py` (debe dar 15/15) y `python main.py`.
4. Sacá `.venv/`, `venv/` y `__pycache__/` del repositorio (el `.gitignore` incluido ya los excluye).

## Qué se corrigió

| Problema | Solución | Archivo |
|---|---|---|
| Muestreo con `delay(4)`: fs real entre 203 y 268 Hz, espaciado irregular, muestras del sensor descartadas | Muestreo marcado por el FIFO del MAX30102 a **200 Hz nativos** (250 Hz no existe en este sensor); contador `n` y `micros()` en cada línea | `main.cpp` |
| Líneas cortadas o alteradas del USB podían meter picos falsos | Checksum XOR por línea; Python descarta las que no coinciden | `main.cpp`, `adquisicion.py` |
| Si faltaba el sensor, el firmware quedaba mudo | Mensaje `# ERROR` cada segundo | `main.cpp` |
| La GUI leía el puerto y redibujaba por cada muestra, frenando todo; el CSV se abría y cerraba por muestra | Hilo lector + cola + QTimer; archivos abiertos una vez, volcado cada 1 s | `adquisicion.py`, `main.py`, `almacenamiento_csv.py` |
| El tiempo dependía del reloj de la PC | Tiempo = `n / fs`; `ControlTiempo` compara con `micros()` y avisa si la fs se desvía >3 % o el firmware y `config.FS` no coinciden | `adquisicion.py` |
| Pérdida de muestras corrompía la derivada | Un salto del contador reinicia la ventana | `pipeline.py` |
| Detector de a-e sin umbral de prominencia, con media y sin validar | Savitzky-Golay para derivar; pico sistólico con período por autocorrelación; 'a' anclada a la subida del pulso; b-e con ventanas fisiológicas y prominencia mínima; validación por latido (b/a plausible, amplitud, RR, forma vs plantilla); mediana por ventana | `procesamiento_ppg.py` |
| Ventanas solapadas duplicaban latidos y los bordes del filtro contaminaban | Solo se confirman los latidos de la mitad central de cada ventana: cada latido se guarda una vez | `pipeline.py` |
| Conversión GSR con 3,3 V/4095 aunque el ADC (11 dB) satura en ~2,5 V; divisor extra ignorado | ADC calibrado en mV desde el firmware; parámetros del circuito en `config.py`; **herramienta de calibración con resistencias patrón** | `procesamiento_gsr.py`, `calibrar_gsr.py` |
| Edad vascular de ~58 años en un sujeto de 22 | Casi todo venía del detector viejo (ahora da ~22). Igual, **la ecuación de Takazawa no está validada para este equipo**: se oculta por defecto y se guarda en `meta.json` como "sin validar" | `edad_vascular.py`, `config.py` |
| Fases de ~10 s (1 o 2 ventanas), sin forma de controlar la duración | Cuenta regresiva por fase con duración mínima y confirmación para cortarla antes (duraciones **provisorias**, definilas con el asesor); las ventanas que cruzan dos fases se marcan `Transicion` | `config.py`, `graficador.py` |
| Planilla sin mano dominante, medicación, cafeína, etc.; edad desde 15 años; archivos siempre `Voluntario_Prueba` | Planilla ampliada, solo ≥18 años, consentimiento obligatorio, **código de sujeto** seudonimizado en el nombre de archivo | `graficador.py`, `almacenamiento_csv.py` |
| CSV sin UTF-8; `ppg_filtrado` guardaba el punto del borde del filtro | UTF-8 con BOM; se guardan latidos y ventanas por separado; la configuración usada queda en `*_meta.json` | `almacenamiento_csv.py` |
| Estadística sobre ventanas solapadas (pseudo-replicación) | `analisis_offline.py`: un valor por sujeto y fase, t pareada + Wilcoxon, Cohen dz, Holm, correlación | `analisis_offline.py` |

## Archivos que genera cada sesión
`<id>_<fecha>_muestras.csv` (crudo a 200 Hz) · `_latidos.csv` (cada latido, con a-e, b/a, AI, validez y motivo)
· `_ventanas.csv` (BPM, b/a, AI, SCL, SCR, calidad) · `_meta.json` (planilla + configuración + cierre).
Reprocesar con otros parámetros: `python analisis_offline.py archivo_muestras.csv`; grupo: `--grupo registros_csv`.

## Antes de medir voluntarios (pendiente, no se resuelve con código)
1. **Circuito GSR.** Con la fórmula de su código la piel recibe ~2,4 V (lo habitual es ~0,5 V) y, si su resistencia baja
   de ~130 kΩ (sudor), la corriente pasa los 10 µA declarados (16,7 µA con los electrodos en corto). Hay que reducir la
   excitación. Después, calibrar con `python calibrar_gsr.py 100000 220000 470000 1000000` y pegar el resultado en `config.py`.
2. **Verificar la frecuencia cardíaca** contra un oxímetro o reloj comercial en el mismo momento.
3. **Mirar la barra de estado**: debe decir `fs = 200.x Hz`. Si muestra pérdida de muestras, algo está frenando el USB.
4. **Fijar los parámetros** (`SG_VENTANA_MS`, banda del filtro) *antes* de medir y reportarlos en métodos:
   cambian el valor absoluto de b/a y AI (ver abajo).
5. **Medir voluntarios de varias edades**: es la única validación posible sin VOP (que b/a y AI crezcan con la edad).
6. **Actualizar el anteproyecto/informe**: RF1 (250 → 200 Hz), RF3 y RNF4 (el DSP corre en la PC, no en el firmware),
   KR3 (el Savitzky-Golay recién ahora está implementado) y la definición única del índice (b/a y AI).

## Lo que se verificó y lo que NO

**Verificado** (`python test_pipeline.py`, 15 tests, y corridas con su sesión real del 27/10):
- El protocolo serie (checksum, contador) con el `main.cpp` compilado con stubs y leído por `parsear_linea`.
- BPM exacto a 50-100 lpm con ruido; el ruido puro no produce latidos válidos; una onda diastólica alta no duplica los lpm.
- Cada latido se informa una sola vez; las ventanas que cruzan un hueco de muestras se descartan.
- Flujo completo `main.py → orquestador → 4 archivos → cierre` (con la interfaz simulada).
- Con su sesión real (reposo basal, un sujeto de 22 años): b/a ≈ −0,79, AI ≈ −1,0, 70 lpm, ~86-88 % de latidos válidos.

**No verificado** (no hay hardware ni PyQt en el entorno donde se escribió):
- El firmware **no se compiló con PlatformIO ni se probó en la placa** (solo con stubs); revisá si `getFIFOIR()`/`check()` se
  comportan como esperan en su versión de la librería.
- La interfaz **no se ejecutó con PyQt real** (solo con stubs); pueden aparecer detalles de API o de aspecto.

**Limitaciones del método (importantes para el informe):**
- El suavizado atenúa las ondas angostas de la SDPPG: con los valores por defecto, en señales sintéticas de verdad conocida,
  **b/a medido ≈ 1,28 × real + 0,07** (más negativo que el real). La respuesta es lineal (r = 0,9999), así que sirve para
  comparar condiciones (Δ b/a), pero el valor absoluto depende de `SG_VENTANA_MS`: con ventanas más cortas las ondas
  c-d-e se confunden con ruido y el AI cambia mucho.
- Que el AI de un solo sujeto dé ~22 años no valida la ecuación: es **n = 1**.
