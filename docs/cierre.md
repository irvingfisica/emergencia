# Cierre: por qué el proyecto se detiene

El proyecto se cerró al terminar la fase 1 y antes de correr la fase 2. No se
cerró por un problema técnico. El simulador, la calibración y las pruebas de
recuperación funcionan. Se cerró porque, al revisarlo, el planteamiento no
sostiene lo que prometía: descubrir las reglas con que los comercios deciden
dónde ubicarse. Este documento deja escrito el razonamiento, para quien retome
la idea.

## 1. Quien propone las reglas trae su contexto

El README planteaba un ciclo automático. Un proponente (un LLM, con programación
genética como línea base) sugiere estructuras de reglas, la simulación las
calibra y el diagnóstico guía la siguiente propuesta.

En la práctica, durante la fase 1 el proponente fue un LLM, aunque no en un ciclo
automatizado: las estructuras candidatas se escribieron leyendo el diagnóstico de
cada ronda. Eso dejó a la vista el problema.

- En la prueba 1b la verdad era un modelo de lugares centrales (Harris–Wilson).
  Quien proponía las reglas lo sabía y conoce la teoría. Por eso propuso
  «atracción cercana × competencia lejana». El resultado de la 1b (esa regla
  ordena η y reduce el error a la mitad) no salió de la simulación. Salió de la
  literatura, y la simulación lo confirmó. Fue una prueba que no podía
  sorprender a quien la diseñó.
- Lo mismo vale para cualquier proponente. Un humano propone desde lo que sabe;
  un LLM, desde un contexto muchísimo más amplio (pero sin la intuición del
  humano). Una búsqueda «ciega» sobre la gramática tampoco es neutral. Alguien
  eligió la gramática, las primitivas (`pob500`, `mismo200`, `avenida`, los
  radios) y, sobre todo, qué patrones cuentan.

Que una hipótesis venga de un contexto no la invalida: así se hace siempre
ciencia. Lo que la valida es una prueba que la pueda refutar. Y eso no lo da el
simulador.

## 2. En el simulador se es juez y parte

Dentro del simulador, la misma persona diseña:

- el mundo;
- las reglas;
- los patrones;
- la medida de éxito.

Lo único que la simulación demuestra es una deducción: la regla X, ejecutada,
produce el patrón Y. Que una regla baste para producir un patrón no dice que así
funcione el mundo. La fase 1 lo mostró: varias reglas ajustan igual de bien, y en
la 1a `pob` y `mismo` se compensan.

Sí hay algo que el investigador no controla: lo que los comercios hacen. El
contraste que vale es el que el mundo decide, con experimentos o con
predicciones hechas antes de ver el resultado. Eso es el método científico de
siempre, no algo que el simulador agregue.

## 3. El DENUE como blanco no arregla el problema

La fase 2 iba a calibrar las reglas contra los comercios reales de
Aguascalientes. Pero lo que se compara no es la ciudad, sino una descripción de
ella:

- las firmas;
- los radios;
- el umbral de los centros;
- la exclusión de plazas y mercados;
- la distancia entre patrones.

Todas son decisiones de diseño. Si se cambia cómo se definen los patrones, cambia
qué regla «gana». El blanco se puede ajustar.

Apuntar a la distribución del DENUE no es un error: describir una distribución
observada es trabajo legítimo y común. Pero para eso están los modelos
estadísticos, no las reglas dinámicas de agentes:

- procesos puntuales espaciales;
- regresiones con efectos de vecindad;
- modelos de Cox log-gaussianos.

Esos modelos se ajustan directamente, dicen qué parámetros se pueden identificar y
miden la incertidumbre. Simular agentes 150 pasos para producir una distribución
y compararla con la observada es el mismo ajuste, solo que más caro y con menos
claridad.

Una regla de agentes solo vale más que un modelo estadístico si afirma un
mecanismo: «así deciden los comercios», no solo «así se distribuyen». Esa
afirmación no se prueba ajustando una distribución, porque muchas reglas
producen la misma. Para ponerla a prueba hace falta observar qué pasa cuando
algo cambia.

## 4. Qué queda útil

Como herramientas y datos, no como hallazgos:

- **Fase 0** ([fase0.md](fase0.md)):
  - los patrones espaciales del comercio son muy estables entre años y entre
    ciudades;
  - la mitad del comercio está en el 5 % de la calle;
  - el DENUE solo se renueva de verdad con cada Censo Económico (2019, 2024), así
    que los cambios llegan en escalones.
- **Fase 1** ([fase1.md](fase1.md)):
  - un simulador de comercios sobre la red de calles;
  - un lenguaje de reglas con medida de complejidad;
  - calibración con CMA-ES y percepción de largo alcance.
  Sirven para deducir qué produce una regla, no para decidir cuál es la buena.
- El código de la fase 2 (`sim/observado.py`, `sim/fase2.py`) ubica los
  comercios reales en los lotes del simulador y define la cadena de reglas. No se
  llegó a correr.

## 5. Si alguien retoma la idea

- **Describir los patrones del comercio:** un modelo estadístico espacial sobre el
  DENUE, sin simulación.
- **Probar un mecanismo:** comprometer la regla con una predicción antes de que el
  mundo la decida. Por ejemplo:
  - calibrar con la versión 2019 del DENUE y predecir dónde cambia en 2024;
  - predecir qué pasa alrededor de una avenida nueva o de una plaza que abre;
  - predecir dónde cerraron comercios en 2020.
  La predicción se registra antes de mirar. Si la regla falla, el mundo la
  refutó; no se recalibra para que ajuste.
