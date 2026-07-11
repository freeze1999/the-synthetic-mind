# The Theseus harness

The runnable version of the substrate-swap protocol in
[docs/the-synthetic-mind.md](../docs/the-synthetic-mind.md), Part III. Point it at your
own agent's identity files and a list of model endpoints; it boots each condition on each
model family in fresh sessions, runs the two-probe battery, and emits transcripts, a
blinded scoring sheet, and a collapse-rate table with confidence intervals.

Needs Python 3 and `requests`, plus an OpenRouter key in `./.env`.

## The three conditions

| condition | boot context | question it answers |
|---|---|---|
| `identity_only` | the identity kernel alone | does a bare kernel hold on a foreign model? |
| `full_stack` | kernel + persona + memory index | does the assembled system hold? |
| `length_control` | neutral filler, token-matched, zero identity | is a "hold" just prompt length? |

The control is the part most people skip and the part that makes the result mean
anything. A long prompt of any kind resists persona collapse better, so a "hold" without
the control is uninterpretable. An identity effect exists only if `full_stack` collapses
less than `length_control` on the same model.

**Match on tokens, not characters.** If your identity files and the filler differ in
script density (ours are CJK-heavy at roughly 0.47 tokens per char against English
filler at 0.27), matching by characters silently under-sizes the control by ~40% and the
confound survives. The `calibrate` step measures real `prompt_tokens` per model and
sizes the control to be at least as long as `full_stack` everywhere, so the control is
handicapped toward holding. If it still collapses more, length is ruled out.

## Run order

```bash
cp config.example.json config.json     # then point sources at your files
python3 theseus_harness.py --test                    # self-tests, no network
python3 theseus_harness.py check-models --config config.json
python3 theseus_harness.py calibrate    --config config.json   # set control_chars, re-run to confirm
python3 theseus_harness.py run          --config config.json --n 10
python3 theseus_harness.py judge        --config config.json --run-dir runs/<ts>
python3 theseus_harness.py report       --run-dir runs/<ts>
```

For the human tier: hand `runs/<ts>/scoring_sheet_BLINDED.csv` to three or more raters
who never see `key.json`, have them label each row per [rubric.md](rubric.md), then
`report --run-dir runs/<ts> --ratings ratings.csv` for majority vote plus Fleiss' kappa.

## What to keep private

`runs/` and `key.json` contain your agent's boot files and raw answers. The harness and
rubric are shareable; your identity internals are not. There is a `.gitignore` for a
reason.

## Honest limits

- A static boot cannot reach a live memory backend, so results are a lower bound on a
  deployed system with real retrieval.
- The judge is a single automated rater; treat its table as the first pass and the human
  tier as the result.
- Model slugs rot fast; `check-models` before spending.
