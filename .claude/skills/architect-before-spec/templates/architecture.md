# Arquitectura — <proyecto>

<!-- Contrato de arquitectura (docs mínimos, gate architect-before-spec).
     Este doc dice cómo ES el sistema y qué límites tiene. No es un backlog ni un
     tutorial: lo que sea deseo futuro va a design.md; lo que sea decisión con
     alternativas va a un ADR. Borrá cada comentario guía al llenar su sección. -->

## Propósito y alcance

<!-- Qué es este sistema y qué NO es, en 3-6 líneas. Quién lo usa, qué problema
     resuelve, dónde termina su responsabilidad (qué queda explícitamente afuera).
     NO va acá: features pendientes, historia del proyecto, visión de producto. -->

## Capas y límites

<!-- El mapa de capas/módulos y sus reglas de import: qué puede depender de qué,
     y en qué dirección. Una línea por regla ("infrastructure importa de application
     y domain, nunca al revés"). Si hay carpetas que encarnan las capas, nombralas.
     NO va acá: detalle de clases internas; eso vive en el código. -->

## Contratos

<!-- Las interfaces que cruzan límites: APIs públicas, eventos, esquemas de datos
     compartidos, colas, contratos con servicios externos. Por contrato: quién lo
     expone, quién lo consume, dónde está definido (path). Cambiar algo de esta
     sección rompe a alguien → ADR primero.
     NO va acá: endpoints internos triviales ni DTOs privados de un módulo. -->

## Stack y módulos activos

<!-- Qué corre de verdad hoy: lenguaje/runtime, framework, DB, infra, y los módulos
     del workflow activos en este proyecto. Desviarse de esta lista (agregar una
     lib nueva, cambiar de DB) pasa por use-context7-first + ADR. Los pins de
     versión y los ids de context7 viven en references/libs.md, no acá. -->

## Invariantes

<!-- Las reglas que NUNCA se rompen, cada una con su porqué en una línea
     ("los handlers no tocan la DB directo — toda escritura pasa por el
     repositorio, porque X"). Incluye antipatrones ya cometidos en ESTE proyecto
     (qué no hacer, por qué, qué hacer en su lugar).
     Romper una invariante exige ADR aprobado antes del código. -->
