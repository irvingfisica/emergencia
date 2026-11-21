# Fase 0: patrones observados

Primer cálculo de los patrones P1–P3 (ver [README](../README.md#41-patrones-los-observables))
en tres ciudades medias, con el DENUE de 2015 y de mayo 2026. El objetivo de esta fase es
saber si los patrones son lo bastante claros y estables para servir de oráculo.

**Respuesta corta: sí.** Los tres patrones son fuertes, casi no cambian en 11 años y se
parecen mucho entre ciudades.

## Datos

| Ciudad | Localidad urbana | Red de calles | Comercios 2015 | Comercios 2026 |
|---|---|---|---|---|
| Aguascalientes | 010010001 | 3,272 km | 29,685 | 36,639 |
| Mérida | 310500001 | 5,197 km | 34,082 | 39,226 |
| Hermosillo | 260300001 | 3,705 km | 21,036 | 23,351 |

- **Comercios:** unidades del DENUE dentro del polígono de la localidad urbana
  (Marco Geoestadístico 2025) en 25 grupos de giro ([config/giros.csv](../config/giros.csv)):
  comercio al por menor, comida, servicios personales, consultorios y bancos. Se excluyen
  manufactura, oficinas, gobierno y escuelas.
- **Red:** calles de OpenStreetMap (sin autopistas, veredas ni estacionamientos), partidas
  en intersecciones; componente conexa más grande dentro del polígono con 1 km de margen.
- Cada comercio se ubica en el tramo de calle más cercano (a menos de 150 m) y se
  inserta como nodo en la red. **Todas las distancias son sobre la red.**

Reproducir:

```bash
uv run python -m emergencia.ciudad --denue datos/denue --marco <00l.parquet> --osm <mexico.osm.pbf>
uv run python -m emergencia.patrones
uv run python -m emergencia.comparar
```

## P1. Atracción y repulsión entre giros

Coeficiente de Jensen *M<sub>ab</sub>* a 200 m sobre la red: cuántos comercios del giro *b*
rodean a los del giro *a*, comparado con repartir los giros al azar entre los mismos
locales. Se compara además con 30 permutaciones para marcar lo que no es significativo.

![Jensen, Aguascalientes 2026](img/fase0_jensen_aguascalientes.png)

Se ven dos familias:

- **Bienes de comparación**, que se juntan entre sí: ropa, calzado, electrónica, muebles,
  ópticas, bancos y consultorios. Calzado consigo mismo: *M* ≈ 5–10; bancos: *M* ≈ 8–28
  (según ciudad, año y radio).
- **Bienes de cercanía**, que cubren el territorio y evitan los centros: abarrotes,
  tortillerías, panaderías, papelerías, carnes. Las tortillerías se repelen entre sí
  (*M* ≈ 0.2–0.7 en casi todos los casos; la excepción es Hermosillo 2026 a 200 m, con 1.4).
  Abarrotes y restaurantes quedan cerca del azar (*M* ≈ 1.1–2.0).

**Estabilidad** (correlación de log₂ *M<sub>ab</sub>* sobre los 625 pares; signo entre los
pares significativos en ambas):

| | r | mismo signo |
|---|---|---|
| Misma ciudad, 2015 vs 2026 | 0.88 · 0.88 · 0.89 | 97–98 % |
| Entre ciudades, misma versión | 0.72–0.86 | 91–94 % |

La estructura de atracción y repulsión es casi la misma en ciudades distintas. Es la
primera señal de que podría haber reglas comunes (la pregunta de universalidad).

## P2. Centros

Densidad de cada sitio = comercios a ≤ 300 m sobre la red. Un centro es un conjunto
conexo (enlaces ≤ 150 m) de sitios con densidad por encima de la media que ve un
comercio típico, con al menos 20 comercios.

| | Centros | Pendiente rango–tamaño | Comercios en centros |
|---|---|---|---|
| Aguascalientes 2015 / 2026 | 25 / 25 | −1.29 / −1.02 | 21 % / 19 % |
| Mérida 2015 / 2026 | 6 / 10 | −1.74 / −1.27 | 16 % / 15 % |
| Hermosillo 2015 / 2026 | 28 / 29 | −1.13 / −1.19 | 26 % / 24 % |

Hay jerarquía: un centro histórico grande y muchos centros menores, con una relación
rango–tamaño cercana a Zipf (pendiente ≈ −1). Este patrón es **sensible al umbral**
(con 1.5× o 2× la media quedan 2–7 centros; ver `sensibilidad` en cada `resumen.json`).
Para usarlo como oráculo conviene compararlo como curva en función del umbral, no con
un solo umbral.

## P3. Corredores

| | Gini (comercios vs. longitud de calle) | Comercios en el 5 % de la calle | Calle sin comercio |
|---|---|---|---|
| Aguascalientes 2015 / 2026 | 0.85 / 0.83 | 51 % / 48 % | 69 % / 64 % |
| Mérida 2015 / 2026 | 0.86 / 0.84 | 54 % / 50 % | 72 % / 68 % |
| Hermosillo 2015 / 2026 | 0.84 / 0.84 | 49 % / 49 % | 70 % / 68 % |

**La mitad de los comercios está en el 5 % de la longitud de calles**, en las tres
ciudades y en los dos años. Las avenidas (primarias, secundarias y terciarias en OSM)
tienen 10–23 comercios por km y las calles residenciales 5–8. Cuál de las tres jerarquías
de avenida domina cambia según la ciudad. Las calles peatonales del centro de Mérida
llegan a 74–94 por km.

![Aguascalientes 2026: comercios por giro, corredores y centros](img/fase0_mapa_aguascalientes.png)

Mérida y Hermosillo: [mapa](img/fase0_mapa_merida.png) · [Jensen](img/fase0_jensen_merida.png) ·
[mapa](img/fase0_mapa_hermosillo.png) · [Jensen](img/fase0_jensen_hermosillo.png).
Cifras completas: [fase0_comparacion.json](fase0_comparacion.json).

## Qué sigue

1. Repetir con toda la serie del DENUE (2015–2026) para ver la dinámica, cuidando que las
   fotos útiles para comercios pequeños son las posteriores a los Censos Económicos.
2. P4 (relación con la demanda): población por manzana del Censo 2020 asignada a la red.
3. P5 (dinámica): con el `id` que persiste entre versiones, dónde nacen y mueren comercios.
4. Fase 1: simulador sobre la red y prueba de recuperación con lugares centrales.

Para el simulador, esta fase deja dos objetivos claros: (a) la matriz de Jensen tiene
estructura en dos bloques que una regla mínima debería reproducir, y (b) la concentración
en corredores es extrema y casi idéntica entre ciudades, así que la regla tendrá que
explicarla, probablemente a través de la red de calles.
