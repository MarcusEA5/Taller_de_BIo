"""
Estimación de la edad vascular a partir del AI basal (ecuación de Takazawa et al., 1998).

    AI = pendiente * edad + ordenada      (coeficientes en config.EDAD_TAKAZAWA)
    edad_vascular = (AI - ordenada) / pendiente

ADVERTENCIA: esta ecuación fue obtenida con otro equipo y otra cadena de filtrado.
Mientras no se la valide/calibre con voluntarios de distintas edades usando ESTE
sistema, el resultado en años no debe presentarse como un valor clínico
(por eso config.MOSTRAR_EDAD_VASCULAR está en False).
"""
import numpy as np

import config


def edad_desde_ai(ai):
    pendiente, ordenada = config.EDAD_TAKAZAWA
    return (ai - ordenada) / pendiente


class EstimadorBasal:
    """Acumula el AI de los latidos válidos del reposo basal y lo resume una sola vez."""

    def __init__(self):
        self._ai = []
        self.finalizado = False
        self.ai_mediana = float("nan")
        self.edad = None
        self.n_latidos = 0

    def agregar(self, ai):
        if not self.finalizado and np.isfinite(ai):
            self._ai.append(float(ai))

    def finalizar(self):
        """Calcula la mediana basal. La edad es None si hay pocos latidos para que sea confiable."""
        self.finalizado = True
        self.n_latidos = len(self._ai)
        if self.n_latidos:
            self.ai_mediana = float(np.median(self._ai))
        if self.n_latidos >= config.MIN_LATIDOS_EDAD:
            self.edad = edad_desde_ai(self.ai_mediana)
        return self.ai_mediana, self.edad, self.n_latidos
