# Robot Dataset Crash Lab

[Français](README.md) · [English](README.en.md)

**Un grabador puede publicar un episodio cuyas imágenes aún no existen. Este laboratorio lo detiene en el momento preciso para demostrarlo.**

Procesos reales, archivos PNG reales y, opcionalmente, archivos **MCAP 1.6.0** reales. El controlador envía SIGKILL en cuatro fronteras de publicación, inspecciona el estado visible y prueba la reanudación. Imágenes y estados de sensores son sintéticos.

![Informe de interrupciones MCAP reales con datos sintéticos](docs/preview-fr.png)

## Probar

Python 3.11 o posterior, Linux o macOS. JSONL usa solo la biblioteca estándar.

```sh
python3 -m robot_crash demo --output .local/matrix.json --html .local/report.html --lang es
```

Abrir `.local/report.html`: informe autónomo FR/EN/ES con filtros, pruebas y exportación JSON. Sin servidor ni clave.

Para probar el formato MCAP real:

```sh
python3 -m venv .venv
.venv/bin/pip install '.[mcap]'
.venv/bin/python -m robot_crash demo --encoding mcap --output .local/mcap.json --html .local/mcap.html --lang es
```

## Qué demuestran los ensayos

Ambos protocolos se interrumpen tras escribir estados, imágenes, publicar archivos y publicar metadatos. El controlador recibe el evento de sincronización, envía **SIGKILL**, espera la salida `-9` y abre los metadatos desde otro proceso.

- **Protocolo de referencia:** archivos completos y sincronizados, directorio publicado y después commit SQLite. Las cuatro interrupciones conservan un prefijo coherente; la reanudación produce tres episodios y doce imágenes legibles.
- **Control deliberadamente defectuoso:** commit de metadatos antes de completar archivos. Tres de cuatro interrupciones exponen un episodio con archivos ausentes; se rechaza la reanudación.
- Se conservan archivos huérfanos y temporales. Existir en disco no hace visible un episodio; la reanudación no los sobrescribe.
- El lector comprueba hashes, manifiesto, cantidades e índices, tiempos, referencias PNG y rutas. En MCAP el SDK real lee también mensajes, secuencias y tiempos con validación CRC.

Ocho interrupciones por formato; pruebas para JSONL **y** MCAP. Los PNG son válidos pero no proceden de robots. El protocolo e índice SQLite pertenecen al laboratorio; no es un grabador nativo LeRobot.

## Por qué otro repositorio

La [propuesta LeRobot #4665](https://github.com/huggingface/lerobot/issues/4665) explica que confirmar una tabla no garantiza coherencia entre frames, vídeo y metadatos. Este laboratorio reproduce ese fallo entre archivos mediante interrupciones reales y un control que debe fallar.

[MCAP](https://mcap.dev/docs/python/mcap-apidoc/mcap.writer) ya aporta formato, grabación e índices; `flush()` no realiza `fsync`. Usamos el [lector oficial](https://mcap.dev/docs/python/mcap-apidoc/mcap.reader) y añadimos un ejercicio de publicación de archivos/metadatos, sin afirmar mejoras del formato. [Robot Run Audit](https://github.com/gbesse/robot-run-audit) analiza trazas existentes; aquí se interrumpe la escritura antes de auditarlas.

## Límites explícitos

SIGKILL no es un corte eléctrico, almacenamiento averiado, corrupción física ni fallo de red. Cuatro fronteras instrumentadas no cubren todo instante posible. No se certifica persistencia ni sincronización del sistema. Sin pruebas nativas LeRobot, ROS 2, cámaras o robots reales. Un futuro adaptador deberá exponer sus puntos de publicación y lector real antes de afirmar cobertura equivalente.

`python3 -m robot_crash inspect carpeta` no escribe explícitamente el conjunto; SQLite puede gestionar archivos auxiliares de lectura. El grabador rechaza directorios no vacíos sin marcador del laboratorio. La matriz usa carpetas temporales y conserva huérfanos; no repara automáticamente episodios confirmados pero corruptos.

## Verificar

```sh
.venv/bin/python -m unittest discover -s tests -v
npm ci
npx playwright install chromium
PYTHON=.venv/bin/python npm run test:browser
npm run format:check
```

Catorce pruebas incluyen dieciséis SIGKILL de matriz, reanudación, control defectuoso, corrupción de imágenes, huérfanos, rutas, decodificación MCAP y CRC PNG. Navegador FR/EN/ES y móvil sobre informe MCAP real. CI Python 3.11/3.12, paquetes e instalación de rueda fuera de fuentes. Salida 0: referencia válida y defecto detectado; 1: fallo de una aserción de matriz; 2: error de ejecución. Licencia MIT; alfa de investigación.
