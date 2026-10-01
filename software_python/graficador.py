import pyqtgraph as pg
from pyqtgraph.Qt import QtWidgets, QtCore
import numpy as np

class Graficador:
    def __init__(self):
        # 1. Inicializar la aplicación Qt
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

        # 2. Crear la ventana principal interactiva con Layout Horizontal
        self.win = QtWidgets.QWidget()
        self.win.setWindowTitle("Monitor Hemodinámico PPG + GSR")
        self.win.resize(1200, 800)
        self.win.setStyleSheet("background-color: black;")

        # Dividimos la pantalla: Izquierda (Panel de control) | Derecha (Gráficos)
        self.layout_principal = QtWidgets.QHBoxLayout(self.win)

        # --- PANEL IZQUIERDO (Control e Interfaz) ---
        self.widget_izq = QtWidgets.QWidget()
        self.layout_izq = QtWidgets.QVBoxLayout(self.widget_izq)
        self.layout_izq.setContentsMargins(0, 0, 0, 0)

        # Panel de Biomarcadores
        self.panel_texto = QtWidgets.QLabel("Esperando\nventana de 10s...")
        self.panel_texto.setStyleSheet("color: white; font-family: Arial; padding: 10px;")
        self.panel_texto.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        self.layout_izq.addWidget(self.panel_texto)

        # --- ETIQUETA DE ESTADO DE MEDICIÓN ---
        self.lbl_estado = QtWidgets.QLabel("ESTADO: EN ESPERA")
        self.lbl_estado.setStyleSheet("color: #f39c12; font-weight: bold; font-size: 14pt; padding: 5px;")
        self.lbl_estado.setAlignment(QtCore.Qt.AlignCenter)
        self.layout_izq.addWidget(self.lbl_estado)

        # --- BOTONES DE CONTROL DE PRUEBA ---
        self.btn_comenzar = QtWidgets.QPushButton("▶ COMENZAR PRUEBA")
        self.btn_comenzar.setStyleSheet("""
            QPushButton { background-color: #27ae60; color: white; font-size: 12pt; font-weight: bold; padding: 10px; border-radius: 5px; }
            QPushButton:hover { background-color: #2ecc71; }
        """)
        self.btn_comenzar.clicked.connect(self.iniciar_prueba)
        self.layout_izq.addWidget(self.btn_comenzar)

        self.btn_finalizar = QtWidgets.QPushButton("⏹ FINALIZAR PRUEBA")
        self.btn_finalizar.setStyleSheet("""
            QPushButton { background-color: #c0392b; color: white; font-size: 12pt; font-weight: bold; padding: 10px; border-radius: 5px; }
            QPushButton:disabled { background-color: #7f8c8d; color: #bdc3c7; }
        """)
        self.btn_finalizar.setEnabled(False) # Arranca deshabilitado
        self.btn_finalizar.clicked.connect(self.detener_prueba)
        self.layout_izq.addWidget(self.btn_finalizar)

        # --- BOTONERA DE FASES DEL EXPERIMENTO ---
        self.label_fases = QtWidgets.QLabel("<b>Fases del Test:</b>")
        self.label_fases.setStyleSheet("color: #aaaaaa; font-size: 10pt; margin-top: 10px;")
        self.layout_izq.addWidget(self.label_fases)

        self.fases_botones = {}
        nombres_fases = ["1. Reposo Basal", "2. Test Stroop", "3. Pausa", "4. Aim Trainer", "5. Recuperación"]
        
        for nombre in nombres_fases:
            btn = QtWidgets.QPushButton(nombre)
            btn.setEnabled(False) # Apagados hasta que empiece la prueba
            btn.setCheckable(True)
            btn.setStyleSheet("""
                QPushButton { background-color: #34495e; color: white; font-size: 9pt; padding: 5px; margin: 2px; border-radius: 4px; }
                QPushButton:disabled { background-color: #1a252f; color: #555555; }
                QPushButton:checked { background-color: #2980b9; color: white; font-weight: bold; }
            """)
            btn.clicked.connect(lambda checked, n=nombre, b=btn: self.seleccionar_fase(n, b))
            self.layout_izq.addWidget(btn)
            self.fases_botones[nombre] = btn

        self.widget_izq.setFixedWidth(280) # Ancho fijo para no aplastar los gráficos
        self.layout_principal.addWidget(self.widget_izq)

        # Variables de estado internas
        self.is_recording = False
        self.fase_actual = "Inactivo"
        self.edad_vascular_fija = None
        self.edad_sujeto = "N/D"
        self.genero_sujeto = "N/D"

        # --- PANEL DERECHO (Gráficos) ---
        self.graficos = pg.GraphicsLayoutWidget()
        self.layout_principal.addWidget(self.graficos)

        # Fila 1: Gráfico en tiempo real (Señal cruda)
        self.plot_raw = self.graficos.addPlot(title="PPG Crudo (Tiempo Real rápido)")
        self.plot_raw.showGrid(x=True, y=True)
        self.curve_raw = self.plot_raw.plot(pen=pg.mkPen('y', width=2))
        self.plot_raw.setMouseEnabled(x=False, y=False)
        self.graficos.nextRow()

        # Fila 2: Gráfico de ventana procesada (Estático, actualiza cada 10s)
        self.plot_filt = self.graficos.addPlot(title="PPG Filtrado (Ventana de 10s)")
        self.plot_filt.showGrid(x=True, y=True)
        self.curve_filt = self.plot_filt.plot(pen=pg.mkPen('g', width=2))
        self.graficos.nextRow()

        # Fila 3: Gráfico de SDPPG con Puntos Fiduciarios (Analítico de 10s)
        self.plot_sdppg = self.graficos.addPlot(title="Segunda Derivada (SDPPG) y Puntos Fiduciarios")
        self.plot_sdppg.showGrid(x=True, y=True)
        self.curve_sdppg = self.plot_sdppg.plot(pen=pg.mkPen('c', width=2))

        # Capa interactiva para dibujar los puntos (a, b, c, d, e)
        self.puntos_fiduciarios = pg.ScatterPlotItem(size=12, pen=pg.mkPen(None))
        self.plot_sdppg.addItem(self.puntos_fiduciarios)

        # Búfer interno exclusivo para el osciloscopio rápido
        self.tamano_buffer_rt = 750
        self.datos_rt_raw = np.zeros(self.tamano_buffer_rt)

        self.win.show()

    def iniciar_prueba(self):
        # Pedimos los metadatos al iniciar
        edad, ok1 = QtWidgets.QInputDialog.getInt(self.win, "Datos del Sujeto", "Edad del Voluntario:", 22, 10, 100, 1)
        self.edad_sujeto = str(edad) if ok1 else "N/D"
        
        genero, ok2 = QtWidgets.QInputDialog.getItem(self.win, "Datos del Sujeto", "Género:", ["Masculino", "Femenino", "Otro"], 0, False)
        self.genero_sujeto = genero if ok2 else "N/D"

        # Actualizamos variables y la interfaz
        self.is_recording = True
        self.fase_actual = "Inactivo"
        self.lbl_estado.setText("ESTADO: GRABANDO...")
        self.lbl_estado.setStyleSheet("color: #2ecc71; font-weight: bold; font-size: 14pt; padding: 5px;")
        
        self.btn_comenzar.setEnabled(False)
        self.btn_finalizar.setEnabled(True)
        
        # Habilitar los botones de fases y resetearlos
        for btn in self.fases_botones.values():
            btn.setChecked(False)
            btn.setEnabled(True)

    def detener_prueba(self):
        self.is_recording = False
        self.fase_actual = "Inactivo"
        self.lbl_estado.setText("ESTADO: FINALIZADO")
        self.lbl_estado.setStyleSheet("color: #e74c3c; font-weight: bold; font-size: 14pt; padding: 5px;")
        
        self.btn_comenzar.setEnabled(True)
        self.btn_finalizar.setEnabled(False)
        
        # Deshabilitar los botones de fases
        for btn in self.fases_botones.values():
            btn.setChecked(False)
            btn.setEnabled(False)

    def seleccionar_fase(self, nombre_fase, boton):
        self.fase_actual = nombre_fase
        # Desmarcamos los demás botones
        for nom, btn in self.fases_botones.items():
            if nom != nombre_fase:
                btn.setChecked(False)
                
        # Marcamos y deshabilitamos el presionado para evitar clics dobles accidentales
        boton.setChecked(True)
        boton.setEnabled(False)

    def actualizar_tiempo_real(self, ppg_raw, gsr_microsiemens=0.0):
        self.datos_rt_raw[:-1] = self.datos_rt_raw[1:]
        self.datos_rt_raw[-1] = ppg_raw
        self.curve_raw.setData(self.datos_rt_raw)

    def actualizar_procesado(self, ppg_filtrado, sdppg, ratio_ba, ai, scl, puntos_x, puntos_y, colores, bpm):
        if ppg_filtrado is not None and sdppg is not None:
            self.curve_filt.setData(ppg_filtrado)
            self.curve_sdppg.setData(sdppg)

        if puntos_x is not None and puntos_y is not None and colores is not None:
            self.puntos_fiduciarios.setData(x=puntos_x, y=puntos_y, brush=colores)
        else:
            self.puntos_fiduciarios.clear()

        if ratio_ba is not None and ai is not None and bpm is not None:
            # Lógica visual para la Edad Vascular
            if self.edad_vascular_fija is not None:
                texto_edad = f"<span style='font-size: 26pt; color: #00FFFF;'>{self.edad_vascular_fija:.1f} años</span>"
            else:
                texto_edad = f"<span style='font-size: 14pt; color: #aaaaaa;'>Calculando basal...</span>"

            texto = (
                f"<b style='color: #FFFFFF; font-size: 16pt;'>Frec. Cardíaca:</b><br>"
                f"<span style='font-size: 32pt; color: #FFFFFF;'>{bpm:.0f} BPM</span><br><br><br>"

                f"<b style='color: #00FF00; font-size: 16pt;'>Rigidez (b/a):</b><br>"
                f"<span style='font-size: 26pt; color: #00FF00;'>{ratio_ba:.3f}</span><br><br><br>"

                f"<b style='color: #00FFFF; font-size: 16pt;'>Edad Vascular:</b><br>"
                f"{texto_edad}<br><br><br>"

                f"<b style='color: #FFA500; font-size: 16pt;'>GSR (SCL):</b><br>"
                f"<span style='font-size: 26pt; color: #FFA500;'>{scl:.2f} µS</span>"
            )
            self.panel_texto.setText(texto)

    def procesar_eventos(self):
        self.app.processEvents()