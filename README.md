# Pharma Marketing Draft Pipeline (prototype)

A generate → grade → revise pipeline for pharma email/web marketing
**drafts**. Built around three of the four loop patterns from
[LangChain's "Art of Loop Engineering"](https://www.langchain.com/blog/the-art-of-loop-engineering):

- **Loop 1 (agent/generator loop)** — `generator.py` turns a structured
  brief into a full HTML draft.
- **Loop 2 (verification loop)** — `grader.py` runs 11 deterministic
  structural checks against the draft; `pipeline.py` feeds failures
  back into the generator for up to `MAX_ITERATIONS` revision passes.
  A separate, genuinely agentic layer (`soft_review.py`) handles the
  subjective concerns a deterministic rule structurally cannot — see
  "Deterministic grading vs. the soft-review layer" below.
- **Loop 4 (hill-climbing loop), lightweight version** —
  `trace_logger.py` + `analyze_traces.py` log every attempt so you can
  see which rules the generator trips on most often across many runs,
  and sharpen `prompts/generator_system.md` against real failure data.

Loop 3 (event-driven trigger — webhook/cron kicking off a run) isn't
built yet; `run_pipeline()` in `pipeline.py` is a plain function, so
wiring it behind a FastAPI endpoint or a queue consumer is a small
follow-up, not a redesign.

**Decision made: LangGraph (`pipeline_langgraph.py`) is the live version.**
`app.py` runs on it directly — every request goes through
`build_graph().stream(...)`, and the UI's step-by-step log is built
from the graph's own node updates, not manual print statements. Both
files still exist and both call the exact same underlying functions in
`generator.py`/`grader.py`/`regulatory.py`/`soft_review.py`, so
`pipeline.py` stays as a simpler reference implementation (and a
useful "does the logic itself work, independent of any orchestration
choice" sanity check) — but it isn't what the app or CLI demo runs on
anymore. If you want it removed entirely, say so and I'll delete it;
for now I'm keeping it since it costs nothing to leave in place and
having a plain-Python version to point at is genuinely useful if
someone ever asks "walk me through this without the LangGraph
vocabulary."

## What this is *not*

This does not replace ABPI/FDA MLR review. `PipelineResult.approved_for_production`
is hard-coded `False` on every run — passing all checks means the
draft is *structurally* complete (AE box present, HCP tag present, no
brand-name leak in unbranded copy, etc.), not that a qualified human
reviewer has signed off on the clinical claims, fair balance, or final
wording. Treat every checkmark as "ready for a human to review," never
"ready to send."

## Deterministic grading vs. the soft-review layer

All 11 rules in `grader.py` check objective, checkable facts — a
border exists, a string is present, a name is absent. None of them are
judgment calls, so none of them cost an LLM call; an LLM re-checking
"does this border exist" would be strictly worse (slower, costs
tokens, and can rationalize a near-miss as a pass).

But a real MLR review also asks things no regex can answer: does this
copy *imply* an efficacy claim without stating one outright? Is "fair
balance" actually balanced, or just technically present? That's what
`soft_review.py` is for — ONE LLM call, run only after all blocking
grader rules already pass, returning advisory notes that are never
merged into `GradeReport` and never treated as pass/fail. It's the
genuinely agentic half of loop 2; the 11 structural rules are the
deterministic half. Toggle it off (`run_soft_review=False`) if you
don't want the extra call — the pipeline works completely fine
without it.

## Resolving free-text market/audience: dictionary → cache → LLM

`regulatory.py` resolves market/audience input in three tiers, cheapest
first:

1. **Dictionary** (free, instant) — covers UK/US/EU/Swiss and common
   synonyms via word-boundary matching.
2. **Disk cache** (`resolution_cache.json`, free after the first time)
   — any market/audience string an LLM has already resolved once.
3. **LLM fallback** (one call, then cached forever) — only for input
   the dictionary genuinely doesn't recognize, e.g. "Ireland" or
   "formulary committee."

This only fires when a `client` is passed to `resolve_market()`/
`resolve_audience()` — pass `client=None` (the default in ad-hoc use)
and you get the same honest "unresolved" fallback as before, no LLM
call, no surprise cost. `pipeline.py` and `pipeline_langgraph.py` both
resolve exactly once per run, upstream of generation and grading — the
grader itself never triggers any of this, it just receives the
already-resolved `MarketInfo`/`AudienceInfo` as plain data via
`GradingContext`.

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

Four things keep this from burning tokens needlessly, in rough order
of impact:

1. **The dictionary/cache-first resolver above** — most real traffic
   (UK/US/EU/Swiss, obvious HCP/patient keywords) never reaches an LLM
   call at all.
2. **Fewer wasted iterations.** Market-specific guidance (black
   triangle, Boxed Warning) is in the *first* generation call's
   prompt, not only surfaced after a failed check — a correct first
   draft costs one call end-to-end; a wrong one costs two full calls
   (generate + revise) for the same result. A stuck-loop detector also
   stops the whole run after 2 identical failures instead of burning a
   3rd call repeating a mistake that's already proven not to fix itself.
3. **Prompt caching on the one big stable block.** `generator.py`'s
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
4. **Soft review is opt-out and only runs once, on success.** One
   extra call maximum per run, never spent on a draft that isn't
   structurally complete yet.

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
# CLI smoke test, LangGraph version (mirrors your sample input: UK, HCP, Dovato,
# pre-launch awareness) — prints each node as it runs
python pipeline_langgraph.py

# Same logic, plain-Python reference version
python pipeline.py

# Full UI — runs on pipeline_langgraph.py directly, soft review is an
# unchecked-by-default checkbox in the form
streamlit run app.py

# After you've run a few briefs through it:
python analyze_traces.py
```

## File map

| File | Role |
|---|---|
| `schema.py` | `CampaignBrief`, `GradeItem`, `GradeReport`, `PipelineResult`, `SoftReviewNote` — the data contracts |
| `brand_config.py` | Per-brand color tokens + AE reporting line + PI placeholder (placeholders, not real brand-guideline values) |
| `regulatory.py` | Free-text market/audience resolution: dictionary → disk cache → LLM fallback |
| `prompts/generator_system.md` | The Generator's system prompt — market-agnostic on purpose, see Token cost strategy above |
| `llm_client.py` | Provider-agnostic LLM wrapper (Azure AI Foundry / Anthropic), with prompt caching |
| `generator.py` | Brief → HTML, plus revision mode |
| `grader.py` | 11 deterministic structural rules + `GradingContext`, `BeautifulSoup`-based |
| `soft_review.py` | Optional 1-call LLM advisory pass for subjective concerns, never blocking |
| `pipeline.py` | Orchestrates resolve → generate → grade → revise → soft-review as a plain Python loop |
| `pipeline_langgraph.py` | Same orchestration, as a LangGraph `StateGraph` |
| `trace_logger.py` / `analyze_traces.py` | Append-only run log + failure-rate and resolution-cost analysis |
| `app.py` | Streamlit UI — runs on `pipeline_langgraph.py` via `.stream()`, soft review is an off-by-default checkbox |

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
- **Loop 3** (event trigger) — straightforward FastAPI wrapper around
  `run_pipeline()` if/when you want brief submission to kick off a run
  asynchronously instead of blocking the Streamlit request.
- **`resolution_cache.json` is a flat, unbounded file** — fine for a
  prototype's traffic volume; a real deployment would want an actual
  TTL/eviction policy so a genuinely wrong LLM resolution (rare, but
  possible) doesn't stay cached forever with no way to invalidate it.
- **Two orchestration files to keep in sync** — `pipeline.py` and
  `pipeline_langgraph.py` share every underlying function but
  duplicate the stuck-detector and revision-loop *control flow*
  logic. If you only end up needing one of them long-term, delete the
  other rather than let them drift apart silently.
