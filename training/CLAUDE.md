# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes, derived from Andrej Karpathy's observations on LLM coding pitfalls. Merged with ISG project-specific rules.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

## Project-Specific Guidelines

### Architecture

- **Desktop app**: PySide6/QML frontend, local SQLite via SQLAlchemy ORM. No web server, no FastAPI in main path.
- **QML → BackendService**: All QML-facing APIs go through `BackendService` (Qt signals/slots). Don't call core modules directly from QML.
- **Background tasks**: Use `threading.Thread(daemon=True)` for long-running tasks. Emit signals for UI updates; don't manipulate UI from worker threads.
- **Reference**: `docs/BACKEND_ARCHITECTURE.md` is the authoritative architecture document. Old `api/` code is legacy.

### Code Style

- Comments: Chinese for domain logic explanations. Code identifiers in English.
- Database: Always use `SessionLocal()` for thread-local sessions in background workers. Reuse sessions in the main thread via dependency injection.
- File paths: Use `os.path` and forward slashes. Handle both Windows and POSIX.
- Signals: Define signals at class level. Emit structured dicts (not raw ORM objects) for QML consumption.
- Error handling: Return `{"status": "error", "message": str(e)}` for QML-facing methods. Log full tracebacks server-side.

### Conventions

- `core/models/`: SQLAlchemy ORM models
- `core/data_management/`: Dataset CRUD, file import/processing
- `core/data_cleaning/`: Cleaning tasks, suggestions, multi-modal strategies
- `core/sample_generation/`: Enhancement tasks, algorithm management
- `core/model_evaluation/`: Evaluation tasks, reports, performance analysis
- `utils/`: Shared helpers (logging, hardware adapters)

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
