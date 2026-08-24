# Adversarial Methodological Audit of `moomoo-trader`

## Evidence boundary and verdict

This audit treats the project as a **paper-trading research system**, not as a candidate for real-money deployment. The question is narrower: *does the project’s present experimental methodology justify the strategy decisions it is making?*

There is an important evidence limitation up front. The public GitHub `master` visible on August 24, 2026 is behind the local state described in the supplied audit bundle. Public `master` still describes four strategies, older strategy configurations, and older evaluation material, while the bundle describes five active strategies plus the LLM regime layer and August 24 local fixes. citeturn14view0 The bundle itself records recent local corrections, including the gate-ETA work and tests around the stale configuration problem. fileciteturn3file0L91-L107 fileciteturn1file2L98-L105 Consequently, findings about public code are directly verified; findings about the newer local state are only as strong as the supplied bundle unless the same code is public.

**Overall verdict:** the project has unusually good *research discipline for a solo hobby project*, but several of its strongest claims outrun what its evidence can presently support. In particular, I would not describe the currently deployed strategies as “independently validated” in a statistical sense. The public README does use that language while also describing a sequence of optimized parameters, symbol exclusions, regime choices, and 2024–2025 OOS results. citeturn14view0 Repeatedly using the same historical period for model selection is exactly the kind of reuse Halbert White defined as data snooping: once the results influence subsequent model selection, apparent superiority can arise by chance even if each individual test was originally called out-of-sample. citeturn18search0

The project **can support discovery**: finding strategies that deserve additional paper observation, falsifying bad ideas, detecting execution defects, and comparing candidate rule sets. It can also support operational decisions such as “this implementation is behaving badly enough that I do not want it generating more paper orders.” What it cannot currently do reliably is turn a point estimate such as `PF = 1.2 after 20 trades` into a defensible statement that a durable edge has been established.

The highest-priority methodological problem is not even sample size. It is the regime-validation statistic. Public `validate_regime.py` computes a profit factor independently for each day, discards infinite-PF days, and then averages the remaining daily PF ratios. citeturn2view1 The supplied research record then uses per-regime “avg PF” results in support of the regime-gate decision. fileciteturn5file0L11-L12 That statistic is not aggregate profit factor and can produce radically misleading conclusions.

The second-largest issue is adaptivity. The repo has done exactly what an active research project naturally does: inspect outcomes, discover anomalies, change filters, add overrides, revisit symbols, alter an ORB time cutoff, evaluate KDJ windows, introduce a loose lane, and evaluate an LLM regime filter. That is good research behavior **provided the reused history is thereafter treated as development data**. Adaptive-data-analysis theory is explicit that a holdout ceases to behave like an untouched holdout when future analyses are chosen as a function of earlier holdout results. citeturn18search6turn18search7

The third issue is dependence. SPY, QQQ, IWM, and DIA can generate distinct trades, but “distinct” is not synonymous with “statistically independent.” US equity returns contain common market factors, so independence cannot simply be assumed for broad-market ETF observations. citeturn17search0 Adding DIA may legitimately add information and improve cross-instrument replication, but it should not be described as converting four correlated same-day observations into four independent samples.

Those problems are fixable without turning the project into an academic statistics package. The strongest recommendation from this audit is actually a simplification: **treat historical backtests as discovery, treat everything seen through August 24, 2026 as development data, and make frozen future paper cohorts the confirmation layer.**

## Verified findings

**The fixed trade-count gates are not calibrated sample-size requirements.** There is no statistical basis for saying that `N=10`, `15`, `20`, `30`, or `50` is inherently sufficient for a trading strategy. For win rate, the uncertainty is easy to illustrate. Brown, Cai, and DasGupta show why the usual Wald interval performs poorly, particularly at small sample sizes, and recommend Wilson or Jeffreys-type intervals instead. citeturn19search3turn19search8

At an observed win rate near 50%, the approximate 95% Wilson half-width is about **26 percentage points at N=10, 23 points at N=15, 20 points at N=20, 17 points at N=30, and 13 points even at N=50**. In other words, a nominal 50% result at 20 trades is roughly compatible with a population win probability from about 30% to 70%; even 50 trades leaves a very broad interval of roughly 37% to 63%. These are not criticisms peculiar to this project; this is simply how little information a few dozen Bernoulli outcomes contain. citeturn19search8

That does **not** mean a 20-trade gate is useless. It means it is an *operational minimum*, not evidence that uncertainty has become small. A rule saying “do not even review this lane before 20 trades” is perfectly defensible. A claim saying “20 trades establishes that PF > 1 or win rate > 40%” is not.

This distinction matters for the August 24 correction. Computing trades/week and ETA before writing a gate is a genuinely useful process improvement because it prevents a gate from unknowingly requiring 13–18 months. The supplied bundle now requires that arithmetic before assigning a sample threshold. fileciteturn3file0L91-L107 But **ETA should constrain project expectations, not statistical sufficiency**. If a strategy takes a year to produce enough information, the statistically correct answer may simply be that the result remains unresolved for a year. Lowering N because the original N is inconvenient solves a project-management problem, not an inference problem.

**Profit factor is even less amenable to a universal N.** If trade P&L is \(P_i\),

\[
PF=\frac{\sum_i \max(P_i,0)}
        {\sum_i \max(-P_i,0)}.
\]

Its uncertainty depends not merely on how many trades occurred but on the entire distribution of winner and loser sizes, the probability of each, tail behavior, and dependence between observations. Ratio statistics can have highly asymmetric and unstable uncertainty, especially when the denominator is small; statistical work on ratios explicitly cautions against treating ordinary symmetric approximations as reliable in small or skewed samples. citeturn10search10 Financial series also commonly present dependence and heavy tails, settings in which standard normal approximations—and in sufficiently heavy-tailed cases even ordinary bootstrap procedures—can fail. citeturn10search2

This creates a concrete failure mode for `PF < 1 after N trades`. Imagine 19 trades yield PF 0.85 and trade 20 is one large winner that pushes PF to 1.25. Nothing magical occurred when trade number 20 arrived. Conversely, one unusually large loser can push PF below 1. The gate gives a clean-looking binary outcome to a statistic whose sampling uncertainty may still be enormous.

**The regime validator is presently calculating the wrong aggregate statistic.** The public validator forms per-day trade sets, calls `profit_factor(day_trades)`, stores those daily ratios, removes values represented as infinity, and computes the arithmetic mean of the remaining PF values. citeturn2view1

Consider only two trading days:

\[
G_1=10,\quad L_1=1,\quad PF_1=10
\]

\[
G_2=1,\quad L_2=10,\quad PF_2=0.1.
\]

The current daily average is

\[
(10+0.1)/2=5.05.
\]

But the actual pooled profit factor is

\[
PF_{\text{pooled}}
=\frac{10+1}{1+10}
=1.00.
\]

A classifier can therefore appear extraordinarily beneficial according to “average daily PF” while its underlying trades are exactly breakeven on pooled PF. This is not a subtle asymptotic concern; it is a different statistic.

Excluding days with no losses compounds the problem. A day with gains and zero gross losses has an infinite daily PF precisely because the denominator is zero. Silently removing it does not transform the remaining arithmetic mean into profit factor. The correct aggregate calculation is simply to pool gross wins and gross losses across every trade belonging to the regime and calculate the ratio once.

Accordingly, **the existing historical evidence for the LLM regime flip must be recomputed before it is allowed to support a strategy decision**. This does not imply the decision will reverse. It means the current reported statistic cannot tell us.

**The appropriate uncertainty calculation should preserve trading-day dependence.** Politis and Romano's stationary bootstrap was explicitly designed to construct standard errors and confidence regions under weak dependence rather than assuming independent observations. citeturn19search4turn19search16 Künsch's block-bootstrap work addresses the same general problem for stationary dependent observations. citeturn19search2 For this project, an even simpler first approximation is to resample **trading dates as clusters**, retaining all strategy/symbol trades occurring on each selected date, then recompute pooled gross gains, gross losses, PF, and expectancy for every bootstrap replicate. That keeps an SPY trade and an IWM trade caused by the same market episode together instead of pretending they were unrelated experiments.

With very heavy tails or very few clusters, even the bootstrap should not be treated as magic. Hall and Yao show that heavy-tailed financial processes can defeat standard bootstrap approximations and motivate subsampling-type methods in such settings. citeturn10search2 For `moomoo-trader`, this means bootstrap intervals are a large improvement over raw PF thresholds, not an oracle.

**Repeated peeking matters if the gates are interpreted inferentially.** A conventional 95% interval or p-value evaluated over and over whenever a new trade arrives does not retain its nominal frequentist interpretation under arbitrary optional stopping. Sequential-analysis methods exist specifically to address this problem. Howard, Ramdas, McAuliffe, and Sekhon construct confidence sequences that remain valid uniformly over time under their stated conditions. citeturn16academia15turn16search3

However, I would not rush to bolt an advanced confidence-sequence implementation onto the project. For binary win rate, it is possible. For dependent, fat-tailed trading P&L and PF ratios, the assumptions and implementation get much harder. A smaller project can get most of the practical benefit simply by defining **fixed review dates or fixed cluster-count reviews**, rather than continuously treating every new PF observation as a fresh hypothesis test.

**The project already contains evidence of changing data-generating policies inside what is discussed as one strategy history.** The supplied bundle says the ORB series “recovered from 0.76 … after `ORB_LATEST_ENTRY`,” with the cutoff change becoming part of the current evaluation narrative. fileciteturn3file0L240-L248 But a strategy before and after a signal-affecting entry-time rule is not the same experimental treatment. Combining those observations may be fine for a lifetime paper-trading dashboard; it is not clean evidence for the current ORB policy.

The same principle applies to every change that alters whether a trade exists, its entry, exit, stop, target, symbol eligibility, or regime eligibility. A corrected strategy can inherit historical audit records, but it should not inherit those records as though they were observations generated by the corrected policy.

**The public historical regime architecture has a reproducibility hole around model/versioned caches.** `morning_regime.py` stores the model and `PROMPT_VERSION` in each result and logs the exact prompt and raw response, which is good experimental hygiene. citeturn21view0turn21view3 But `load_regime_today()` names the artifact only by date and accepts the stored regime without checking that its model or prompt version matches the experiment currently being evaluated. citeturn21view4 That means “regime for 2025-03-12” is treated as a single immutable fact even though the label is actually the output of a specific model × prompt × features × data snapshot.

The bundle's Haiku-to-Sonnet change therefore is not merely a software upgrade. Methodologically it creates a new classifier. Historical labels from one model should not silently coexist with labels from another classifier in the same validation cohort.

**The historical regime prompt also has a genuine temporal-validity problem.** The classifier explicitly receives the historical date, prior VIX, prior SPY and QQQ session summaries, and a macro-calendar feature. citeturn22view0turn22view2 It is then asked to classify that day's market regime using a modern language model. The code does not impose an enforceable “knowledge only through this historical morning” boundary on the model itself. Modern research has now tested exactly this issue. The 2026 ExAnte benchmark found that LLMs frequently rely on internalized post-cutoff information even when explicitly instructed to obey historical temporal cutoffs. citeturn9search3 A 2025 study focused specifically on economic and financial forecasting found that models can memorize historical economic variables and financial information, making pre-cutoff historical forecasting impossible to distinguish cleanly from recall. citeturn9academia25

Therefore, retrospective LLM classifications of 2024 or 2025 dates **cannot be considered equivalent to labels that would have been produced ex ante on those mornings** unless it can be established that the model had no access, through training, to post-morning information. The repo does not establish that.

The hardcoded macro feature introduces an additional, more conventional reproducibility problem: the source itself labels its 2026 FOMC and CPI calendar values “approximate.” citeturn22view1 A feature meant to represent information available before a historical market open should be sourced from a known as-of calendar snapshot, not a manually reconstructed approximation. Even if every approximate date happened to be harmless, the methodology needs to know what information was actually available at classification time.

## Reasonable inferences

**The project's 2024+ “OOS” period should now be considered development/adaptive-validation data for new strategy decisions.** This does not mean the original first evaluation against 2024–2025 was fraudulent or meaningless. “Out of sample” is relative to a particular model-selection event. A period can be genuinely OOS for version A and then become development data after version A's results are inspected and used to create versions B, C, and D.

White's definition is directly relevant: reuse of a dataset for inference or model selection creates data-snooping risk because the selected winner can owe its apparent quality to chance. citeturn18search0 Dwork and colleagues make the same broader point about adaptive analysis: once future analyses depend on earlier holdout results, ordinary holdout guarantees no longer apply without special machinery. citeturn18search6

The public README documents enough sequential research decisions to make that concern material: ATR stop selection, signal-score selection, timeframe comparisons, regime-filter comparisons, symbol-specific deployment, KDJ-window selection, and an OOS SPY/QQQ/IWM comparison all coexist in the same research history. citeturn14view0 The supplied bundle adds further adaptive research after those results. Thus, calling future variants “validated on the 2024+ OOS period” would overstate independence. A more accurate label is **historical adaptive validation** or simply **development**.

This also means a sophisticated nested cross-validation scheme cannot magically make the already-examined 2024–2026 history pristine again. It can estimate robustness and reduce overfitting during future historical searches, but knowledge already extracted from the data does not disappear when you rearrange the folds.

**Walk-forward analysis remains useful, but primarily as a robustness diagnostic.** Time-series validation differs from ordinary randomized K-fold CV because serial correlation and nonstationarity make arbitrary shuffling problematic. Bergmeir, Hyndman, and Koo show that ordinary K-fold time-series validation can be justified only in particular autoregressive circumstances, not as a generic license to ignore temporal structure. citeturn19search1turn19search6 For these intraday strategies, chronological expanding-window or rolling-window evaluation is conceptually cleaner.

A valid walk-forward experiment would choose parameters using only the training history available before each test block and then run the frozen strategy on the next block. If the final reported parameter—say `ATR_STOP_MULT=1.0`—was chosen after looking at performance across all walk-forward test blocks, then those blocks have participated in model selection. The reported walk-forward consistency still tells you something useful about historical robustness, but it is no longer a clean final confirmation sample.

“Purging” and “embargoing” are less central here than they are in machine-learning problems with overlapping labels. They become useful where indicator warm-up, trade holding periods, or target construction overlap a fold boundary. The essential rule for this repo is simpler: no information from the future test block may influence parameter choice, no position should straddle the train/test boundary unless the protocol explicitly models that, and all indicators need only legitimate pre-test warm-up data.

**A signal-affecting live configuration change should start a new evaluation cohort.** This follows from the definition of what is being estimated. Suppose configuration A allows ORB entries until 15:45 and configuration B stops at 12:30. The distribution of trades under B is not the distribution that generated A's afternoon observations. “What is the PF of current ORB?” therefore has a different target after the change.

The minimum useful identity is approximately:

`strategy + symbol + policy/config hash + code version`

For the LLM-dependent lanes it should additionally include:

`regime model ID + prompt hash + feature-schema version`.

This does not require deleting old observations. The dashboard can still show lifetime operational P&L. The research view should show, for example, “ORB policy A: retired” and “ORB policy B: current cohort since August 14, 2026.” The old data remain valuable evidence about why A was changed; they simply stop masquerading as samples from B.

The same rule should apply to bug fixes when the bug materially changed generated trades. Keeping buggy trades in the audit trail is correct. Counting them toward evidence for the corrected policy is not. There is no contradiction between “do not rewrite history” and “do not pool incompatible experiments.”

**The project's new gate-ETA discipline should be retained, but its causal direction should be reversed.** The sequence should be:

> Define what amount of uncertainty is tolerable → estimate how much evidence that likely requires → compute trades/week → accept the resulting ETA or admit that the project cannot resolve the hypothesis quickly.

It should not be:

> Decide the project should know the answer within six months → choose N that produces a six-month ETA.

The latter is effectively choosing evidentiary standards around desired project velocity. The new arithmetic rule catches absurd gate durations, but the existence of an inconvenient ETA is itself useful information about a low-frequency strategy.

**The statement that another ETF creates “independent signal-generating instruments” is too strong.** Broad US equities share common market variation; Fama and French's classic factor evidence is enough to reject a blanket independence assumption. citeturn17search0 The relevant correlation for this project is not even ordinary daily return correlation. It is **correlation between the strategy's realized outcomes and signals across instruments**, especially on the same trading date.

Consider an illustrative exchangeable cluster—not an estimate of your actual data. If four same-day ETF trade outcomes had pairwise within-day correlation \(\rho=0.5\), the standard cluster design-effect approximation,

\[
DE \approx 1+(m-1)\rho,
\]

gives \(DE=2.5\) for \(m=4\). Four nominal observations would then carry information comparable to only about

\[
4/2.5 = 1.6
\]

independent observations. At \(\rho=0.25\), the same four observations are roughly 2.3 independent-equivalents. If signals occur on different days and their outcomes are weakly related, the penalty could be much smaller. The actual answer cannot be inferred from ETF names; it needs the timestamps and trade outcomes.

That gives a more precise verdict on DIA:

**Adding DIA can legitimately increase evidence. It does not legitimately multiply evidence one-for-one.**

DIA is useful if it is treated initially as a **new replication instrument**. Freeze the strategy first, select DIA on non-performance criteria such as liquidity/data availability/exposure definition, and preregister what constitutes success before examining the results. Then report DIA separately. If DIA independently shows the same effect, the strategy's cross-instrument credibility increases.

By contrast, suppose the process is “backtest DIA, XLK, MDY and XLF on all five strategies, pick whichever produces the best PF, then add that symbol's trades to the existing gate.” That is another specification search. White's Reality Check and Hansen's Superior Predictive Ability test were developed precisely for comparisons where the “best” model is selected from a family of alternatives. citeturn18search0turn18search4 A financial application of these methods found that apparently profitable technical rules became much less impressive after explicitly accounting for the universe of rules searched. citeturn10search12

For a hobby project, implementing SPA is optional. **Recording all candidates and refusing to call the best backtest a confirmation result is not optional.**

**The symbol-level and strategy-level samples should usually remain separate longer than the current raw-count instinct suggests.** SPY, QQQ, IWM, and DIA differ in composition, volatility, opening behavior, and exposure. The repo has already found symbol heterogeneity—for example, the public README says VWAP pullback was retained on SPY/QQQ while IWM was excluded, and KDJ windows were configured differently by symbol. citeturn14view0 Once such heterogeneity is known, blindly pooling every symbol into one PF estimates an average across a mixture whose weights are determined partly by signal frequency.

That mixture may be a valid portfolio-level estimand, but it answers a different question from “does BB+KDJ work on DIA?” or “is the SPY implementation positive?” The repo should decide which question each gate is intended to answer before counting trades.

**The public phrase “independently validated production strategies” should be softened.** Based on the adaptive reuse problem, small live cohorts, configuration changes, and multiple historical searches, a more defensible description would be something like **“historically validated candidates under ongoing forward paper evaluation.”** That is not a cosmetic downgrade. It correctly distinguishes historical robustness from genuine future confirmation. citeturn14view0turn18search0

## Speculation and unresolved risks

**The magnitude of cross-symbol dependence is unknown.** I cannot calculate an honest effective sample size from the aggregate scoreboard in the bundle. It requires at least trade timestamp/date, strategy, symbol, outcome or normalized P&L, and preferably the candidate signals that did not become trades. It is entirely possible that BB+KDJ signals on SPY, QQQ, IWM, and DIA are asynchronous enough that a fourth ETF adds substantial information. It is also possible that most entries cluster around the same broad selloffs/rebounds, in which case raw trade count materially exaggerates effective evidence. The current evidence does not decide between those cases.

**It is unknown whether correcting the regime PF calculation will reverse the regime-gate conclusion.** The arithmetic defect is verified; the direction of its effect is not. Averaging ratios can inflate or deflate comparisons depending on the distribution of daily gross losses, and dropping infinite-PF days adds another source of distortion. The correct response is not to presume the LLM filter is bad. It is to rerun the exact historical trade set using pooled gross gains/losses and date-clustered uncertainty before drawing any further conclusion.

**It is unknown how much hindsight knowledge actually affected historical Claude labels.** The design permits temporal contamination, and modern LLM research establishes that such contamination can occur even under explicit cutoff instructions. citeturn9search3turn9academia25 That does not prove a specific 2024 `trending_up` label was generated from memorized future information. There is generally no reliable way to inspect a model response afterward and prove that it did not rely on internalized knowledge. The uncertainty itself is why those historical labels should be categorized as exploratory rather than confirmatory.

**The true multiplicity penalty is also unknown.** White or Hansen corrections require a defined family of alternatives. If every strategy variation, prompt idea, VIX band, symbol override, target, time cutoff, window size, and abandoned hypothesis is faithfully recorded, a formal correction could approximate the search universe. If some experiments happened interactively and never entered the graveyard, the effective universe is larger. This is another reason that future-forward confirmation is simpler and more trustworthy than trying to calculate the perfect historical multiplicity correction after the fact.

**Profit factor may not be the best primary statistic for every strategy.** PF has intuitive appeal and is scale invariant, but it obscures how uncertain the numerator and denominator are and becomes unstable with few losses. A normalized expectancy measure—such as P&L in risk units or basis points per trade—can be statistically easier to summarize alongside PF. This is not an argument to remove PF; it is an argument against allowing one unstable ratio to be the entire evidentiary gate.

**There may be important regime nonstationarity that no amount of additional historical trades solves.** A strategy's 2022–2026 trade distribution need not be the distribution it sees in 2027. Time-series nonstationarity is exactly why ordinary randomized validation is not automatically valid for forecasting problems. citeturn19search6 More history shrinks sampling error under a stable process, but it does not eliminate structural change. A practical system therefore benefits more from transparent chronological cohorts than from one ever-growing lifetime PF.

## Replacement evaluation design

The project does not need a huge statistical framework. A comparatively small change in research semantics would materially improve the quality of almost every future decision.

**Declare the historical boundary once.** Treat all market data and strategy results inspected through **August 24, 2026** as development data. Nothing is “thrown away.” It remains available for parameter discovery, debugging, mechanism investigation, walk-forward robustness checks, and historical stress testing. What changes is the claim attached to it.

A clean future-forward paper confirmation period could begin on a fixed date such as **September 1, 2026**. Every current strategy configuration would be frozen before that date. The future period should not be searched for new filters while simultaneously being called confirmation data. Once a result from that period inspires a change, that data has done its job and becomes part of development history for the new version. Version B then starts a fresh forward cohort.

This “rolling burn” of confirmation data sounds expensive, but it is what makes the evidence honest. The project cannot repeatedly learn from a period and still pretend never to have seen it. citeturn18search6

**Use chronological historical validation for robustness, not absolution.** Within the development history, use expanding-window walk-forward testing. For example, a parameter candidate is chosen from earlier history, frozen, evaluated on the next chronological block, then the window advances. If you subsequently select the candidate with the most attractive collection of test blocks, acknowledge that those blocks contributed to model selection. Time-series validation is useful precisely because it preserves temporal ordering; it does not create untouched data after adaptation. citeturn19search1

For large parameter sweeps, two reasonable paths exist. The statistically ambitious path is White Reality Check or Hansen SPA over the recorded family of variants. citeturn18search0turn18search4 The much simpler path is better suited here: call every sweep **discovery**, pick one candidate, freeze it, and let new future paper data carry the confirmation burden.

**Version the experimental unit.** Every open/close record should include a deterministic hash or human-readable version derived from all policy-defining settings. The minimum is strategy name, symbol, code commit, and signal-affecting configuration. For LLM-gated strategies, add model ID, prompt hash, and feature-schema version.

Then a report can truthfully say:

`ORB / SPY / policy 8c91... / 2026-09-01 onward`

instead of treating “ORB” as a Platonic object that remained unchanged through every modification.

The old and new versions can still be displayed beside one another. That is actually more informative: a rule change that genuinely helped should eventually produce a visible difference between cohorts rather than retroactively improving a blended lifetime statistic.

**Replace hard N decisions with minimum-N plus uncertainty states.** Keep an operational minimum so that the system does not react to three trades. But when that minimum is reached, do not automatically pronounce pass or fail from the point estimate.

A practical three-state rule is:

**Supported:** the uncertainty interval lies on the favorable side of the preregistered decision boundary.

**Contradicted:** the interval lies on the unfavorable side.

**Unresolved:** the interval still crosses the boundary.

For profit factor, the neutral boundary is PF 1.0, although a strategy may rationally require an ex-ante margin above 1 to account for modeling error and simulated execution. For win rate, the correct neutral threshold depends on payoff asymmetry, so `40%` should not be interpreted independently of average winner/loss sizes.

For PF and expectancy, generate the interval by resampling trading dates—or blocks of consecutive dates if serial dependence is apparent—and recomputing the entire pooled metric. Stationary/block bootstrap methods exist for exactly this dependent-observation problem. citeturn19search4 For win rate, a Wilson or Jeffreys interval is a useful descriptive baseline, but a date-cluster procedure is preferable when several correlated symbol trades occur on the same day. citeturn19search8

This changes the meaning of the current `N=15` BB+KDJ gate. At trade 15, the system becomes **eligible for evaluation**. It does not become magically capable of knowing whether the strategy is positive.

**Separate operational suspension from statistical falsification.** There is nothing wrong with saying, “At 20 paper trades PF is 0.35, so I am suspending this lane because continuing it is not useful.” That is an asymmetric research-management decision. Just label it that way.

A stronger statement—“the strategy has been statistically shown to lack edge”—requires uncertainty analysis. This distinction lets you remain conservative without pretending a tiny sample proves more than it does.

**Cluster symbols by date before talking about effective N.** The easiest implementation is not a complicated covariance model. Build one research table with:

`date | strategy | symbol | version | pnl | normalized_pnl | win`

Then measure how often symbols fire together and their pairwise outcome association when they do. Bootstrap dates, not individual rows. Report both raw N and number of unique trade dates. That immediately prevents four simultaneous ETF reactions to one market shock from looking like four completely independent experiments.

If a strategy genuinely fires on DIA on days when the existing ETFs do nothing, DIA will naturally earn more incremental information under this method. The methodology therefore does not punish diversification; it simply measures it honestly.

**Treat DIA first as replication rather than gate fuel.** Choose DIA before looking at strategy results if its role is confirmation. Freeze all five strategies and their parameters. Record the intended analyses. Backtest it historically for diagnostic purposes if useful, but recognize that this makes DIA's historical period development evidence. Then let future DIA paper trades form a separate symbol cohort.

Only after observing whether outcomes are sufficiently similar across instruments should you consider a pooled “common strategy effect.” A hierarchical model could eventually formalize symbol heterogeneity, but that would be unnecessary complexity today. Separate symbol estimates plus a clustered combined summary are enough.

This explicitly rejects the strongest version of the earlier “more symbols = faster gates” claim. **More symbols can shorten calendar time to more observations; they cannot guarantee proportional shortening of the time to more independent evidence.**

**Demote retrospective LLM-regime results to exploratory evidence.** The clean LLM experiment is extremely straightforward: classify the market before the open, save the result, never change it after observing the session, and then accumulate strategy outcomes under those contemporaneously generated labels.

The existing logger already captures much of what is needed: model, prompt version, exact prompts, raw response, and timestamp. citeturn21view0turn21view3 Strengthen this by making the experiment identity part of the cache key and loader validation. A historical artifact should conceptually be something like:

`date + exact_model + prompt_hash + feature_schema_hash + input_data_hash`.

A loader should reject an artifact when those do not match the requested experiment, rather than saying “a regime file exists for this date, therefore we are done.” Public `load_regime_today()` currently checks only the date file and valid label. citeturn21view4

The Haiku and Sonnet regimes should therefore be different cohorts. A prompt revision is another cohort. A material feature change is another cohort.

Historical LLM experiments can still be useful for hypothesis generation. Removing the exact date from the prompt and supplying only as-of numerical features would reduce one obvious leakage channel, but it would not transform the result into proof of ex-ante validity because models can possess memorized contextual information and temporal contamination is difficult to rule out. citeturn9search3turn9academia25 The strongest evidence should remain labels actually produced before future sessions.

**Fix the macro-calendar feature or remove it.** If it remains, generate it from an authoritative calendar snapshot and log the exact event data supplied to the classifier. A manually reconstructed “approximate” date table defeats the point of attempting as-of historical reconstruction. citeturn22view1

**Use a single correct regime statistic.** For each regime label, aggregate all relevant trade gross gains and gross losses:

\[
PF_r=
\frac{\sum_{i:R_i=r}\max(P_i,0)}
{\sum_{i:R_i=r}\max(-P_i,0)}.
\]

Also calculate normalized expectancy and number of unique trading dates. Then resample dates and recompute those quantities. Do not average per-day PFs. If some bootstrap replicates have zero losses and hence infinite PF, preserve that fact rather than silently discarding them; it is telling you that the ratio is poorly determined in that replicate.

## Smallest practical changes

**Fix `validate_regime.py` before interpreting the regime gate again.** Replace average daily PF with pooled gross-profit/gross-loss PF. Rerun every regime result used to justify `trending_up`/`trending_down` suppression. Add a two-day regression test using the `PF 10` plus `PF 0.1` example above; the expected pooled result must be `1.0`, not `5.05`. This is the highest-value methodological fix because the current statistic itself is wrong. citeturn2view1

**Declare a clean evidence boundary.** Label everything through August 24, 2026 as development/adaptive historical evidence. Freeze the current candidates and begin a clearly named future-forward paper cohort on a fixed upcoming date. Stop describing reused 2024+ data as a fresh OOS confirmation period for newly derived variants. This single language and workflow change addresses a large fraction of the project's data-snooping problem. citeturn18search0turn18search6

**Add `strategy_version` or `policy_hash` to trade events.** Do not reset or delete historical P&L. Merely stop pooling pre-change observations when evaluating the current strategy version. The ORB cutoff change is already a concrete example of why this matters. fileciteturn3file0L240-L248

**Keep the current N values only as “minimum before review.”** Do not call 15, 20, 30, or 50 statistically sufficient. At each review, report raw N, unique trade dates, PF, normalized expectancy, win rate, and an uncertainty interval. The current ETA rule remains useful for telling you when a review is likely; it should not determine how much evidence constitutes a conclusion. fileciteturn3file0L91-L107

**Bootstrap by trading date.** It is a small implementation change with a large methodological payoff. All SPY/QQQ/IWM/DIA observations from a selected date move together in the resample. This automatically reduces false precision caused by same-market-event clustering and is consistent with the statistical motivation for block/stationary bootstrap methods under dependent observations. citeturn19search4turn19search2

**Do not use DIA as one-for-one gate acceleration.** Add it as a preregistered replication symbol. Report DIA separately first. Let it contribute to a pooled summary only through a date-clustered analysis whose pooling rule was specified before seeing DIA's result. The scientifically defensible claim is “DIA gives us another opportunity to test whether the same frozen rule generalizes,” not “DIA gives us independent trades four times as fast.” Common market factors make the latter assumption unjustified without empirical outcome-level evidence. citeturn17search0

**Make LLM regime artifacts versioned experiments and validate primarily forward.** The existing logging is already close to what is required. Add strict model/prompt/input identity to cache validation, stop mixing old-model historical labels with new-model labels, treat retrospective date-aware classifications as exploratory, and accumulate the real evidence from labels emitted before future sessions. Temporal-contamination research makes that a materially stronger test than rerunning a 2024 date through a 2026 language model. citeturn9search3turn9academia25

With those changes, the project would not become slower in the sense that matters. It would become **less binary about weak evidence**. Some gates would resolve early because their intervals move decisively away from the null; others might remain “unresolved” well beyond 20 or 30 trades. That is not a defect in the research harness. It is the accurate result.

The larger conclusion is therefore somewhat adversarial to both extremes. The project is **not** methodologically hopeless or merely curve-fit noise: it has explicit freeze rules, a graveyard, forward paper execution, recorded failures, and a willingness to correct its own assumptions. But the opposite claim—that preregistration plus fixed trade counts has already converted these strategies into independently validated edges—is also unsupported. The strongest next step is not more elaborate strategy logic, smaller gates, or a fourth ETF by itself. It is to make **experimental identity, temporal independence, clustered uncertainty, and future-forward evidence** first-class concepts. Once those exist, more symbols genuinely become useful because the project can distinguish *more trades* from *more evidence*.