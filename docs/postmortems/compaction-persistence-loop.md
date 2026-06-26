# A silent vendor update broke my agent's memory
### Debugging field note: context compaction that built a summary every turn, then threw it away
*Field note, June 2026*

---

## What happened

One day the agent got slow on one channel. Casual chat, simple messages, one to three minutes to reply. The day before it was fast. I had changed nothing.

The frustrating part: a large, 1M-context model with prompt caching should not take two minutes to answer "ok". A cached prefix that size returns in seconds. So the slowness was not the model, and I spent a few hours proving that the hard way.

This is the write-up, including the three wrong theories I chased first, because the dead ends are the useful part.

## Three theories that were wrong

**1. "The session is bloated."** The slow session was huge, north of 300k tokens. Obvious culprit. I even started building a tool-result offloader to shrink it before I checked whether size was the problem.

It was not. I measured per-call latency against context size and it was flat. A 60k-token call and a 300k-token call both came back in about five seconds. With caching, context size is latency-neutral. Shrinking the context does nothing for speed. I reverted the offloader.

**2. "The memory tool is stuck."** It kept hitting its character cap and retrying, which looked like a retry loop eating the turn. But that store is shared across channels, and the other channel was fine. Same store, different speed. Not it.

**3. "Heavy tool loops."** Some turns fired twenty to thirty tool calls. Plausible, and wrong, and backwards. The slow channel was the casual one. The fast channel was the one doing hundreds of tool calls, scans, and external calls. Heavy work was fine. The casual chat was not.

At that point I stopped theorizing and started measuring.

## The method that actually worked

A reply's wall-clock is three separate clocks, not one:

1. pre-turn processing
2. the model's API calls
3. tool execution

You have to know which clock is running before you touch anything.

- The API calls were ~5s each at 100% cache. Fine.
- A few tool calls blocked for a minute or two (a hung shell wait, a web fetch with a six-minute timeout). Real, worth fixing, but not the main event.
- The gap between the message arriving and the model starting to think was 60 to 120 seconds. Every turn. There it was.

The slow part was happening before the model even began.

## Root cause

When a session grows too large, the gateway runs a "hygiene" pass before the turn: it summarizes the old history so the next request fits the window. On this session it ran every single turn, spent about two minutes building the summary, and then logged this:

> did not rotate or compact in place, preserving the original transcript

It threw the summary away. The session never shrank, so the next turn it loaded the full history again and recompacted it. A two-minute loop, forever, with nothing to show for it.

Why it could not save: a recent auto-update had refactored that path. The hygiene worker is now built without a database handle, and persistence depends on an in-place-compaction flag. That flag defaults to off, and the update did not turn it on. The release note said "no new settings to configure." So it shipped a quiet regression. Compaction computes the answer and has no way to write it down.

The forensic part lined up cleanly. The first failure log appeared about two hours after the update started, and the two compaction source files were rewritten at that exact minute. Before the update, the same kind of long session compacted fine.

## The fix

One line: turn the in-place flag on.

Now the gateway persists the summary through its own working database handle instead of the worker's missing one. The session drops from ~360 messages to about a dozen, and replies are fast again. The agent does not go blank either. It keeps a reference summary of the old history, the recent turns word-for-word, and its long-term memory. Continuity holds, the loop is gone.

## What I would tell myself

- Context size is not latency. Caching makes a full window cheap and fast per call. Don't fix slowness by shrinking context. Wrong axis.
- Decompose before you fix. Pre-turn, model, and tools are three different clocks. Measure which one is running.
- The model is rarely the slow part. A two-minute reply is almost never the model thinking. It's a pre-turn step or a blocking tool.
- A sudden break you did not cause is probably a vendor update. Check the update log and the file timestamps first. It would have pointed me at the answer on minute one.
- Be wrong out loud and move on. I burned hours on three theories that each felt obvious. Ten minutes of measuring would have killed all three.

The bug was upstream and not mine to prevent. The hours were mine, and they were spent on assuming instead of measuring. That's the lesson worth keeping.
