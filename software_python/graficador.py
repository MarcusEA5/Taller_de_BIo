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

        # --- PANEL IZQUIERDO (Texto + Botón) ---
        self.widget_izq = QtWidgets.QWidget()
        self.layout_izq = QtWidgets.QVBoxLayout(self.widget_izq)
        self.layout_izq.setContentsMargins(0, 0, 0, 0)

        self.panel_texto = QtWidgets.QLabel("Adquiriendo\nventana de 10s...")
        self.panel_texto.setStyleSheet("color: white; font-family: Arial; padding: 10px;")
        self.panel_texto.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        self.layout_izq.addWidget(self.panel_texto)

        # Botón de Grabación CSV
        self.btn_grabar = QtWidgets.QPushButton("INICIAR GRABACIÓN")
        self.btn_grabar.setCheckable(True)
        self.btn_grabar.setStyleSheet("""
            QPushButton {
                background-color: #27ae60; color: white; font-size: 14pt; font-weight: bold; padding: 12px; border-radius: 8px;
            }
            QPushButton:checked {
                background-color: #c0392b; color: white;
            }
        """)
        self.btn_grabar.clicked.connect(self.cambiar_estado_grabacion)
        self.layout_izq.addWidget(self.btn_grabar)

        self.widget_izq.setFixedWidth(280) # Ancho fijo para que los gráficos no lo aplasten
        self.layout_principal.addWidget(self.widget_izq)

        # Variable interna de estado para la grabación
        self.is_recording = False

        # --- PANEL DERECHO (Gráficos) ---
        self.graficos = pg.GraphicsLayoutWidget()
        self.layout_principal.addWidget(self.graficos)

        # Fila 1: Gráfico en tiempo real (Señal cruda)
        self.plot_raw = self.graficos.addPlot(title="PPG Crudo (Tiempo Real rápido)")
        self.plot_raw.showGrid(x=True, y=True)
        self.curve_raw = self.plot_raw.plot(pen=pg.mkPen('y', width=2)) # Curva amarilla
        self.plot_raw.setMouseEnabled(x=False, y=False) # Bloqueado para mantener la fluidez
        self.graficos.nextRow()

        # Fila 2: Gráfico de ventana procesada (Estático, actualiza cada 10s)
        self.plot_filt = self.graficos.addPlot(title="PPG Filtrado (Ventana de 10s)")
        self.plot_filt.showGrid(x=True, y=True)
        self.curve_filt = self.plot_filt.plot(pen=pg.mkPen('g', width=2)) # Curva verde
        self.graficos.nextRow()

        # Fila 3: Gráfico de SDPPG con Puntos Fiduciarios (Analítico de 10s)
        self.plot_sdppg = self.graficos.addPlot(title="Segunda Derivada (SDPPG) y Puntos Fiduciarios")
        self.plot_sdppg.showGrid(x=True, y=True)
        self.curve_sdppg = self.plot_sdppg.plot(pen=pg.mkPen('c', width=2)) # Curva celeste

        # Capa interactiva para dibujar los puntos (a, b, c, d, e)
        self.puntos_fiduciarios = pg.ScatterPlotItem(size=12, pen=pg.mkPen(None))
        self.plot_sdppg.addItem(self.puntos_fiduciarios)

        # Búfer interno exclusivo para el osciloscopio rápido
        self.tamano_buffer_rt = 750 # Representa 3 segundos a 250Hz para que se vea fluida la onda
        self.datos_rt_raw = np.zeros(self.tamano_buffer_rt)

        self.win.show()

    def cambiar_estado_grabacion(self):
        """Método que se ejecuta al hacer clic en el botón"""
        self.is_recording = self.btn_grabar.isChecked()
        if self.is_recording:
            self.btn_grabar.setText("DETENER GRABACIÓN")
        else:
            self.btn_grabar.setText("INICIAR GRABACIÓN")

    def actualizar_tiempo_real(self, ppg_raw, gsr_raw=0.0):
        """
        Recibe 1 dato crudo y empuja la gráfica superior.
        (El parámetro gsr_raw se mantiene para no romper el main.py)
        """
        # Desplaza y anima la señal cruda
        self.datos_rt_raw[:-1] = self.datos_rt_raw[1:]
        self.datos_rt_raw[-1] = ppg_raw
        self.curve_raw.setData(self.datos_rt_raw)

    def actualizar_procesado(self, ppg_filtrado, sdppg, ratio_ba, ai, scl, puntos_x, puntos_y, colores, bpm):
        """
        Actualiza los gráficos de la ventana de 10s (Filtrado y Derivada) y el panel izquierdo.
        """
        # Graficamos la ventana completa de la señal filtrada y la derivada
        if ppg_filtrado is not None and sdppg is not None:
            self.curve_filt.setData(ppg_filtrado)
            self.curve_sdppg.setData(sdppg)

        if puntos_x is not None and puntos_y is not None and colores is not None:
            self.puntos_fiduciarios.setData(x=puntos_x, y=puntos_y, brush=colores)
        else:
            self.puntos_fiduciarios.clear()

        if ratio_ba is not None and ai is not None and bpm is not None:
            texto = (
                f"<b style='color: #FFFFFF; font-size: 16pt;'>Frec. Cardíaca:</b><br>"
                f"<span style='font-size: 32pt; color: #FFFFFF;'>{bpm:.0f} BPM</span><br><br><br>"

                f"<b style='color: #00FF00; font-size: 16pt;'>Rigidez (b/a):</b><br>"
                f"<span style='font-size: 26pt; color: #00FF00;'>{ratio_ba:.3f}</span><br><br><br>"

                f"<b style='color: #00FFFF; font-size: 16pt;'>Edad Vascular (AI):</b><br>"
                f"<span style='font-size: 26pt; color: #00FFFF;'>{ai:.3f}</span><br><br><br>"

                f"<b style='color: #FFA500; font-size: 16pt;'>GSR (SCL):</b><br>"
                f"<span style='font-size: 26pt; color: #FFA500;'>{scl:.2f} µS</span>"
            )
            self.panel_texto.setText(texto)

    def procesar_eventos(self):
        self.app.processEvents()