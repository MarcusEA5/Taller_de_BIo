"""
Interfaz gráfica (PyQt5 + pyqtgraph). No contiene lógica de procesamiento: solo muestra
lo que le entrega el Orquestador y avisa (callbacks) cuándo empieza o termina una sesión.

Contrato con el Orquestador (duck typing):
    is_recording, fase_actual, edad_vascular_texto      atributos que lee/escribe el orquestador
    mostrar_ventana(res)                                resultado de cada ventana de 10 s
    set_estado_adquisicion(ok, texto)                   estado del enlace con el ESP32
    on_comenzar(datos_planilla) / on_finalizar()        callbacks que se asignan desde main.py
"""
import time
from datetime import datetime

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets

import config
from almacenamiento_csv import id_valido

ESTILO_ETIQUETA = "color: #ddd; font-size: 14px;"


# ----------------------------------------------------------------------------
# Formulario del voluntario
# ----------------------------------------------------------------------------
class FormularioVoluntario(QtWidgets.QDialog):
    """Planilla previa a la sesión. Registra los factores que alteran la señal cardiovascular."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Planilla del voluntario")
        lay = QtWidgets.QFormLayout(self)

        self.f_codigo = QtWidgets.QLineEdit()
        self.f_codigo.setPlaceholderText("Código seudonimizado, p. ej. V01 (no usar nombre ni DNI)")
        self.f_edad = QtWidgets.QSpinBox()
        self.f_edad.setRange(18, 100)                       # solo mayores de edad
        self.f_edad.setValue(22)
        self.f_sexo = self._combo(["Femenino", "Masculino", "Otro / prefiere no decir"])
        self.f_mano = self._combo(["Derecha", "Izquierda", "Ambidiestro"])
        self.f_cafeina = self._combo(["No consumió hoy", "Hoy, hace más de 3 h", "Hoy, hace menos de 3 h"])
        self.f_tabaco = self._combo(["No fuma", "Fuma, no en las últimas 3 h", "Fumó en las últimas 3 h"])
        self.f_ejercicio = self._combo(["Ninguno en 24 h", "Sí, hace más de 3 h", "Sí, hace menos de 3 h"])
        self.f_comida = self._combo(["Ayuno de más de 3 h", "Comió hace menos de 3 h"])
        self.f_sueno = self._combo(["Menos de 5 h", "Entre 5 y 7 h", "Más de 7 h"])
        self.f_medicacion = self._combo(["No", "Sí"])
        self.f_antecedentes = self._combo(["No", "Sí"])
        self.f_pa_sis = QtWidgets.QSpinBox()
        self.f_pa_sis.setRange(0, 260)
        self.f_pa_sis.setSpecialValueText("No medida")
        self.f_pa_dia = QtWidgets.QSpinBox()
        self.f_pa_dia.setRange(0, 160)
        self.f_pa_dia.setSpecialValueText("No medida")
        self.f_consentimiento = QtWidgets.QCheckBox("Firmó el consentimiento informado")

        lay.addRow("Código de sujeto:", self.f_codigo)
        lay.addRow("Edad (años):", self.f_edad)
        lay.addRow("Sexo:", self.f_sexo)
        lay.addRow("Mano dominante:", self.f_mano)
        lay.addRow("Cafeína / mate:", self.f_cafeina)
        lay.addRow("Tabaco:", self.f_tabaco)
        lay.addRow("Ejercicio:", self.f_ejercicio)
        lay.addRow("Última comida:", self.f_comida)
        lay.addRow("Sueño de la última noche:", self.f_sueno)
        lay.addRow("Medicación cardiovascular:", self.f_medicacion)
        lay.addRow("Hipertensión / cardiopatía diagnosticada:", self.f_antecedentes)
        lay.addRow("Presión sistólica (mmHg):", self.f_pa_sis)
        lay.addRow("Presión diastólica (mmHg):", self.f_pa_dia)
        lay.addRow("", self.f_consentimiento)

        botones = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        lay.addRow(botones)

    @staticmethod
    def _combo(opciones):
        c = QtWidgets.QComboBox()
        c.addItems(opciones)
        return c

    def accept(self):
        if not id_valido(self.f_codigo.text().strip()):
            QtWidgets.QMessageBox.warning(self, "Código inválido",
                                          "Usá un código de 2 a 20 caracteres (letras, números, _ o -), p. ej. V01.")
            return
        if not self.f_consentimiento.isChecked():
            QtWidgets.QMessageBox.warning(self, "Consentimiento",
                                          "No se puede iniciar la medición sin consentimiento informado firmado.")
            return
        super().accept()

    def obtener_datos(self):
        return {
            "Codigo": self.f_codigo.text().strip(),
            "Fecha": datetime.now().isoformat(timespec="seconds"),
            "Edad": self.f_edad.value(),
            "Sexo": self.f_sexo.currentText(),
            "Mano_dominante": self.f_mano.currentText(),
            "Cafeina": self.f_cafeina.currentText(),
            "Tabaco": self.f_tabaco.currentText(),
            "Ejercicio": self.f_ejercicio.currentText(),
            "Ultima_comida": self.f_comida.currentText(),
            "Sueno": self.f_sueno.currentText(),
            "Medicacion_cardiovascular": self.f_medicacion.currentText(),
            "Antecedentes_cardiovasculares": self.f_antecedentes.currentText(),
            "PA_sistolica": self.f_pa_sis.value() or None,
            "PA_diastolica": self.f_pa_dia.value() or None,
            "Consentimiento": True,
        }


# ----------------------------------------------------------------------------
# Ventana principal
# ----------------------------------------------------------------------------
class Graficador:
    def __init__(self):
        pg.setConfigOption("background", "k")
        pg.setConfigOption("foreground", "w")
        self.app = pg.mkQApp("Monitor PPG + GSR")

        self.is_recording = False
        self.fase_actual = config.FASE_INACTIVA
        self.edad_vascular_texto = "Esperando basal"
        self.on_comenzar = None
        self.on_finalizar = None
        self._t_inicio_fase = time.monotonic()
        self._duracion_min = dict(config.PROTOCOLO)

        self._crear_ventana()
        self.ventana.show()

        self._timer_fase = QtCore.QTimer()
        self._timer_fase.timeout.connect(self._actualizar_cuenta)
        self._timer_fase.start(500)

    # ---------------------------------------------------------------- construcción
    def _etiqueta(self, texto, estilo=ESTILO_ETIQUETA):
        e = QtWidgets.QLabel(texto)
        e.setStyleSheet(estilo)
        return e

    def _crear_ventana(self):
        self.ventana = QtWidgets.QWidget()
        self.ventana.setWindowTitle("Monitor PPG + GSR - Taller de Bioingeniería")
        self.ventana.resize(1280, 800)
        self.ventana.setStyleSheet("background-color: #111;")
        raiz = QtWidgets.QHBoxLayout(self.ventana)

        # --- panel izquierdo -------------------------------------------------
        izq = QtWidgets.QVBoxLayout()
        self.lbl_bpm = self._etiqueta("Frec. cardíaca:\n-- lpm", "color: white; font-size: 26px; font-weight: bold;")
        self.lbl_ba = self._etiqueta("b/a (mediana):\n--", "color: #4fd1c5; font-size: 20px;")
        self.lbl_ai = self._etiqueta("AI (mediana):\n--", "color: #4fd1c5; font-size: 20px;")
        self.lbl_edad = self._etiqueta("Edad vascular:\nEsperando basal", "color: #63b3ed; font-size: 16px;")
        self.lbl_scl = self._etiqueta("GSR (SCL):\n-- µS", "color: #f6ad55; font-size: 20px;")
        self.lbl_scr = self._etiqueta("SCR: --", "color: #f6ad55; font-size: 14px;")
        self.lbl_calidad = self._etiqueta("Calidad: --", "color: #ddd; font-size: 14px;")
        self.lbl_adq = self._etiqueta("Adquisición: sin conexión", "color: #fc8181; font-size: 13px;")
        for w in (self.lbl_bpm, self.lbl_ba, self.lbl_ai, self.lbl_edad, self.lbl_scl, self.lbl_scr,
                  self.lbl_calidad, self.lbl_adq):
            izq.addWidget(w)
        izq.addSpacing(10)

        self.btn_comenzar = QtWidgets.QPushButton("COMENZAR PRUEBA")
        self.btn_comenzar.setStyleSheet("background-color: #2f855a; color: white; padding: 8px; font-weight: bold;")
        self.btn_comenzar.clicked.connect(self._al_comenzar)
        self.btn_finalizar = QtWidgets.QPushButton("FINALIZAR PRUEBA")
        self.btn_finalizar.setStyleSheet("background-color: #c53030; color: white; padding: 8px; font-weight: bold;")
        self.btn_finalizar.setEnabled(False)
        self.btn_finalizar.clicked.connect(self._al_finalizar)
        izq.addWidget(self.btn_comenzar)
        izq.addWidget(self.btn_finalizar)
        izq.addSpacing(10)

        self.lbl_fase = self._etiqueta("Fase: Inactivo", "color: #ecc94b; font-size: 15px; font-weight: bold;")
        izq.addWidget(self.lbl_fase)
        self.btns_fase = {}
        for nombre, _ in config.PROTOCOLO:
            b = QtWidgets.QPushButton(nombre)
            b.setEnabled(False)
            b.setStyleSheet("padding: 6px;")
            b.clicked.connect(lambda _checked=False, n=nombre: self._cambiar_fase(n))
            self.btns_fase[nombre] = b
            izq.addWidget(b)
        izq.addStretch(1)
        raiz.addLayout(izq, 1)

        # --- gráficos ---------------------------------------------------------
        self.win = pg.GraphicsLayoutWidget()
        raiz.addWidget(self.win, 4)

        self.p_rt = self.win.addPlot(title="PPG en tiempo real (últimos 5 s, sin componente continua)")
        self.c_rt = self.p_rt.plot(pen=pg.mkPen("y", width=1.5))
        self.p_rt.setLabel("bottom", "Tiempo", units="s")
        self.win.nextRow()
        self.p_gsr = self.win.addPlot(title="Conductancia de la piel (últimos 30 s)")
        self.c_gsr = self.p_gsr.plot(pen=pg.mkPen("#f6ad55", width=1.5))
        self.p_gsr.setLabel("left", "µS")
        self.p_gsr.setLabel("bottom", "Tiempo", units="s")
        self.win.nextRow()
        self.p_filt = self.win.addPlot(title="PPG filtrado (ventana de análisis)")
        self.c_filt = self.p_filt.plot(pen=pg.mkPen("g", width=1.5))
        self.p_filt.setLabel("bottom", "Tiempo", units="s")
        self.win.nextRow()
        self.p_sd = self.win.addPlot(title="Segunda derivada (SDPPG) y puntos a-e de latidos válidos")
        self.c_sd = self.p_sd.plot(pen=pg.mkPen("c", width=1.2))
        self.sc_sd = pg.ScatterPlotItem(size=9, pen=pg.mkPen(None))
        self.p_sd.addItem(self.sc_sd)
        self.p_sd.setLabel("bottom", "Tiempo", units="s")

    # ---------------------------------------------------------------- sesión y fases
    def _al_comenzar(self):
        dlg = FormularioVoluntario(self.ventana)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        datos = dlg.obtener_datos()
        try:
            if self.on_comenzar:
                self.on_comenzar(datos)
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self.ventana, "No se pudo iniciar", str(exc))
            return
        self.is_recording = True
        self.btn_comenzar.setEnabled(False)
        self.btn_finalizar.setEnabled(True)
        self._cambiar_fase(config.PROTOCOLO[0][0], confirmar=False)

    def _al_finalizar(self):
        self.is_recording = False
        self.fase_actual = config.FASE_INACTIVA
        self.btn_finalizar.setEnabled(False)
        self.btn_comenzar.setEnabled(True)
        for b in self.btns_fase.values():
            b.setEnabled(False)
        if self.on_finalizar:
            self.on_finalizar()
        self.lbl_fase.setText("Fase: Inactivo")

    def _cambiar_fase(self, nombre, confirmar=True):
        """Avanza a la fase `nombre`. Pide confirmación si la fase anterior no cumplió su duración mínima."""
        if not self.is_recording:
            return
        previa = self.fase_actual
        minimo = self._duracion_min.get(previa)
        if confirmar and minimo:
            transcurrido = time.monotonic() - self._t_inicio_fase
            if transcurrido < minimo:
                r = QtWidgets.QMessageBox.question(
                    self.ventana, "Fase incompleta",
                    f"'{previa}' lleva {transcurrido:.0f} s de los {minimo} s previstos.\n¿Pasar a '{nombre}' igual?")
                if r != QtWidgets.QMessageBox.StandardButton.Yes:
                    return
        self.fase_actual = nombre
        self._t_inicio_fase = time.monotonic()
        orden = [n for n, _ in config.PROTOCOLO]
        for n, b in self.btns_fase.items():
            b.setEnabled(orden.index(n) > orden.index(nombre))     # solo se puede avanzar
        self._actualizar_cuenta()

    def _actualizar_cuenta(self):
        if not self.is_recording:
            return
        t = time.monotonic() - self._t_inicio_fase
        minimo = self._duracion_min.get(self.fase_actual, 0)
        color = "#68d391" if t >= minimo else "#ecc94b"            # verde al cumplir el mínimo
        self.lbl_fase.setStyleSheet(f"color: {color}; font-size: 15px; font-weight: bold;")
        self.lbl_fase.setText(f"{self.fase_actual}\n{t:.0f} s / {minimo} s")

    # ---------------------------------------------------------------- actualización de datos
    def set_estado_adquisicion(self, ok, texto):
        color = "#68d391" if ok else "#fc8181"
        self.lbl_adq.setStyleSheet(f"color: {color}; font-size: 13px;")
        self.lbl_adq.setText(f"Adquisición: {texto}")

    def actualizar_tiempo_real(self, ppg_ac, gsr_uS, fs=config.FS):
        """Curvas en vivo (se llama ~25 veces por segundo desde main.py)."""
        if len(ppg_ac):
            self.c_rt.setData(np.arange(-len(ppg_ac), 0) / fs, ppg_ac)
        if len(gsr_uS):
            self.c_gsr.setData(np.arange(-len(gsr_uS), 0) / fs, gsr_uS)
        self.lbl_edad.setText(f"Edad vascular:\n{self.edad_vascular_texto}")

    @staticmethod
    def _fmt(v, formato):
        return "--" if v is None or not np.isfinite(v) else format(v, formato)

    def mostrar_ventana(self, res, fs=config.FS):
        """Actualiza paneles y gráficos con el resultado de una ventana de 10 s."""
        self.lbl_bpm.setText(f"Frec. cardíaca:\n{self._fmt(res['bpm'], '.0f')} lpm")
        self.lbl_ba.setText(f"b/a (mediana):\n{self._fmt(res['ba_med'], '+.2f')}")
        self.lbl_ai.setText(f"AI (mediana):\n{self._fmt(res['ai_med'], '+.2f')}")
        self.lbl_scl.setText(f"GSR (SCL):\n{self._fmt(res['scl_uS'], '.2f')} µS")
        self.lbl_scr.setText(f"SCR: {res['scr_n']} picos, máx {self._fmt(res['scr_amp_uS'], '.2f')} µS")

        avisos = []
        if not res["dedo_ok"]:
            avisos.append("SIN DEDO / señal débil")
        elif not res["resumen_ok"]:
            avisos.append("señal ruidosa: ventana descartada")
        if not res["contacto_ok"]:
            avisos.append("GSR sin contacto")
        if res["perdidas"]:
            avisos.append(f"{res['perdidas']} muestras perdidas")
        ok = not avisos
        self.lbl_calidad.setStyleSheet(f"color: {'#68d391' if ok else '#fc8181'}; font-size: 14px;")
        self.lbl_calidad.setText(f"Latidos válidos: {res['n_validos']}/{res['n_latidos']}"
                                 + ("" if ok else "\n" + " · ".join(avisos)))

        if res["ppg_f"] is None:
            self.c_filt.setData([], [])
            self.c_sd.setData([], [])
            self.sc_sd.setData([], [])
            return
        t = np.arange(len(res["ppg_f"])) / fs
        self.c_filt.setData(t, res["ppg_f"])
        self.c_sd.setData(t, res["sdppg"])
        xs, ys, cs = res["puntos"]
        self.sc_sd.setData(x=xs, y=ys, brush=[pg.mkBrush(c) for c in cs])

    # ---------------------------------------------------------------- bucle de la aplicación
    def ejecutar(self):
        ejecutar = getattr(self.app, "exec_", None) or self.app.exec
        return ejecutar()
