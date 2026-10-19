# Robot Dataset Crash Lab

[Français](README.md) · [Español](README.es.md)

**A recorder can publish an episode whose images do not exist yet. This lab kills it at the right moment to demonstrate the defect.**

Real processes, real PNG files and optional real **MCAP 1.6.0** files. The controller sends SIGKILL at four publication boundaries, inspects reader-visible state, then tests resume. Sensor images and states are synthetic.

![Real MCAP interruption report with synthetic data](docs/preview-fr.png)

## Try it

Python 3.11 or newer, Linux or macOS. JSONL mode uses only the standard library.

```sh
python3 -m robot_crash demo --output .local/matrix.json --html .local/report.html --lang en
```

Open `.local/report.html`: a standalone FR/EN/ES report with filters, evidence and JSON export. No server or key.

To test the actual MCAP format:

```sh
python3 -m venv .venv
.venv/bin/pip install '.[mcap]'
.venv/bin/python -m robot_crash demo --encoding mcap --output .local/mcap.json --html .local/mcap.html --lang en
```

## What the trials demonstrate

Both protocols meet the same checkpoints: after state writes, image writes, file publication and metadata publication. The controller receives a synchronization event, sends **SIGKILL**, waits for exit code `-9`, then opens metadata from a separate process.

- **Reference protocol:** complete synced files, published directory, then SQLite commit. All four interruptions retain a consistent prefix; resume yields three episodes and twelve readable frames.
- **Deliberately broken control:** metadata commit before file completion. Three of four interruptions expose an episode with missing files; resume is refused.
- Orphan and staging files remain preserved. File existence alone never makes an episode visible; resume does not overwrite them.
- The reader checks hashes, manifest, frame counts and indices, timestamps, PNG references and paths. In MCAP mode, the actual SDK also reads messages, sequences and timestamps with CRC validation.

Eight interruptions per format; tests cover both JSONL **and** MCAP. PNGs are valid but come from no robot. The publication protocol and SQLite index belong to this lab; this is not a native LeRobot recorder.

## Why another repository?

[LeRobot proposal #4665](https://github.com/huggingface/lerobot/issues/4665) explains why a table commit does not make frames, video and metadata mutually consistent. This lab exercises that cross-artifact failure with real process interruptions and a control that must fail.

[MCAP](https://mcap.dev/docs/python/mcap-apidoc/mcap.writer) already provides recording, format and indexes; its `flush()` does not perform `fsync`. We use the [official reader](https://mcap.dev/docs/python/mcap-apidoc/mcap.reader) and add a file/metadata publication exercise, without claiming to improve the MCAP format. [Robot Run Audit](https://github.com/gbesse/robot-run-audit) analyzes existing traces; here, writing is interrupted before the audit.

## Explicit limits

SIGKILL is not power loss, failing storage, hardware corruption or a network fault. Four instrumented boundaries do not cover every possible interruption instant. System-level persistence and synchronization are not certified. No native LeRobot, ROS 2, camera or real-robot trial has run. A future adapter must expose its own publication checkpoints and actual reader before claiming equivalent coverage.

`python3 -m robot_crash inspect directory` performs no explicit dataset writes; SQLite may manage auxiliary read files. The reference recorder refuses nonempty directories lacking the lab marker. Matrix runs use temporary directories and preserve orphans; no automatic repair of corrupted committed episodes is attempted.

## Verify

```sh
.venv/bin/python -m unittest discover -s tests -v
npm ci
npx playwright install chromium
PYTHON=.venv/bin/python npm run test:browser
npm run format:check
```

Fourteen tests include sixteen matrix SIGKILLs, resume, broken control, image corruption, orphans, path protection, MCAP decoding and PNG CRCs. Browser checks the real MCAP report in FR/EN/ES and mobile. CI covers Python 3.11/3.12, packaging and wheel installation outside sources. Exit 0 means the reference passes and the broken control is detected; 1 means a matrix assertion failed; 2 means execution error. MIT license; research alpha.
