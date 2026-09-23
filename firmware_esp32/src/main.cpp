#include <Arduino.h>
#include <Wire.h>
#include "MAX30105.h"

MAX30105 particleSensor;

// Pines I2C confirmados
#define I2C_SDA 8
#define I2C_SCL 9

const int pinGSR = 4;

void setup() {
  Serial.begin(115200);
  delay(3000); // Pausa para estabilizar el puerto USB-CDC

  // Inicializamos el bus I2C
  Wire.begin(I2C_SDA, I2C_SCL);
  
  // Intentamos conectar con el sensor MAX30102 / MAX30105
  if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) { 
    while (1) {
      // Bucle de error si no encuentra el sensor
      delay(1000);
    }
  }

  // Configuración del sensor PPG
  byte powerLevel = 0x1F; 
  byte sampleAverage = 1; 
  byte ledMode = 2;       
  int sampleRate = 400;   // Cambiado a 400Hz (o 200Hz) según soporte nativo del sensor
  int pulseWidth = 411;   
  int adcRange = 4096;    

  particleSensor.setup(powerLevel, sampleAverage, ledMode, sampleRate, pulseWidth, adcRange);
}

void loop() {
    // Lectura de los sensores
    uint32_t ppgValue = particleSensor.getIR(); 
    int gsrValue = analogRead(pinGSR); 

    // Empaquetado en formato CSV estricto por Puerto Serie
    Serial.print(ppgValue);
    Serial.print(",");
    Serial.println(gsrValue);

    // Pequeño retardo para regular el ciclo (puedes ajustarlo si notas que saturas el buffer)
    delay(4); 
}