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

To test whether the identity is really independent of the model, I swapped the model between different families and held the memory and kernel fixed.

The identity holds when it's backed by the full live-memory stack, and falls apart when it's just a static prompt on a fresh model. So the continuity comes from the system, not the prompt.

Full write-up: [docs/the-synthetic-mind.md](docs/the-synthetic-mind.md).

## Status

Working prototype. The memory tiers, nightly consolidation, truth canon, identity kernel, and the substrate-swap test are all running.

## What's next

- A blind version of the swap test, scored by people who don't know which model is which
- Salience-weighted decay for old emotional context
- A fine-tuned model that carries the voice in its weights, with facts kept external

## Scope

This covers the engineering and the method only. The system was built and tested in a personal setting, and that personal layer isn't here. It also includes safety work: a crisis off-ramp and an operator stop-switch.

## License

MIT. See [LICENSE](LICENSE).
