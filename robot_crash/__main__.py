import json
from pathlib import Path
import sqlite3
import sys

from .harness import inspect, matrix
from .report import html_report

MESSAGES = {
"fr":{"help":"Utilisation : python -m robot_crash demo [--encoding jsonl|mcap] [--output rapport.json] [--html rapport.html] [--lang fr|en|es] | inspect dossier", "error":"Entrée non valide ou essai interrompu"},
"en":{"help":"Usage: python -m robot_crash demo [--encoding jsonl|mcap] [--output report.json] [--html report.html] [--lang fr|en|es] | inspect directory", "error":"Invalid input or interrupted trial"},
"es":{"help":"Uso: python -m robot_crash demo [--encoding jsonl|mcap] [--output informe.json] [--html informe.html] [--lang fr|en|es] | inspect carpeta", "error":"Entrada no válida o ensayo interrumpido"}}


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    options = {"--lang":"en", "--output":None, "--html":None, "--encoding":"jsonl"}
    try:
        for key in options:
            if key in args:
                i = args.index(key)
                options[key] = args[i + 1]
                del args[i:i + 2]
        lang = options["--lang"]
        if lang not in MESSAGES:
            raise ValueError("invalid_language")
        if not args or args[0] in ("--help", "help"):
            print(MESSAGES[lang]["help"])
            return 0
        if args == ["demo"]:
            report = matrix(options["--encoding"])
            good = report["safe_protocol_passed"] and report["broken_control_detected"]
        elif len(args) == 2 and args[0] == "inspect":
            report = inspect(args[1])
            good = report["valid"]
        else:
            raise ValueError("invalid_command")
        content = json.dumps(report, ensure_ascii=False, indent=2)
        for flag, value in (("--output", content), ("--html", html_report(report, lang) if "trials" in report else None)):
            if options[flag]:
                if value is None:
                    raise ValueError("invalid_report_format")
                target = Path(options[flag])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(value)
        print(content)
        return 0 if good else 1
    except (ValueError, TypeError, KeyError, IndexError, OSError, RuntimeError, sqlite3.Error):
        lang = options.get("--lang") if options.get("--lang") in MESSAGES else "en"
        print(json.dumps({"error":"trial_failed", "message":MESSAGES[lang]["error"]}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
