# Pharma Marketing Draft Pipeline (prototype)

A generate → grade → revise pipeline for pharma email/web marketing
**drafts**. Built around two of the four loop patterns from
[LangChain's "Art of Loop Engineering"](https://www.langchain.com/blog/the-art-of-loop-engineering):

- **Loop 1 (agent/generator loop)** — `generator.py` turns a structured
  brief into a full HTML draft.
- **Loop 2 (verification loop)** — `grader.py` runs deterministic
  structural checks against the draft; `pipeline.py` feeds failures
  back into the generator for up to `MAX_ITERATIONS` revision passes.
- **Loop 4 (hill-climbing loop), lightweight version** —
  `trace_logger.py` + `analyze_traces.py` log every attempt so you can
  see which rules the generator trips on most often across many runs,
  and sharpen `prompts/generator_system.md` against real failure data.

Loop 3 (event-driven trigger — webhook/cron kicking off a run) isn't
built yet; `run_pipeline()` in `pipeline.py` is a plain function, so
wiring it behind a FastAPI endpoint or a queue consumer is a small
follow-up, not a redesign.

## What this is *not*

This does not replace ABPI/FDA MLR review. `PipelineResult.approved_for_production`
is hard-coded `False` on every run — passing all checks means the
draft is *structurally* complete (AE box present, HCP tag present, no
brand-name leak in unbranded copy, etc.), not that a qualified human
reviewer has signed off on the clinical claims, fair balance, or final
wording. Treat every checkmark as "ready for a human to review," never
"ready to send."

## Why the grader is rule-based, not another LLM call

An LLM grading its sibling's output can rationalize a near-miss as a
pass. Regex/DOM checks either find the bordered AE box or they don't —
the audit trail in `GradeReport` tells a human reviewer exactly which
rule fired and why, which is what actually makes this useful as a
demo of a *compliance-aware* pipeline rather than just a content
generator with an extra LLM call bolted on.

## Market-specific rules, not a hardcoded one-size-fits-all set

Early versions of this only varied *which acronym* (ABPI vs FDA/OPDP)
appeared in the footer per market — everything else was identical
regardless of market, which understates real differences (EU/UK
additional-monitoring black-triangle requirements, US Boxed Warning
placement rules, DTC advertising restrictions that don't exist in the
same form in the US). `regulatory.py::MARKET_MAP` now carries
market-specific notes alongside the regulatory tag, injected into the
generator's user prompt via `market_addendum()`, and `grader.py` has
two dedicated market-specific rules (`black_triangle` for UK/EU,
`boxed_warning` for US) on top of the 9 structural ones. Both are
non-blocking "confirm with regulatory" reminders, not pass/fail
verdicts — the tool has no way to know a specific product's actual
monitoring or Boxed Warning status, so it flags the question rather
than guessing the answer. Extending to more markets is adding an
entry to `MARKET_MAP`, not touching the grader's control flow.

## Token cost strategy

Three things keep this from burning tokens needlessly, in rough order
of impact:

1. **Fewer wasted iterations.** Market-specific guidance (black
   triangle, Boxed Warning) is now in the *first* generation call's
   prompt, not only surfaced after a failed check — a correct first
   draft costs one call end-to-end; a wrong one costs two full calls
   (generate + revise) for the same result.
2. **Prompt caching on the one big stable block.** `generator.py`'s
   `SYSTEM_PROMPT` is loaded once and reused byte-for-byte forever —
   it's deliberately market-agnostic (market content lives in the
   per-call user prompt instead) specifically so it stays one constant
   ~1000-token prefix. `llm_client.py` tags it with Anthropic's
   `cache_control: {"type": "ephemeral"}`, giving a ~90% discount on
   every call after the first. On Azure AI Foundry/OpenAI-compatible
   endpoints, caching on a >=1024-token repeated prefix is automatic —
   no code needed, which is also why the system prompt wasn't
   aggressively shrunk when asked to optimize; dropping it under
   ~1024 tokens would forfeit that automatic discount.
3. **Bounded loop + early exit.** `MAX_ITERATIONS = 3`, and the loop
   already stops as soon as only non-blocking warnings remain instead
   of spending a 3rd call chasing a check that was never going to
   block.

`LLMClient.last_usage` exposes real token/cache counts after every
call (`input_tokens`, `output_tokens`, and on Anthropic,
`cache_read_input_tokens` / `cache_creation_input_tokens`) — both
`app.py` and `pipeline.py`'s CLI smoke test print these so you can see
the discount happening, not just take it on faith.

## Setup

```bash
pip install -r requirements.txt

# Azure AI Foundry (matches your existing GPT-4o-mini deployment):
export AZURE_AI_FOUNDRY_ENDPOINT="https://<resource>.services.ai.azure.com/models"
export AZURE_AI_FOUNDRY_API_KEY="..."
export AZURE_AI_FOUNDRY_DEPLOYMENT="gpt-4o-mini"

# — or — Anthropic instead:
export ANTHROPIC_API_KEY="..."
```

## Run it

```bash
# CLI smoke test (mirrors your sample input: UK, HCP, Dovato, pre-launch awareness)
python pipeline.py

# Full UI
streamlit run app.py

# API Server
uvicorn api:app --reload

# Docker Deployment
docker build -t mlr-pipeline .
docker run -p 8000:8000 mlr-pipeline

# After you've run a few briefs through it:
python analyze_traces.py
```

## File map

| File | Role |
|---|---|
| `schema.py` | `CampaignBrief`, `GradeItem`, `GradeReport`, `PipelineResult` — the data contracts |
| `brand_config.py` | Per-brand color tokens + AE reporting line + PI placeholder (placeholders, not real brand-guideline values) |
| `regulatory.py` | Free-text market/audience resolution + per-market compliance notes (word-boundary matched, not naive substring) |
| `prompts/generator_system.md` | The Generator's system prompt — market-agnostic on purpose, see Token cost strategy below |
| `llm_client.py` | Provider-agnostic LLM wrapper (Azure AI Foundry / Anthropic) |
| `generator.py` | Brief → HTML, plus revision mode |
| `grader.py` | 9 deterministic structural rules, `BeautifulSoup`-based |
| `pipeline.py` | Orchestrates generate → grade → revise, up to 3 iterations |
| `trace_logger.py` / `analyze_traces.py` | Append-only run log + failure-rate analysis |
| `app.py` | Streamlit UI matching your sample input format |

## Validated against your uploaded templates

I ran `grader.py` against `DOVATO-UK-EMAIL-2026-004` as a sanity check
before handing this over: 8 of 9 rules passed cleanly, including
correctly detecting that the file is unbranded (product name only
appears in the internal annotation footer, never the visible body) and
correctly finding the ABPI reference and HCP-only line. The one
"failure" was the AE line not matching my placeholder wording verbatim
— expected, since that file predates this token system; it's not a
grader bug.

## Known gaps / next steps

- **`rule_ae_box`** matches the AE line against the brand token
  verbatim. That's correct for content this pipeline generated itself,
  but too strict if you ever grade externally-sourced HTML — consider
  a looser "known reporting mechanism per market" check for that case.
- **No image/logo asset pipeline** — logos stay labeled placeholders
  by design (see `prompts/generator_system.md`, rule 7); wiring in
  real approved assets is a deliberate separate step, not something to
  automate away.
- **Loop 3** (event trigger) — API layer added via FastAPI in `api.py`, which exposes `run_pipeline()` over HTTP.
