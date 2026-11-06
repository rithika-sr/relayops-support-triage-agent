# Contributing

## Workflow

1. `make setup`, pull the two Ollama models, `make seed`, `make dev`.
2. Make a focused change with its tests in the same commit.
3. Run `make test-offline` and `make check-repo`. Run `make test-live` and `make e2e` when the change touches the
   runtime, prompts, retrieval, or UI journeys; run `make eval-offline` when it touches routing, retrieval, or data.
4. Use conventional commit messages (`feat(scope): ...`, `fix(...)`, `test(...)`, `docs: ...`, `ci: ...`).
5. Open a pull request describing behavior changes and how you verified them. CI must pass.

## Code conventions

- Backend: Python 3.12, ruff (line length 120), ruff format, mypy. Routers call services; services own transactions
  and audit; repositories apply scope; tools reuse services. Domain modules do not import FastAPI.
- Frontend: TypeScript, ESLint (Next config), Tailwind tokens in `globals.css`, all API calls through `src/lib/api.ts`.
- Never hold a database transaction across a model call or HTTP request.
- Tests that need a model use the `FixtureProvider` and must not claim to measure model quality.

## Data and evaluation

- All demo data is synthetic. Do not add real customer, employer, or university records.
- Edit benchmark families in `evals/datasets/build_cases.py`, then rebuild `cases.jsonl` and the manifest. Keep
  paraphrases of one failure in one family. Do not tune on the test split; if you do, mark it consumed.
- Report measured numbers only, with denominators. Unrun cases stay unrun.

## Secrets

Never commit `.env`, `.local/`, credentials, or tokens. `scripts/check_repo.py` runs in CI.
