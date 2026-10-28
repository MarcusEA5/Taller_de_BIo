/*
 * Adquisición PPG (MAX30102) + GSR (ADC) para ESP32-C3 SuperMini.
 *
 * CAMBIOS RESPECTO DE LA VERSIÓN ANTERIOR
 *  - El ritmo de muestreo lo marca el RELOJ DEL SENSOR (FIFO del MAX30102 a FS_HZ), no un
 *    delay(4). Cada muestra del PPG se lee exactamente una vez: no se descartan ni se repiten
 *    muestras y el espaciado es uniforme (lo que exige derivar dos veces la señal).
 *  - Cada línea lleva un contador de muestras (n) -> el tiempo real es n / FS_HZ, sin depender
 *    de cuándo llegue el dato a la PC. También lleva micros() para verificar la fs.
 *  - Checksum XOR por línea: una línea cortada o alterada en el USB se descarta en Python
 *    en lugar de meter un pico falso en la señal.
 *  - El GSR se envía en mV ya calibrados (analogReadMilliVolts usa la calibración de fábrica
 *    del ADC) y promediando GSR_OVERSAMPLING lecturas para reducir ruido.
 *  - Si no hay sensor se avisa por el puerto serie en vez de quedar colgado en silencio.
 *
 * FORMATO (una línea por muestra):   n,t_us,ppg_ir,gsr_mV*HH
 *   HH = XOR de todos los caracteres anteriores al '*', en hexadecimal.
 *   Las líneas que empiezan con '#' son informativas (p. ej. "# fs=200").
 *
 * IMPORTANTE: FS_HZ debe coincidir con config.FS de software_python/config.py.
 *             El MAX30102 admite 50/100/200/400/800/1000/1600/3200 muestras/s (250 NO existe).
 */
#include <Arduino.h>
#include <Wire.h>
#include "MAX30105.h"          // SparkFun MAX3010x (sirve también para el MAX30102)

// ---------------- Pines ----------------
constexpr int PIN_SDA = 8;
constexpr int PIN_SCL = 9;
constexpr int PIN_GSR = 4;

// ---------------- Parámetros del sensor ----------------
constexpr int FS_HZ        = 200;     // muestras/s (nativo del MAX30102)
constexpr byte LED_POWER   = 0x1F;    // ~6,4 mA
constexpr byte SAMPLE_AVG  = 1;       // sin promediado interno: se conserva la fs nativa
constexpr byte LED_MODE    = 2;       // Rojo + IR (se transmite solo el IR)
constexpr int PULSE_WIDTH  = 411;     // µs -> 18 bits de resolución
constexpr int ADC_RANGE    = 4096;    // nA de fondo de escala

// ---------------- GSR ----------------
constexpr int GSR_OVERSAMPLING = 8;   // lecturas promediadas por muestra

MAX30105 sensor;
uint32_t contador   = 0;              // número de muestra (0,1,2,...)
uint32_t t0_us      = 0;              // micros() al iniciar la adquisición
uint32_t ult_info_ms = 0;

// Promedio de varias lecturas del ADC, ya en milivoltios calibrados.
static int leerGsrMilivolts() {
  uint32_t acum = 0;
  for (int i = 0; i < GSR_OVERSAMPLING; i++) acum += analogReadMilliVolts(PIN_GSR);
  return (int)(acum / GSR_OVERSAMPLING);
}

static void enviarMuestra(uint32_t n, uint32_t t_us, uint32_t ir, int gsr_mV) {
  char buf[72];
  int len = snprintf(buf, sizeof(buf), "%lu,%lu,%lu,%d",
                     (unsigned long)n, (unsigned long)t_us, (unsigned long)ir, gsr_mV);
  uint8_t chk = 0;
  for (int i = 0; i < len; i++) chk ^= (uint8_t)buf[i];
  Serial.printf("%s*%02X\n", buf, chk);
}

static void enviarInfo() {
  Serial.printf("# fs=%d\n", FS_HZ);
}

void setup() {
  Serial.begin(115200);
  delay(3000);                                   // tiempo para que la PC abra el puerto

  analogReadResolution(12);
  analogSetPinAttenuation(PIN_GSR, ADC_11db);    // rango útil ~0-2,5 V

  Wire.begin(PIN_SDA, PIN_SCL);
  while (!sensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("# ERROR: MAX30102 no encontrado (revisar SDA/SCL/alimentacion)");
    delay(1000);
  }
  sensor.setup(LED_POWER, SAMPLE_AVG, LED_MODE, FS_HZ, PULSE_WIDTH, ADC_RANGE);
  sensor.clearFIFO();

  enviarInfo();
  t0_us = micros();
}

void loop() {
  // check() trae del FIFO del sensor todas las muestras nuevas; cada una se lee una sola vez.
  sensor.check();
  while (sensor.available()) {
    uint32_t ir = sensor.getFIFOIR();
    sensor.nextSample();
    uint32_t t_us = micros() - t0_us;            // envuelve a las ~71 min; Python lo maneja
    enviarMuestra(contador++, t_us, ir, leerGsrMilivolts());
  }

  // Reenvío periódico de la fs: si la PC abre el puerto después del arranque igual la recibe.
  uint32_t ahora = millis();
  if (ahora - ult_info_ms >= 5000) {
    ult_info_ms = ahora;
    enviarInfo();
  }
}
