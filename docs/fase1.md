# Fase 1: simulador y prueba de recuperación

Antes de buscar reglas en datos reales hay que saber si el método encuentra una
regla conocida a partir de sus patrones. Esta fase construye el simulador y el
lenguaje de reglas (DSL) y los pone a prueba con dos verdades sintéticas sobre la
red real de Aguascalientes.

Resultados crudos: `salida/fase1/recuperacion_dsl_aguascalientes.json` (1a) y
`salida/fase1/recuperacion_hw_aguascalientes.json` (1b). Ambos se regeneran con
los comandos al final de este documento.

## Simulador

**Espacio** ([lotes.py](../src/emergencia/sim/lotes.py)). Cada tramo de calle se
parte en lotes de unos 25 m. En cada lote caben hasta 3 comercios. Aguascalientes
tiene 135,894 lotes. Para cada lote se guardan:

- la jerarquía de la vía;
- la población del Censo 2020 a ≤ 200 m y a ≤ 500 m sobre la red;
- las distancias en red a los demás lotes a ≤ 200 m (7.6 M pares, unos 56 por lote).

**Reglas** ([reglas.py](../src/emergencia/sim/reglas.py)). Una regla es una
expresión de texto que se lee con `ast` y se valida contra una lista blanca. Cada
agente ve solo información local:

| Variable | Qué mide |
|---|---|
| `pob200`, `pob500` | población a ≤ 200 m y a ≤ 500 m |
| `mismo100`, `mismo200` | comercios del mismo giro a ≤ 100 m y a ≤ 200 m |
| `total100`, `total200` | comercios de cualquier giro a ≤ 100 m y a ≤ 200 m |
| `<giro>100`, `<giro>200` | comercios de un giro dado a ≤ 100 m y a ≤ 200 m |
| `via`, `avenida`, `peatonal` | tipo de calle |
| `edad` | edad del comercio |

Operadores: `+ - * / **`, `exp`, `log1p`, `sat`, `umbral`, `min` y `max`. La
complejidad de una regla es su número de nodos más su número de parámetros.

**Dinámica (modo génesis)** ([simulador.py](../src/emergencia/sim/simulador.py)).
El número de comercios de cada giro es fijo. En cada paso:

1. Cierra el 5 % de los comercios de cada giro. Si hay regla de permanencia,
   decide quién cierra; si no, se eligen al azar.
2. Llegan tantos comercios como cerraron. Cada uno elige un lote con lugar libre,
   con probabilidad proporcional a la regla de localización.

Los conteos de vecinos se actualizan de forma incremental. Con 3 giros (unos
12.6 mil comercios), 150 pasos bastan para llegar al estado estacionario y una
corrida tarda unos 20 s.

**Firma y distancia** ([firmas.py](../src/emergencia/sim/firmas.py)). La firma
resume cuatro patrones observados en la fase 0:

| Grupo | Patrón |
|---|---|
| P1 | log₂ M de Jensen a 200 m entre todos los pares de giros |
| P2 | centros a f = 1, 1.5 y 2, y pendiente rango–tamaño |
| P3 | Gini por calle, top 5 %, fracción de calles vacías y razón por tipo de vía |
| P4 | log de la razón de población a 500 m por giro |

La distancia entre dos firmas es la media de z² por grupo. La escala de z es la
dispersión entre réplicas de la verdad, con un piso de 0.05. El total es la media
de los cuatro grupos.

**Calibración** ([calibrar.py](../src/emergencia/sim/calibrar.py)):

- Se usa CMA-ES en el cubo [0, 1]^d (población 10, 12 iteraciones, 2 réplicas por
  punto, unas 240 simulaciones por estructura).
- Al final se reevalúan el mejor punto y la media de CMA.
- Con un solo parámetro se usa una rejilla.

**Piso de ruido.** Es la distancia de la propia verdad, corrida con semillas nuevas,
a su firma objetivo. Una estructura que lo alcanza es indistinguible de la verdad.

## Prueba 1a: la verdad es una regla del DSL

Hay tres giros con las cantidades reales de Aguascalientes y reglas verdaderas
conocidas:

| Giro | Comercios | Regla | Valores |
|---|---|---|---|
| abarrotes | 3,347 | `pob500**a` | a = 1 |
| ropa | 2,150 | `(1+mismo200)**b * exp(c*avenida)` | b = 1.5, c = 1 |
| restaurantes | 7,121 | `(1+total200)**d` | d = 0.5 |

Piso de ruido: **0.32 ± 0.10**.

| Estructura | Complejidad | Distancia | Parámetros recuperados |
|---|---:|---:|---|
| **verdad** | 22 | **0.87** | a = 1.11, b = 1.49, c = 2.54, d = 0.54 |
| ropa sin avenida | 16 | 1.90 | |
| abarrotes con atracción (`pob500**a*(1+mismo200)**e`) | 29 | 2.95 | a = 0.11, e = 0.79 |
| ropa exponencial (`exp(b*mismo200 + c*avenida)`) | 20 | 13.98 | |
| abarrotes sin población | 19 | 16.11 | |
| ropa sin atracción | 15 | 39.41 | |
| nulo | 3 | 93.04 | |

Lo que salió bien:

- **La estructura verdadera gana**, y queda a menos de 2 pisos de ruido.
- Quitar cualquier término empeora el ajuste. La caída es grande cuando falta un
  término fuerte (la atracción de ropa: ×45; la población en abarrotes: ×18) y
  chica cuando falta uno débil (avenida: ×2).
- Una forma equivocada de la atracción (exponencial en vez de potencia) ajusta 16
  veces peor.
- Los exponentes fuertes se recuperan bien: a, b y d dentro del 11 %.

Límites que aparecieron:

- **El efecto de avenida está mal identificado.** Se recuperó c = 2.54 cuando el
  verdadero es 1. Las avenidas son pocas y la firma solo las ve en la razón por
  tipo de vía, así que la superficie es plana en c.
- **La calibración cae en óptimos locales.** "Abarrotes con atracción" contiene a
  la verdad (con e = 0), pero ajustó peor que ella (2.95 contra 0.87). CMA-ES
  terminó en otra combinación: poca población y mucha atracción entre iguales.
  Eso muestra dos cosas:
  - la búsqueda necesita varios arranques;
  - hay equifinalidad parcial: concentrarse cerca de otros abarrotes imita en
    parte a concentrarse donde hay gente.

## Prueba 1b: la verdad es un modelo de lugares centrales

La verdad es el sistema dinámico de lugares centrales de
[central_theory_sim](https://github.com/irvingfisica/central_theory_sim) (tipo
Harris–Wilson), puesto sobre la red real
([harris_wilson.py](../src/emergencia/sim/harris_wilson.py)):

- R_j = Σ_i P_i W_j d_ij^-η / Σ_k W_k d_ik^-η es el ingreso del centro j.
- W_j ← W_j + g (R_j − W_j) hace crecer al centro cuando su ingreso supera su costo.

Montaje:

| Elemento | Cómo se fija |
|---|---|
| Demanda | población del Censo 2020 en celdas de 300 m (1,274 puntos) |
| Centros posibles | un lote por celda de 150 m (7,035) |
| d | distancia en red en km, más 0.1 |
| Equilibrio | g = 1 (ver abajo) |
| Comercios | el tamaño final de cada centro se reparte en comercios en lotes a ≤ 100 m de él |

Con costo lineal, el punto fijo W = R es la actualización EM de los pesos de una
mezcla con núcleo d^-η. Por eso g = 1 llega al mismo equilibrio que la dinámica
lenta, en menos pasos.

A diferencia de central_theory_sim, la población queda fija: no se pone en cero
donde hay actividad.

Hay tres sectores independientes, con los mismos tamaños que en 1a:

| Sector | η | Comercios | Centros vivos |
|---|---:|---:|---:|
| eta10 | 1.0 | 2,150 | 35 |
| eta15 | 1.5 | 3,347 | 163 |
| eta25 | 2.5 | 7,121 | 688 |

Como referencia, los centros vivos en todo el barrido de η: η = 0.5 → 15,
1.0 → 35, 1.5 → 163, 2.0 → 428, 2.5 → 688, 3.0 → 853, 4.0 → 995.

Este modelo **no es local**: el ingreso de un centro depende de todos los demás
y de toda la población. La pregunta es si alguna regla local reproduce sus
patrones y si sus parámetros ordenan a los sectores según η. Se calibra la misma
estructura en los tres sectores, cada uno con parámetros propios.

Piso de ruido: **0.22 ± 0.04**.

| Estructura | Complejidad | Distancia | Jensen | Centros | Corredores | Demanda | Parámetros (η = 1 / 1.5 / 2.5) |
|---|---:|---:|---:|---:|---:|---:|---|
| `pob500**a * (1+mismo200)**b` | 33 | **31.4** | 65.5 | 28.7 | 13.0 | 18.5 | a = 2.90 / 0.37 / 0.28; b = 0.20 / 0.45 / 0.07 |
| `pob500**a` | 12 | 32.9 | 83.7 | 16.5 | 10.2 | 21.1 | a = 3.00 / 0.49 / 0.28 |
| `pob500**a * (1+total200)**b` | 33 | 51.2 | 175.6 | 13.9 | 9.2 | 6.1 | a = 1.20 / 0.56 / 0.60; b = 0.45 / 0.20 / 0.00 |
| `(1+mismo200)**b` | 18 | 56.4 | 101.9 | 11.1 | 17.1 | 95.4 | b = 1.13 / 1.00 / 0.72 |
| nulo | 3 | 266.4 | 234.6 | 603.8 | 25.0 | 202.0 | |
| `pob500**a * exp(b*mismo200)` | 30 | 292.8 | 467.7 | 653.0 | 27.1 | 23.5 | a = 2.29 / 1.69 / 2.42; b = 0.84 / 0.02 / 0.00 |

Lo que se aprende:

- **Ninguna regla local probada reproduce la verdad.** La mejor queda unas 140
  veces por encima del piso de ruido. Esto contrasta con 1a, donde la verdad
  quedaba a menos de 3 pisos.
- **Los parámetros sí ordenan a los sectores según η.**
  - En la regla de población, el exponente baja de forma monótona con η: 3.0, 0.49
    y 0.28. Con η chico casi todo el comercio va a donde más gente hay a 500 m.
  - En la regla de atracción pura, b también baja: 1.13, 1.00 y 0.72.
  - Es decir, la dirección de la transición se recupera aunque la forma no.
- **La parsimonia funciona.** Agregar atracción entre iguales a la regla de
  población casi no mejora el ajuste (31.4 contra 32.9) y casi duplica la
  complejidad. En un frente de Pareto, `pob500**a` domina.
- **La calibración sigue frágil.**
  - La forma exponencial terminó peor que el nulo. Un b = 0.84 en η = 1 hace que
    exp(b·mismo) se dispare, todo el sector cae en un punto, y CMA-ES no salió de
    ahí en 12 iteraciones.
  - Igual que en 1a, hacen falta varios arranques y probablemente un espacio de
    parámetros mejor escalado.

**Diagnóstico.** Esta es la firma de la verdad contra la mejor regla:

| Patrón | Lugares centrales | Regla local |
|---|---|---|
| log₂ M propio, η = 1 | 1.87 | 1.10 |
| log₂ M entre η = 1 y η = 2.5 | −0.71 | −0.09 |
| log₂ M entre η = 1.5 y η = 2.5 | −1.38 | −0.63 |
| fracción en centros (f = 1) | 0.38 | 0.26 |
| top 5 % de calles | 0.71 | 0.41 |
| razón de población, η = 1 / 1.5 / 2.5 | 0.81 / 0.76 / 0.54 | 1.01 / 0.48 / 0.38 |

La regla local produce poca autoatracción, casi ninguna repulsión entre sectores
y mucha menos concentración. Hay dos razones, y las dos son de alcance:

1. **Radio de percepción.** Con η = 1 los centros quedan a unos 1.8 km entre sí.
   La competencia que los separa ocurre a una escala que un agente que ve 200 m
   no percibe. Lo único que ve a más distancia es `pob500`, y por eso esa
   variable carga todo el ajuste.
2. **Interacción entre sectores.** En la verdad los sectores son independientes,
   pero compiten por los mismos lotes y por la misma población, y eso los separa.
   Las candidatas probadas no ven a los otros giros salvo a través de `total200`,
   que es positivo (atracción), no negativo.

## Qué sigue

1. **Calibración con varios arranques.** Reiniciar CMA-ES desde puntos distintos
   (o con IPOP), y escalar en logaritmo los parámetros que entran en exponentes.
   Volver a correr las estructuras de 1a que contienen a la verdad, para ver si
   alcanzan el piso.
2. **Percepción de mayor alcance.** Agregar al DSL variables locales de radio
   largo (por ejemplo, comercios a ≤ 1 km sobre una malla gruesa) y términos con
   signo libre para otros giros. Con esto, repetir 1b:
   - si la distancia baja hacia el piso, el problema era de percepción;
   - si no baja, los patrones de lugares centrales no tienen una explicación
     local simple, y eso es un resultado en sí.
3. Después, la **fase 2**: búsqueda de estructuras sobre los datos reales de una
   ciudad.

## Cómo reproducir

```
uv run python -m emergencia.sim.lotes --ciudad aguascalientes
uv run python -m emergencia.sim.recuperacion          # prueba 1a, ~2.5 h con 6 núcleos
uv run python -m emergencia.sim.recuperacion_hw       # prueba 1b, ~2 h con 12 núcleos
```

Las dos pruebas aceptan `--rapido` para una corrida corta de verificación y
`--candidatas` para correr solo algunas estructuras.
