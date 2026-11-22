# Emergencia: reglas mínimas de agentes a partir de patrones colectivos

Buscar, de forma automática, **las reglas de interacción más simples** que, dadas a
agentes que solo ven su entorno local, reproducen un **comportamiento colectivo
observado** en un sistema real. El primer caso es la organización espacial del
comercio en ciudades mexicanas.

> El objetivo no es una simulación realista del sistema. Es encontrar qué reglas
> locales son *suficientes* y *mínimas* para que emerja lo que se observa, y qué
> tanto se puede afirmar sobre ellas.

---

## 1. La idea

La inspiración viene de una forma reciente de construir emuladores de software:
agentes que escriben código y lo corrigen contrastando, una y otra vez, el
comportamiento del emulador con el del sistema real, que funciona como oráculo
([All Things Distributed, 2026](https://www.allthingsdistributed.com/2026/11/aws-emulator-and-the-engineers-job-when-agents-write-the-code.html)).

Aquí se hace lo mismo con un sistema complejo, pero con una diferencia de escala
fundamental:

| | Emulador de software | Este proyecto |
|---|---|---|
| Qué se escribe | El código del sistema | Solo las reglas de los agentes |
| Qué se compara | Respuesta a cada petición | Patrones **colectivos**, a escala del sistema |
| Oráculo | El servicio real | Los datos observados del sistema |
| Qué se busca | Equivalencia de comportamiento | Las reglas **más simples** que bastan |

Es el problema inverso de los modelos basados en agentes: de un flock de
estorninos se observan las formas del conjunto, no las reglas de cada pájaro. Se
proponen reglas, se simula y se compara lo que emerge con lo observado. Luego se
mejoran las reglas, castigando la complejidad. En el flock las reglas ya se
conocen; aquí se aplica a un sistema donde no se conocen.

### Las tres capas

| Capa | Qué es | ¿De dónde sale? |
|---|---|---|
| **Agentes y reglas** | Las entidades y cómo deciden con información local | **Es lo que se busca.** Ningún dato lo revela. |
| **Entradas exógenas** | Lo que empuja al sistema desde fuera (población, red de calles) | Datos, como condiciones de frontera |
| **Patrones emergentes** | Estructuras colectivas que ningún agente decide | Datos: **son el oráculo** |

Se observa el estado del sistema (dónde está cada comercio), igual que en un
flock se ven las posiciones de los pájaros. Lo que no se observa son las
decisiones que llevaron a ese estado.

## 2. El caso: cómo se organiza el comercio en una ciudad

Los comercios no se reparten al azar ni de forma uniforme. En el mapa se ven
estructuras colectivas que ningún comercio decidió:

- **Centros con jerarquía:** pocos centros grandes y muchos pequeños, con un
  espaciamiento que no es aleatorio (la estructura de los lugares centrales).
- **Corredores:** el comercio se alinea a lo largo de ciertas calles y no de otras.
- **Atracción y repulsión entre giros:** las zapaterías, refaccionarias o tiendas
  de ropa se juntan en calles enteras; las farmacias, tortillerías o tiendas de
  abarrotes se repelen y cubren el territorio.
- **Dinámica:** dónde nacen comercios nuevos respecto a los existentes, qué
  centros se consolidan, cuáles desaparecen y cómo responde todo a un choque como
  la pandemia de 2020.

### Preguntas

1. ¿Cuáles son las reglas locales mínimas (por tipo de comercio) que reproducen
   a la vez los centros, los corredores y la atracción/repulsión entre giros?
2. ¿Basta la demanda (población cercana) con economías de escala, o hace falta
   interacción explícita entre comercios? ¿Hace falta la red de calles?
3. ¿Son las mismas reglas en ciudades distintas? Si una regla mínima ajustada en
   una ciudad funciona en otras, hay algo parecido a una **universalidad**.
4. ¿Las reglas que reproducen una foto de la ciudad también reproducen cómo
   cambia entre fotos, y cómo respondió al choque de 2020?

## 3. Datos

Todos son públicos.

| Capa | Fuente | Uso |
|---|---|---|
| **Comercios (oráculo)** | [DENUE, INEGI](https://www.inegi.org.mx/app/descarga/?ti=6): unidades económicas con coordenadas, clase SCIAN, personal ocupado, fecha de alta y centro comercial. Hay versiones nacionales de 2015, dos por año de 2016 a 2025 y la de mayo 2026. | Patrones observados por ciudad y periodo |
| **Red de calles** | OpenStreetMap (extracto de México de Geofabrik) | Espacio donde viven los agentes; distancias sobre la red |
| **Demanda** | Censo de Población y Vivienda 2020 (INEGI), resultados por manzana | Población que genera demanda en cada punto de la red |
| **Geografía** | Marco Geoestadístico (INEGI) | Límites de localidades urbanas y manzanas |

Sobre el DENUE hay una advertencia importante. Entre censos económicos, el INEGI
actualiza sobre todo los establecimientos grandes. La foto completa se renueva con
cada Censo Económico (2014, 2019 y 2024). Por eso, las fotos que de verdad
informan sobre nacimientos y muertes de comercios pequeños son probablemente las
posteriores a cada censo (2015, 2020 y 2025). Esto se verifica en la fase 0.

### Ciudades

Para empezar, **ciudades medias relativamente aisladas** (por ejemplo
Aguascalientes, Mérida, San Luis Potosí, Morelia o Hermosillo), y no una gran zona
metropolitana. Así la demanda es casi toda interna y la frontera del sistema está
clara: es un sistema *semicerrado*. Las demás ciudades sirven para validar.

## 4. Metodología

```
                ┌──────────────────────────────────────────────┐
                │  Proponente de reglas                        │
                │  (LLM que lee el diagnóstico · GP de base)   │
                └───────────────┬──────────────────────────────┘
                                │ estructura de la regla (DSL)
                                ▼
                ┌──────────────────────────────────────────────┐
                │  Calibración interna de parámetros           │
                │  (CMA-ES o ABC-SMC)                          │
                └───────────────┬──────────────────────────────┘
                                ▼
   entradas exógenas ──► ┌──────────────────────────────┐
   (red, población)      │  Simulador: solo agentes     │  N réplicas
                         └──────────────┬───────────────┘
                                        ▼
                         patrones simulados  ◄─── comparación ───►  patrones observados (DENUE)
                                        │
                                        ▼
                ajuste por patrón × complejidad de la regla → frente de Pareto
                                        │
                                        └──► diagnóstico ("faltan corredores", "las farmacias
                                             se agrupan demasiado") → siguiente propuesta
```

### 4.1 Patrones (los observables)

Una distribución por sí sola restringe poco las reglas. Siguiendo el
*pattern-oriented modelling*, se exige reproducir **varios patrones
estructurales a la vez**. Todos se miden sobre la red de calles, no en línea
recta:

| Patrón | Medida |
|---|---|
| **P1. Atracción y repulsión entre giros** | Matriz de coaglomeración *M<sub>ab</sub>(r)*: cuántos comercios del giro *b* hay alrededor de los del giro *a*, comparado con un reparto aleatorio sobre los mismos lugares (índice de Jensen) |
| **P2. Centros** | Centros detectados (picos de densidad sobre la red): número, distribución de tamaños, espaciamiento entre centros y jerarquía (qué giros aparecen solo en los centros grandes) |
| **P3. Corredores** | Qué tan concentrado está el comercio en pocos tramos de calle, en qué tipo de calles y qué tan largos son los tramos continuos de comercio |
| **P4. Relación con la demanda** | Comercios por giro en función de la población alcanzable a cierta distancia (umbral y alcance de cada giro) |
| **P5. Dinámica** | Dónde nacen y mueren comercios entre fotos, respecto a la densidad y a los giros vecinos |

Unos patrones se usan para ajustar y otros se reservan para validar.

### 4.2 Simulador

- **Espacio:** la red de calles de la ciudad. Los agentes ocupan tramos.
- **Entradas exógenas:** la población de cada manzana, asignada a la red, y la
  jerarquía vial. Son fijas y vienen de los datos.
- **Agentes:** comercios de *K* tipos (agrupaciones SCIAN de comercio y servicios
  al consumidor). Opcionalmente, consumidores que eligen dónde comprar según la
  distancia y el atractivo de cada lugar (interacción espacial).
- **Dinámica:** en cada paso llegan comercios potenciales que eligen dónde
  ubicarse según la regla de **localización**. Los existentes sobreviven o cierran
  según la regla de **permanencia**.
- **Dos modos de prueba:**
  1. **Génesis:** desde una ciudad vacía hasta un estado estacionario, y se
     comparan los patrones.
  2. **Evolución:** desde la foto real de un año (por ejemplo 2015) se avanza al
     siguiente periodo y se compara con la foto real (2020, 2025). Es la prueba más
     cercana al contraste petición por petición del emulador.
- **Estocástico:** cada regla se evalúa con varias réplicas, y lo que se compara
  es la distribución de los patrones, no una sola corrida.

### 4.3 El espacio de reglas (DSL)

Las reglas se escriben en un lenguaje pequeño, para que "más simple" sea medible
y para impedir trampas.

- **Percepción local** (lo único que un agente puede ver):
  - población alcanzable a distancia *r* sobre la red;
  - número de comercios del mismo giro, de cada otro giro y totales a distancia *r*;
  - tipo de calle del tramo;
  - edad propia.
- **Operadores:** suma, producto, potencia, umbral, saturación, exponencial.
- **Salidas:** el atractivo de un lugar (localización) y la probabilidad de
  cerrar (permanencia).
- **Complejidad:** número de nodos del árbol de la regla más número de
  parámetros libres (longitud de descripción).

**Restricción de localidad:** ninguna primitiva da acceso a información global (la
distribución de toda la ciudad, la posición de los centros). Sin esa restricción,
el buscador puede codificar el patrón directamente en vez de hacerlo emerger.

### 4.4 Búsqueda

- **Dos niveles:** fuera se busca la **estructura** de la regla y dentro se
  calibran sus **parámetros**. Si se mezclan, una regla buena con parámetros malos
  se descarta como si fuera una regla mala.
- **Proponente:** un LLM que recibe el diagnóstico de qué patrón falla y propone
  modificaciones dirigidas, al estilo de la búsqueda de programas con LLM
  (FunSearch, AlphaEvolve). Como línea base, programación genética sobre el mismo
  DSL, para medir si el LLM aporta.
- **Selección multiobjetivo:** ajuste a cada patrón frente a complejidad. El
  resultado es un **frente de Pareto**, no un ganador.

### 4.5 Validación

1. **Recuperación con verdad conocida.** Antes de tocar datos reales, el método
   tiene que redescubrir las reglas de un modelo conocido a partir solo de sus
   patrones. El modelo de referencia es un sistema dinámico de lugares centrales
   (tipo Harris–Wilson), ya implementado en
   [central_theory_sim](https://github.com/irvingfisica/central_theory_sim). Tiene
   una transición en el exponente de la distancia η: con η chico la competencia es
   de largo alcance y sobreviven pocos centros grandes; con η grande, muchos
   chicos. Si el método no recupera la forma de la regla y no ordena η en datos
   sintéticos, no se puede confiar en lo que encuentre en datos reales. Como ese
   modelo no es local (el ingreso de cada centro depende de todos), la prueba se
   hace en dos partes: primero con una verdad escrita en el propio DSL y después
   con el modelo de lugares centrales ([docs/fase1.md](docs/fase1.md)).
2. **Patrones reservados:** las reglas se ajustan con unos patrones y se evalúan
   en otros.
3. **Fuera de muestra:** otro periodo, otras ciudades y otros giros.
4. **El choque de 2020:** ¿las reglas predicen *dónde* cerraron los comercios?
   Si dos familias de reglas ajustan igual de bien el estado estacionario, la
   respuesta al choque suele desempatarlas.
5. **Identificabilidad:** cuántas reglas distintas alcanzan el mismo ajuste
   (equifinalidad). Se reporta, no se esconde.

## 5. Qué queremos obtener

1. **Un conjunto de patrones observados** del comercio por ciudad y periodo,
   abierto y reproducible desde el DENUE: coaglomeración entre giros, centros y
   corredores.
2. **Un simulador y un DSL** de reglas para comercio sobre redes de calles.
3. **Las reglas mínimas** por tipo de comercio: frentes de Pareto de ajuste
   frente a complejidad, con las familias de reglas equivalentes y lo que no se
   puede distinguir.
4. **Una respuesta sobre universalidad:** si las reglas mínimas son las mismas en
   ciudades distintas, o qué cambia.
5. **Una evaluación del método:** si el ciclo de proponer, simular y contrastar
   con agentes funciona para descubrir reglas de un sistema complejo, y si un LLM
   como proponente supera a la programación genética. El método es general y se
   puede aplicar después a otros sistemas.

## 6. Plan

| Fase | Qué | Resultado |
|---|---|---|
| **0. Datos y patrones observados** | Serie del DENUE, red y población para 2–3 ciudades. Calcular P1–P5 y verificar que los patrones son claros y estables entre fotos. | Mapas y patrones observados. Decisión de ciudades y giros. **Primeros resultados (P1–P3): [docs/fase0.md](docs/fase0.md).** |
| **1. Simulador y prueba de recuperación** | Simulador sobre la red y DSL. Recuperar las reglas de lugares centrales a partir de sus patrones. | El método recupera la verdad conocida (o se sabe por qué no). **Resultados: [docs/fase1.md](docs/fase1.md)** — recupera una regla del DSL; ante lugares centrales, la regla «atracción cercana × competencia lejana» ordena η y reduce el error a menos de la mitad, aunque todavía no alcanza el piso de ruido. |
| **2. Búsqueda en una ciudad** | Ciclo completo en una ciudad, modo génesis. | Primer frente de Pareto de reglas reales. |
| **3. Validación** | Modo evolución 2015 → 2020 → 2025, choque de 2020, patrones reservados. | Reglas que sobreviven a la validación. |
| **4. Universalidad** | Mismas reglas en otras ciudades. | Qué es general y qué es local. |

## 7. Riesgos

- **Actualización desigual del DENUE** entre censos económicos (ver Datos). Puede
  reducir la dinámica útil a tres fotos.
- **Comercio informal:** tianguis y ambulantes no están en el DENUE. Una parte del
  sistema queda fuera del oráculo.
- **Georreferencia:** varios comercios comparten coordenadas (plazas, mercados).
  Se trata como un solo sitio con varios ocupantes.
- **Equifinalidad:** es probable que varias reglas expliquen lo mismo. Por eso el
  resultado es un frente de Pareto y no una regla.
- **Cómputo:** cada evaluación implica varias réplicas por regla. Hay que
  mantener el simulador rápido y ciudades medianas.

## 8. Referencias

- Grimm, V. et al. (2005). Pattern-oriented modeling of agent-based complex
  systems: lessons from ecology. *Science* 310, 987–991.
- Epstein, J. M. (2023). Inverse generative social science: backward to the
  future. *JASSS* 26(2).
- Jensen, P. (2006). Network-based predictions of retail store commercial
  categories and optimal locations. *Physical Review E* 74, 035101.
- Harris, B. y Wilson, A. G. (1978). Equilibrium values and dynamics of
  attractiveness terms in production-constrained spatial-interaction models.
  *Environment and Planning A* 10, 371–388.
- [Dynamic Central Place Theory: Results of a Simulation Approach](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1538-4632.1977.tb00576.x).
  *Geographical Analysis* (1977).
- Romera-Paredes, B. et al. (2024). Mathematical discoveries from program search
  with large language models. *Nature* 625, 468–475.

## Estructura del repo

```
README.md          este documento
DATOS.md           de dónde salen los datos y cómo se preparan
scripts/           descarga y preparación de datos
src/emergencia/    código del proyecto (patrones, simulador, búsqueda)
datos/             datos locales (no van en git)
```
