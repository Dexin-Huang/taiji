# Parameter Golf Attack Note

This is a separate attack vector, not the core taiji product.

`parameter-golf` already defines a sharp public benchmark:

- minimize final `val_bpb`
- keep total artifact bytes under `16,000,000`
- train in under `10` minutes on `8xH100`
- evaluate in under `10` minutes on `8xH100`
- remain reproducible

That means this is primarily a `fixed` world problem, not an `adaptive` one. Yin does not need to keep inventing a harder world. The main difficulty is expensive, noisy evaluation under a fixed official objective.

## Search Equation

Let `x` be a candidate end-to-end procedure:

- tokenizer
- model architecture
- training rule
- export / compression
- evaluation method

The true objective is:

```text
minimize S(x) = official_val_bpb(x)

subject to
  bytes_total(x) <= 16,000,000
  train_time(x) <= 600s on 8xH100
  eval_time(x) <= 600s on 8xH100
  reproducible(x) = true
```

Because official evaluation is expensive, the real search problem is:

```text
maximize expected official improvement per unit compute
```

or more explicitly:

```text
Choose next (x, f) to maximize

Pr(feasible_official(x) | D_t) * ExpectedImprovement_official(x | D_t, f)
------------------------------------------------------------------------
                             Cost(f)
```

Where:

- `D_t` is everything learned so far
- `f` is the evaluation fidelity tier

## Multi-Fidelity Ladder

Do not spend most search budget on the official `10` minute run.

Use a staged ladder:

1. `Tier 0`: static checks
   - code compiles
   - artifact is self-contained
   - byte accounting is sane
2. `Tier 1`: tiny proxy
   - very short wallclock
   - small data slice
   - same export path
3. `Tier 2`: medium proxy
   - longer run
   - more realistic training regime
4. `Tier 3`: near-official proxy
   - closest affordable approximation
5. `Tier 4`: official run
   - only for top candidates
   - repeated enough to estimate variance

Cheap proxy runs are hints. Official runs are truth.

## DAG View

Represent a candidate as a pipeline DAG:

```text
data/tokenizer -> model spec -> train loop -> export/compress -> eval
```

Each node has:

- an artifact
- local parameters
- local proxy metrics
- local compute cost

But only the end-to-end pipeline matters for the real objective.

This means:

- local node optimization is useful
- node-local wins are not enough
- full pipeline checks must periodically re-anchor the search

Good local axes:

- tokenizer efficiency / correctness
- architecture under byte pressure
- short-run training slope and stability
- post-quantization degradation
- eval-time compute tradeoffs

## Agent Loop

If we attack this autonomously, the right shape is:

- `builder`
  - edits only the candidate script or candidate folder
  - proposes one concrete hypothesis at a time
- `critic`
  - read-only
  - inspects logs, deltas, and failures
  - suggests the next move
- `librarian`
  - read-only retrieval over past runs and artifacts
  - queryable, not prompt-stuffed
- `scheduler`
  - mechanical
  - decides tier promotion, repeats, and resource allocation

## Selection Rule

Use hard keep/discard.

Among candidates, compare mechanically with a public score tuple:

1. lower `val_bpb`
2. then lower `bytes_total`
3. then lower train time
4. then lower eval time
5. then lower code bytes

If a candidate does not beat the incumbent at the current tier, discard it.

## Byte-Scale Curriculum

If we want a smaller internal track, do not jump straight to `16KB`.

That is too likely to become code-golf instead of model-craft. A better internal byte ladder is:

- `256KB`
- `1MB`
- `4MB`
- `16MB`

The goal is to learn transfer:

- which architectural motifs survive compression
- which parameter allocations are worth bytes
- which export paths preserve performance

Exact hyperparameters will not transfer cleanly, but structural lessons might.

## Fit With Taiji

This is a good fit for a separate taiji application in `fixed` mode:

- frozen benchmark
- one editable candidate surface
- mechanical score
- harsh keep/discard
- retrieval-based memory

It is not a good fit for taiji's core adaptive yin/yang loop, because the official challenge already defines the world and the law.
