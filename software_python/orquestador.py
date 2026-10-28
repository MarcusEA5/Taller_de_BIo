"""
Orquestador: lógica de la sesión sin depender de Qt ni del puerto serie.

`main.py` solo crea la ventana, el hilo lector y un QTimer que llama a
`procesar_item` con cada elemento de la cola. Todo lo demás (qué se guarda,
cuándo se calcula el AI basal, qué se muestra) está acá, así que se puede
probar alimentándolo con datos grabados.

La interfaz debe ofrecer (duck typing):
    .is_recording : bool
    .fase_actual  : str
    .edad_vascular_texto : str            (se asigna acá)
    .mostrar_ventana(res) / .set_estado_adquisicion(ok, texto)
"""
import time

import config
import procesamiento_gsr
from adquisicion import ControlTiempo
from almacenamiento_csv import GestorSesion
from edad_vascular import EstimadorBasal
from pipeline import ProcesadorStream


class Orquestador:
    def __init__(self, interfaz, fs=config.FS, carpeta="registros_csv"):
        self.ui = interfaz
        self.fs = fs
        self.carpeta = carpeta
        self.proc = ProcesadorStream(fs)
        self.control = ControlTiempo(fs)
        self.sesion = None
        self.estimador = None
        self._ult_estado = 0.0

    # ------------------------------------------------------------------
    def comenzar(self, datos_planilla):
        """Inicia la grabación. Lanza ValueError si el código de sujeto es inválido."""
        self.sesion = GestorSesion(datos_planilla["Codigo"], datos_planilla, self.carpeta)
        self.estimador = EstimadorBasal()
        self.ui.edad_vascular_texto = "Calculando basal..."

    def finalizar(self):
        if self.sesion is None:
            return
        if self.estimador and not self.estimador.finalizado:
            self._finalizar_basal()
        est = self.estimador
        self.sesion.cerrar(dict(
            muestras_perdidas=self.proc.perdidas,
            fs_medida_hz=self.control.fs_medida(),
            ai_basal_mediana=est.ai_mediana if est else None,
            n_latidos_basales=est.n_latidos if est else 0,
            edad_vascular_takazawa_sin_validar=est.edad if est else None))
        self.sesion = None

    # ------------------------------------------------------------------
    def procesar_item(self, item):
        """Procesa un elemento de la cola del lector serie."""
        tipo = item[0]
        if tipo == "dato":
            _, n, t_us, ppg_raw, mv = item
            self.control.actualizar(n, t_us)
            grabando = self.ui.is_recording and self.sesion is not None
            fase = self.ui.fase_actual if grabando else config.FASE_INACTIVA

            if grabando:
                self.sesion.guardar_muestra(n, self.fs, fase, ppg_raw, mv,
                                            procesamiento_gsr.mV_a_uS(mv))
            res = self.proc.agregar(n, ppg_raw, mv, fase)
            if res is not None:
                self._manejar_ventana(res, grabando)
            self._actualizar_estado()
        elif tipo == "info":
            if item[1].startswith("fs="):
                try:
                    self.control.fs_declarada = float(item[1][3:])
                except ValueError:
                    pass
        elif tipo == "error":
            self.ui.set_estado_adquisicion(False, item[1])

    # ------------------------------------------------------------------
    def _manejar_ventana(self, res, grabando):
        if grabando:
            self.sesion.guardar_ventana(res)
            self.sesion.guardar_latidos(res["latidos_confirmados"])
            self._actualizar_basal(res["latidos_confirmados"])
        self.ui.mostrar_ventana(res)

    def _actualizar_basal(self, latidos):
        est = self.estimador
        if est is None or est.finalizado:
            return
        for l in latidos:
            if l["fase"] == config.FASE_BASAL:
                if l["valido"]:
                    est.agregar(l["ai"])
            elif l["fase"] not in (config.FASE_INACTIVA, config.FASE_BASAL):
                self._finalizar_basal()          # primera vez que se sale del reposo
                return

    def _finalizar_basal(self):
        ai, edad, n = self.estimador.finalizar()
        if config.MOSTRAR_EDAD_VASCULAR and edad is not None:
            self.ui.edad_vascular_texto = f"{edad:.1f} años (sin calibrar)"
        elif edad is not None or n > 0:
            self.ui.edad_vascular_texto = f"AI basal = {ai:+.2f} (n={n})"
        else:
            self.ui.edad_vascular_texto = "Sin datos basales"

    def _actualizar_estado(self):
        ahora = time.monotonic()
        if ahora - self._ult_estado >= 1.0:
            self._ult_estado = ahora
            ok, texto = self.control.estado()
            self.ui.set_estado_adquisicion(ok, texto)
