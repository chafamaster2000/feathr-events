# Referencias — <proyecto>

<!-- Índice de la carpeta docs/references/ (docs mínimos, gate architect-before-spec).
     references/ es una CARPETA, no un archivo: adentro va un archivo por tema y
     este README es el índice de dónde mirar antes de inventar. Curado significa
     corto: si nadie lo consultaría dos veces, no entra. Cada archivo nuevo se
     lista acá con una línea de qué contiene. Borrá cada comentario guía al
     llenar su sección. -->

## Archivos

<!-- Una fila por archivo de la carpeta. Los temas típicos:

     | Archivo | Contiene |
     |---|---|
     | `libs.md` | Librerías del proyecto: ids de context7 + versión consultada |
     | `engine.md` | Engine/runtime (lo siembra el módulo del stack — ej. unity-setup en Unity) |

     Creá los archivos a medida que hagan falta (libs.md es el primero: lo exige
     use-context7-first). Un archivo por tema, kebab-case; este README es solo el
     índice — el contenido vive en los archivos, no acá. -->

## Guía de `libs.md`

<!-- El contenido va en docs/references/libs.md, NO acá. Una fila por dependencia
     relevante (no todo el lockfile — las que definen el proyecto):

     | Lib | Versión en uso | context7 id | Notas |
     |---|---|---|---|
     | next | 15.1.x | /vercel/next.js | App Router; consultado 2026-07-01 |

     La "versión en uso" es la real (manifest/lockfile) y la fecha de consulta
     evita confiar en memoria vieja (use-context7-first). APIs prohibidas o
     deprecadas en la versión pineada se anotan en Notas. -->

## Docs externas

<!-- Links a documentación de terceros que este proyecto realmente usa: guías de
     integración, specs de APIs externas, RFCs. Un link + una línea de por qué
     importa. Si crecen, movelas a su propio archivo por tema y listalo en el
     índice. NO va acá: tutoriales genéricos ni links "por si acaso". -->

## Recursos internos

<!-- Material propio del estudio/proyecto: docs de diseño en Drive, boards, ADRs
     de otros repos que condicionan a éste, dashboards. Un link + una línea.
     Si el recurso es secreto/credencial, NO va acá — va al gestor de secretos. -->
