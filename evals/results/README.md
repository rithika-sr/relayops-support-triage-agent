# Evaluation results

Each run of `evals/runners/run.py` writes `<profile>-<UTC timestamp>.json` (metadata, per-system summary with
numerators and denominators, per-case rows) and a matching `.md` summary. Reports name the exact repository commit,
dataset split hashes, model tag and digest, and Ollama version. Only selected reports are committed; the Evaluations
page imports whatever JSON reports are present here.
