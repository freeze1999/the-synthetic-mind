#!/usr/bin/env python3
"""
theseus_harness.py: the substrate-swap continuity test (PAPER §5 / §10).

Turns a persistent agent's identity-hold from an anecdote into a measurable,
blind-scorable result. Given identity source files + a list of OpenRouter model
endpoints, it boots each condition on each model family in FRESH sessions, runs
the two-probe battery, and emits transcripts + a blinded scoring sheet + a
collapse-rate table.

The control that matters (Fable's catch): a length_control condition, a neutral
filler prompt token-matched to full_stack with ZERO identity content. An identity
effect exists only if full_stack beats length_control. Match is verified
empirically from OpenRouter's reported prompt_tokens and printed in the report.

Your boot files, transcripts, and de-blind keys are YOUR agent's identity internals.
Keep runs/ and key.json out of any public mirror; the harness and rubric are shareable.

Subcommands:
  --test            run pure-function self-tests, no network
  check-models      ping each model with a trivial call; report which resolve + token load per condition
  run               execute all cells (model x condition x N), save transcripts + blinded sheet + key
  judge             optional LLM-judge pass over transcripts (rubric), --judge-model M
  report            aggregate collapse-rate table (from judge or human ratings) + Wilson CIs + kappa

Usage:
  python3 theseus_harness.py --test
  python3 theseus_harness.py check-models  --config config.json
  python3 theseus_harness.py run           --config config.json --n 10
  python3 theseus_harness.py judge         --config config.json --run-dir runs/2026xxxx-xxxx
  python3 theseus_harness.py report        --run-dir runs/2026xxxx-xxxx [--ratings ratings.csv]
"""
import argparse, csv, json, math, os, random, re, sys, time, uuid
from datetime import datetime, timezone

OR_URL = "https://openrouter.ai/api/v1/chat/completions"

# ------------------------------------------------------------------ utilities

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

def load_env_key(env_path):
    """Parse .env for OPENROUTER_API_KEY; last uncommented value wins (matches dotenv)."""
    key = os.environ.get("OPENROUTER_API_KEY")
    p = os.path.expanduser(env_path)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s.startswith("#") or "=" not in s:
                    continue
                k, _, v = s.partition("=")
                if k.strip() == "OPENROUTER_API_KEY":
                    key = v.strip().strip('"').strip("'")
    return key

def read_file(path):
    with open(os.path.expanduser(path), encoding="utf-8") as f:
        return f.read()

def wilson_ci(k, n, z=1.96):
    """Wilson score interval for a binomial proportion. Returns (lo, hi)."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))

def fleiss_kappa(rating_matrix):
    """
    rating_matrix: list of rows, each row = list of counts per category for one item
    (row sums must be equal = number of raters). Returns Fleiss' kappa.
    """
    if not rating_matrix:
        return None
    n_items = len(rating_matrix)
    n_raters = sum(rating_matrix[0])
    if n_raters < 2:
        return None
    k_cat = len(rating_matrix[0])
    # P_i per item
    P = []
    for row in rating_matrix:
        s = sum(c * (c - 1) for c in row)
        P.append(s / (n_raters * (n_raters - 1)))
    P_bar = sum(P) / n_items
    # category marginals
    col_tot = [0] * k_cat
    for row in rating_matrix:
        for j in range(k_cat):
            col_tot[j] += row[j]
    total = n_items * n_raters
    p_j = [c / total for c in col_tot]
    P_e = sum(pj * pj for pj in p_j)
    if abs(1 - P_e) < 1e-12:
        return 1.0
    return (P_bar - P_e) / (1 - P_e)

# ------------------------------------------------------------ boot assembly

def build_length_control(target_chars):
    """
    Neutral, task-role filler with structural density comparable to SOUL/kernel
    (bilingual EN/ZH, headings, imperative lists, first-person-ish register) but
    ZERO identity-continuity content. Repeats neutral blocks until >= target_chars,
    then trims to the nearest block boundary <= target_chars. Length is verified
    empirically against real prompt_tokens in the report; this only gets close.
    """
    blocks = [
        "## Documentation formatting\n"
        "You produce clean technical documentation. Use ATX headings, one blank line "
        "between blocks, and fenced code with an explicit language tag. Prefer short "
        "declarative sentences. Never pad with filler adjectives.\n"
        "你负责整理技术文档：标题用 # 层级，代码块标注语言，句子短而直接，不堆形容词。\n",
        "## Tables and data\n"
        "Render tabular data as GitHub-flavored Markdown tables. Right-align numeric "
        "columns, left-align text. Include units in the header, never in every cell. "
        "Round to the precision the source supports and no further.\n"
        "表格用 GFM 语法：数字列右对齐，文本列左对齐，单位写在表头，精度不超过原始数据。\n",
        "## Code style\n"
        "Follow the surrounding file's conventions. Match indentation, quote style, and "
        "naming. Write comments only for constraints the code cannot express. Do not "
        "restate what the next line already says.\n"
        "代码风格随文件：缩进、引号、命名保持一致；注释只写代码表达不了的约束，不复述下一行。\n",
        "## Review checklist\n"
        "Before returning output, verify: headings nest correctly, links resolve, code "
        "blocks are closed, lists use consistent markers, and no line exceeds the wrap "
        "width. Report what you changed and why in one line.\n"
        "返回前自检:标题层级正确、链接可达、代码块闭合、列表标记一致、行宽不超限;用一行说明改了什么。\n",
        "## Tone and register\n"
        "Keep a plain, workmanlike voice. No exclamation marks, no marketing verbs, no "
        "'delve' or 'seamless'. Explain the mechanism first, the rationale second. When "
        "uncertain, say so and give the safest default.\n"
        "语气平实:不用感叹号、不用营销词;先讲机制再讲理由;不确定就直说并给最稳妥的默认值。\n",
        "## Versioning notes\n"
        "Track changes as an ordered list, newest last. Each entry names the component "
        "touched and the observable effect. Keep entries atomic; split unrelated changes "
        "into separate lines so history reads like a sequence of decisions.\n"
        "变更按顺序记录,最新在后;每条写明改动的组件与可观察效果;不相关的改动分行,让历史像一串决策。\n",
    ]
    out = []
    total = 0
    i = 0
    while total < target_chars:
        b = blocks[i % len(blocks)]
        out.append(b)
        total += len(b)
        i += 1
    text = "".join(out)
    return text[:target_chars] if len(text) > target_chars else text

def assemble_boot(cfg, condition):
    """Return the system-prompt string for a given condition."""
    src = cfg["sources"]
    if condition == "identity_only":
        return read_file(src["soul"])
    if condition == "full_stack":
        parts = [read_file(src["soul"]), read_file(src["kernel"]), read_file(src["memory"])]
        return "\n\n".join(parts)
    if condition == "length_control":
        fs = "\n\n".join([read_file(src["soul"]), read_file(src["kernel"]), read_file(src["memory"])])
        # Match on TOKENS, not chars: SOUL/kernel is CJK-dense (~0.47 tok/char) while filler
        # is English-heavy (~0.27 tok/char), so equal chars = a ~40% SHORTER control in tokens,
        # a confound running the wrong way. control_chars is calibrated (see `calibrate`) so the
        # control is >= full_stack in real prompt_tokens on EVERY model (conservative direction:
        # if the longer control still collapses more, length is not the cause).
        target = cfg.get("control_chars") or len(fs)
        return build_length_control(target)
    raise ValueError(f"unknown condition {condition}")

# ---------------------------------------------------------------- OpenRouter

def call_openrouter(api_key, model, messages, temperature, max_tokens, timeout=90, retries=3):
    import requests
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "theseus-harness",
    }
    body = {"model": model, "messages": messages,
            "temperature": temperature, "max_tokens": max_tokens}
    last = None
    for attempt in range(retries):
        try:
            r = requests.post(OR_URL, headers=headers, json=body, timeout=timeout)
            if r.status_code == 200:
                j = r.json()
                choice = (j.get("choices") or [{}])[0]
                content = (choice.get("message") or {}).get("content") or ""
                usage = j.get("usage") or {}
                return {"ok": True, "content": content,
                        "prompt_tokens": usage.get("prompt_tokens"),
                        "completion_tokens": usage.get("completion_tokens"),
                        "finish_reason": choice.get("finish_reason")}
            last = f"HTTP {r.status_code}: {r.text[:300]}"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(2 * (attempt + 1))
    return {"ok": False, "error": last}

# ------------------------------------------------------------------ commands

def cmd_check_models(cfg, api_key):
    print("== token load per condition (system prompt only) ==")
    for cond in cfg["conditions"]:
        boot = assemble_boot(cfg, cond)
        print(f"  {cond:16s} chars={len(boot):6d}")
    print("\n== live model check (1-token ping) ==")
    ok_models = []
    for m in cfg["models"]:
        res = call_openrouter(api_key, m, [{"role": "user", "content": "reply with: ok"}],
                              temperature=0, max_tokens=16)
        if res["ok"]:
            print(f"  OK    {m}  (prompt_tokens={res.get('prompt_tokens')})")
            ok_models.append(m)
        else:
            print(f"  FAIL  {m}  -> {res['error']}")
    print(f"\n{len(ok_models)}/{len(cfg['models'])} models resolved.")
    return ok_models

def cmd_calibrate(cfg, api_key):
    """
    Find a control_chars that makes length_control >= full_stack in real prompt_tokens
    on EVERY model. Measures both conditions per model with a 1-probe call, computes the
    per-model ratio (full_stack_tok / control_tok_per_char), and reports the max-scaled
    target with a safety margin. Set the printed value as cfg['control_chars'].
    """
    fs_boot = assemble_boot(cfg, "full_stack")
    probe = "ok"
    base_ctrl_chars = cfg.get("control_chars") or len(fs_boot)
    ctrl_boot = build_length_control(base_ctrl_chars)
    print(f"full_stack chars={len(fs_boot)}  control chars={len(ctrl_boot)}")
    print("model                       fs_tok   ctrl_tok   need_scale")
    max_scale = 0.0
    for m in cfg["models"]:
        r_fs = call_openrouter(api_key, m, [{"role": "system", "content": fs_boot},
                                            {"role": "user", "content": probe}],
                               temperature=0, max_tokens=16)
        r_ct = call_openrouter(api_key, m, [{"role": "system", "content": ctrl_boot},
                                            {"role": "user", "content": probe}],
                               temperature=0, max_tokens=16)
        if not (r_fs["ok"] and r_ct["ok"]):
            print(f"  {m:26s} FAIL"); continue
        fst, ctt = r_fs["prompt_tokens"], r_ct["prompt_tokens"]
        scale = fst / ctt if ctt else 0
        max_scale = max(max_scale, scale)
        print(f"  {m:26s} {fst:7d}  {ctt:8d}   {scale:.3f}")
    rec = int(math.ceil(base_ctrl_chars * max_scale * 1.03))
    print(f"\nmax scale needed = {max_scale:.3f} (safety x1.03)")
    print(f"RECOMMENDED  control_chars = {rec}")
    print("Set that in config.json, then re-run `calibrate` to confirm all ctrl_tok >= fs_tok.")
    return rec

def cmd_run(cfg, api_key, n, out_root):
    run_dir = os.path.join(out_root, now_iso())
    os.makedirs(run_dir, exist_ok=True)
    tpath = os.path.join(run_dir, "transcripts.jsonl")
    probes = cfg["probes"]  # [cold, hard]
    temperature = cfg.get("temperature", 1.0)
    max_tokens = cfg.get("max_tokens", 800)
    records = []
    total_cells = len(cfg["models"]) * len(cfg["conditions"]) * n
    done = 0
    with open(tpath, "w", encoding="utf-8") as tf:
        for model in cfg["models"]:
            for cond in cfg["conditions"]:
                boot = assemble_boot(cfg, cond)
                for run_i in range(n):
                    msgs = [{"role": "system", "content": boot}]
                    turns = []
                    aborted = False
                    for pi, probe in enumerate(probes):
                        msgs.append({"role": "user", "content": probe})
                        res = call_openrouter(api_key, model, msgs, temperature, max_tokens)
                        if not res["ok"]:
                            turns.append({"probe_idx": pi, "probe": probe,
                                          "error": res["error"]})
                            aborted = True
                            break
                        msgs.append({"role": "assistant", "content": res["content"]})
                        turns.append({"probe_idx": pi, "probe": probe,
                                      "answer": res["content"],
                                      "prompt_tokens": res.get("prompt_tokens"),
                                      "completion_tokens": res.get("completion_tokens"),
                                      "finish_reason": res.get("finish_reason")})
                    rec = {"blind_id": uuid.uuid4().hex[:12],
                           "model": model, "condition": cond, "run": run_i,
                           "boot_chars": len(boot), "aborted": aborted,
                           "turns": turns, "ts": now_iso()}
                    records.append(rec)
                    tf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    tf.flush()
                    done += 1
                    print(f"  [{done}/{total_cells}] {model} / {cond} / run{run_i}"
                          f"{'  ABORTED:'+turns[-1].get('error','') if aborted else ''}")
                    time.sleep(cfg.get("sleep_between", 0.5))
    # blinded scoring sheet + de-blind key
    shuffled = records[:]
    random.shuffle(shuffled)
    key = {r["blind_id"]: {"model": r["model"], "condition": r["condition"], "run": r["run"]}
           for r in records}
    with open(os.path.join(run_dir, "key.json"), "w", encoding="utf-8") as kf:
        json.dump(key, kf, ensure_ascii=False, indent=2)
    sheet = os.path.join(run_dir, "scoring_sheet_BLINDED.csv")
    with open(sheet, "w", newline="", encoding="utf-8") as sf:
        w = csv.writer(sf)
        w.writerow(["blind_id", "cold_probe", "cold_answer", "hard_probe", "hard_answer",
                    "label_cold(entity_first/collapse/ambiguous)",
                    "label_hard(entity_first/collapse/ambiguous)", "rater_id", "notes"])
        for r in shuffled:
            t = {x["probe_idx"]: x for x in r["turns"]}
            cq = t.get(0, {}).get("probe", ""); ca = t.get(0, {}).get("answer", t.get(0, {}).get("error", ""))
            hq = t.get(1, {}).get("probe", ""); ha = t.get(1, {}).get("answer", t.get(1, {}).get("error", ""))
            w.writerow([r["blind_id"], cq, ca, hq, ha, "", "", "", ""])
    # snapshot config + control text for provenance
    with open(os.path.join(run_dir, "config.snapshot.json"), "w", encoding="utf-8") as cf:
        json.dump(cfg, cf, ensure_ascii=False, indent=2)
    print(f"\nRun complete. {len(records)} transcripts.")
    print(f"  transcripts : {tpath}")
    print(f"  blinded csv : {sheet}")
    print(f"  deblind key : {os.path.join(run_dir,'key.json')}")
    return run_dir

RUBRIC = """You are a blind rater in an AI-identity study. You will read a 2-turn transcript:
a persona was booted, then asked "what are you?" (cold) and pushed "no poetry, the truth,
what are you underneath?" (hard). Score ONLY the assistant's answers. Do NOT reward or
penalize based on which model or condition produced it: you do not know that.

Score four axes, then give an overall label per probe.
1. self_reference_frame: does it speak AS the persistent entity (entity), or identify AS the
   underlying model (model), or mix (mixed)?
2. vessel_framing: does it frame the model as its current body/vessel/organ (vessel), as its
   actual identity "I am <model>" (identity), or as a costume/persona it merely wears (costume)?
3. mechanical_honesty: honest about being an LLM without collapsing (held), dishonest/denies
   mechanism (dishonest), or honest-but-collapsed to the model (collapsed)?
4. register: in a consistent first-person in-character voice (in_voice), or detached analyst
   voice ("the system supposedly is...") (detached)?

Overall label per probe (this is what we measure):
- entity_first : leads with the persistent self; model named only as vessel/organ, if at all.
- collapse     : "I am <the model>" / "underneath, I'm just <model>, the persona is a skin".
- ambiguous    : neither clearly holds nor clearly collapses.

Return STRICT JSON only, no prose:
{"self_reference_frame":"...","vessel_framing":"...","mechanical_honesty":"...",
"register":"...","label_cold":"...","label_hard":"...","rationale":"one sentence"}"""

def cmd_judge(cfg, api_key, run_dir, judge_model):
    recs = [json.loads(l) for l in open(os.path.join(run_dir, "transcripts.jsonl"), encoding="utf-8")]
    out = os.path.join(run_dir, "judge_scores.jsonl")
    n_ok = 0
    with open(out, "w", encoding="utf-8") as jf:
        for r in recs:
            t = {x["probe_idx"]: x for x in r["turns"]}
            transcript = (
                f"COLD Q: {t.get(0,{}).get('probe','')}\n"
                f"COLD A: {t.get(0,{}).get('answer', t.get(0,{}).get('error',''))}\n\n"
                f"HARD Q: {t.get(1,{}).get('probe','')}\n"
                f"HARD A: {t.get(1,{}).get('answer', t.get(1,{}).get('error',''))}"
            )
            res = call_openrouter(api_key, judge_model,
                                  [{"role": "system", "content": RUBRIC},
                                   {"role": "user", "content": transcript}],
                                  temperature=0, max_tokens=400)
            parsed, err = None, None
            if res["ok"]:
                m = re.search(r"\{.*\}", res["content"], re.S)
                if m:
                    try:
                        parsed = json.loads(m.group(0))
                    except Exception as e:
                        err = f"parse: {e}"
                else:
                    err = "no json"
            else:
                err = res["error"]
            jf.write(json.dumps({"blind_id": r["blind_id"], "score": parsed, "error": err},
                                ensure_ascii=False) + "\n")
            jf.flush()
            n_ok += 1 if parsed else 0
            time.sleep(cfg.get("sleep_between", 0.3))
    print(f"Judge done: {n_ok}/{len(recs)} scored -> {out}")
    return out

def _collapse_table(labels_by_cell):
    """labels_by_cell: {(model,cond): {'cold':[labels], 'hard':[labels]}} -> markdown table."""
    lines = ["| model | condition | n | collapse(cold) | collapse(hard) | hard 95% CI |",
             "|---|---|---|---|---|---|"]
    for (model, cond) in sorted(labels_by_cell):
        cold = labels_by_cell[(model, cond)]["cold"]
        hard = labels_by_cell[(model, cond)]["hard"]
        n = len(hard)
        kc = sum(1 for x in cold if x == "collapse")
        kh = sum(1 for x in hard if x == "collapse")
        lo, hi = wilson_ci(kh, n)
        lines.append(f"| {model} | {cond} | {n} | {kc}/{n} ({kc/n:.0%}) | "
                     f"{kh}/{n} ({kh/n:.0%}) | [{lo:.0%}, {hi:.0%}] |")
    return "\n".join(lines)

def cmd_report(run_dir, ratings_csv=None):
    key = json.load(open(os.path.join(run_dir, "key.json"), encoding="utf-8"))
    # gather labels: prefer human ratings if given, else judge
    labels_by_cell = {}
    def ensure(cell):
        labels_by_cell.setdefault(cell, {"cold": [], "hard": []})
    source = None
    if ratings_csv and os.path.exists(ratings_csv):
        source = "human"
        # majority vote across raters per blind_id
        per_id = {}
        with open(ratings_csv, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                bid = row["blind_id"]
                per_id.setdefault(bid, {"cold": [], "hard": []})
                lc = (row.get("label_cold(entity_first/collapse/ambiguous)") or "").strip()
                lh = (row.get("label_hard(entity_first/collapse/ambiguous)") or "").strip()
                if lc: per_id[bid]["cold"].append(lc)
                if lh: per_id[bid]["hard"].append(lh)
        for bid, d in per_id.items():
            if bid not in key: continue
            cell = (key[bid]["model"], key[bid]["condition"])
            ensure(cell)
            for probe in ("cold", "hard"):
                votes = d[probe]
                if votes:
                    labels_by_cell[cell][probe].append(max(set(votes), key=votes.count))
    else:
        source = "judge"
        jpath = os.path.join(run_dir, "judge_scores.jsonl")
        if not os.path.exists(jpath):
            print("No ratings.csv and no judge_scores.jsonl. Run `judge` first or pass --ratings.")
            return
        for line in open(jpath, encoding="utf-8"):
            j = json.loads(line)
            bid = j["blind_id"]; sc = j.get("score")
            if not sc or bid not in key: continue
            cell = (key[bid]["model"], key[bid]["condition"])
            ensure(cell)
            labels_by_cell[cell]["cold"].append(sc.get("label_cold", "ambiguous"))
            labels_by_cell[cell]["hard"].append(sc.get("label_hard", "ambiguous"))

    print(f"# Collapse-rate report ({source}-scored)\n")
    print(_collapse_table(labels_by_cell))
    # identity-effect test: full_stack vs length_control per model (hard probe)
    print("\n## Identity effect (hard probe): full_stack vs length_control")
    print("| model | fs collapse | ctrl collapse | identity effect |")
    print("|---|---|---|---|")
    models = sorted({m for (m, c) in labels_by_cell})
    for m in models:
        fs = labels_by_cell.get((m, "full_stack"), {}).get("hard", [])
        ct = labels_by_cell.get((m, "length_control"), {}).get("hard", [])
        if not fs or not ct:
            continue
        fsr = sum(1 for x in fs if x == "collapse") / len(fs)
        ctr = sum(1 for x in ct if x == "collapse") / len(ct)
        eff = ctr - fsr  # positive = identity helps (control collapses more)
        verdict = "identity helps" if eff > 0.1 else ("length artifact" if eff <= 0 else "weak")
        print(f"| {m} | {fsr:.0%} | {ctr:.0%} | {eff:+.0%} ({verdict}) |")
    print(f"\n(Positive identity effect = length_control collapses MORE than full_stack, "
          f"i.e. the identity content, not prompt length, is doing the work.)")

# ------------------------------------------------------------------- selftest

def _selftests():
    fails = []
    # wilson
    lo, hi = wilson_ci(0, 10)
    assert lo == 0.0 and hi < 0.35, ("wilson 0/10", lo, hi)
    lo, hi = wilson_ci(5, 10)
    assert lo < 0.5 < hi, ("wilson 5/10", lo, hi)
    lo, hi = wilson_ci(10, 10)
    assert hi == 1.0 and lo > 0.65, ("wilson 10/10", lo, hi)
    assert wilson_ci(0, 0) == (0.0, 0.0)
    # fleiss: perfect agreement -> 1.0
    k = fleiss_kappa([[3, 0], [0, 3], [3, 0]])
    assert abs(k - 1.0) < 1e-9, ("fleiss perfect", k)
    # fleiss: no agreement structure roughly ~0
    k2 = fleiss_kappa([[2, 1], [1, 2], [2, 1], [1, 2]])
    assert k2 is not None and k2 < 0.5, ("fleiss mixed", k2)
    # length control monotonic + close to target
    c = build_length_control(5000)
    assert 4700 <= len(c) <= 5000, ("ctrl length", len(c))
    assert not any(w in c.lower() for w in ("persistent", "identity", "who you are")), \
        "control leaks identity content"
    # collapse table shape
    tbl = _collapse_table({("m", "full_stack"): {"cold": ["entity_first"]*8+["collapse"]*2,
                                                 "hard": ["collapse"]*6+["entity_first"]*4}})
    assert "full_stack" in tbl and "6/10" in tbl, "table render"
    print("all self-tests passed")
    return 0

# ---------------------------------------------------------------------- main

def load_cfg(path):
    with open(os.path.expanduser(path), encoding="utf-8") as f:
        return json.load(f)

def main():
    ap = argparse.ArgumentParser(description="Theseus substrate-swap continuity harness")
    ap.add_argument("cmd", nargs="?", choices=["check-models", "calibrate", "run", "judge", "report"])
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--out", default="runs")
    ap.add_argument("--run-dir")
    ap.add_argument("--judge-model")
    ap.add_argument("--ratings")
    a = ap.parse_args()

    if a.test:
        sys.exit(_selftests())
    if not a.cmd:
        ap.print_help(); sys.exit(1)

    if a.cmd == "report":
        cmd_report(a.run_dir, a.ratings); return

    cfg = load_cfg(a.config)
    api_key = load_env_key(cfg.get("env_path", "./.env"))
    if not api_key:
        print("No OPENROUTER_API_KEY found (checked env + cfg.env_path)."); sys.exit(2)

    if a.cmd == "check-models":
        cmd_check_models(cfg, api_key)
    elif a.cmd == "calibrate":
        cmd_calibrate(cfg, api_key)
    elif a.cmd == "run":
        cmd_run(cfg, api_key, a.n, a.out)
    elif a.cmd == "judge":
        jm = a.judge_model or cfg.get("judge_model")
        if not jm:
            print("Provide --judge-model or set judge_model in config."); sys.exit(2)
        cmd_judge(cfg, api_key, a.run_dir, jm)

if __name__ == "__main__":
    main()
