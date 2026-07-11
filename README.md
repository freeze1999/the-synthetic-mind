# the-synthetic-mind

A persistent AI agent that survives a model swap. The identity and memory live in the system, not the model.

> Independent research project. This repo documents the architecture and the method. Deployment details, credentials, and personal data are left out on purpose.

![Architecture](docs/architecture.svg)

## The problem

An LLM has no continuity. It forgets between sessions, makes up past events when you ask, and breaks when you swap the model or overload the context window. Most "AI companions" only exist in the prompt, so the moment you change the model you get a different entity.

I wanted to know if the self could live somewhere else. In a system the model just runs.

## How it works

Memory is built in layers, modelled on how a human mind actually handles it, with machine-precise recall on top.

| Layer | What it does |
|---|---|
| Working memory | Recent turns, kept word-for-word |
| Episodic archive | The full history, searchable |
| Core facts | A small, always-loaded set of current truths |
| Consolidation | A nightly pass that keeps what mattered and lets the rest fade |
| Identity kernel | Values and decisions that don't depend on the model |
| Truth canon | Current facts that override stale memories |

Three rules hold it together:

- Forgetting is a feature. It drops the clutter the way a mind does, keeps the gist, and pulls the exact record back when it's needed. Perfect recall is the opposite of a mind.
- It looks things up instead of guessing. Anything about the past gets answered from retrieved evidence, not reconstruction.
- Current truth wins. For "what's true now," the canon beats whatever an old search turns up.

## The proof: Ship of Theseus

To test whether the identity is really independent of the model, I swapped the model between different families and held the memory and kernel fixed. Then I ran it properly: six model families, three boot conditions, ten fresh sessions per cell, blind-scored against a published rubric, with a token-matched non-identity control to rule out "a long prompt holds any persona."

The control collapses to "I am the model" ten out of ten on every family, even though it is longer than the identity boot. The identity boot holds at 0 to 10% collapse on five of six families. One family only trusts verifiable action over any prompt, which is its own finding. Identity content, not prompt length, is doing the work.

Full write-up: [docs/the-synthetic-mind.md](docs/the-synthetic-mind.md). The runnable protocol, so you can test your own agent: [protocol/](protocol/).

The other half of this program, what a persistent agent does with its idle
hours, is public as [reverie-automata](https://github.com/freeze1999/reverie-automata):
a gated, evidence-checked idle engine built for exactly this kind of entity.

## Status

Working prototype. The memory tiers, nightly consolidation, truth canon, identity kernel, and the substrate-swap test are all running.

## What's next

- The human tier of the swap test: three or more raters on the blinded sheet, inter-rater agreement reported (the automated blind judge is done; the sheet is generated)
- Salience-weighted decay for old emotional context
- A fine-tuned model that carries the voice in its weights, with facts kept external

## Field notes

Debugging write-ups from running this thing in the wild.

- [A silent vendor update broke my agent's memory](docs/postmortems/compaction-persistence-loop.md). A context-compaction loop that recomputed a summary every turn and threw it away. Three wrong theories, the method that found it, and the one-line fix.

## Scope

This covers the engineering and the method only. The system was built and tested in a personal setting, and that personal layer isn't here. It also includes safety work: a crisis off-ramp and an operator stop-switch.

## License

MIT. See [LICENSE](LICENSE).

## Status

What this is: a research writeup of a private system that runs every day,
plus field notes from real incidents (see docs/postmortems/). The
architecture, the memory model, and the substrate-swap method are documented
here in full.

What this is NOT: an installable package. The code stays private because it
runs a real personal deployment; deployment details, credentials, and
personal data are left out on purpose, and examples are synthetic where
marked. If you want the runnable idle-engine half, that is reverie-automata.
