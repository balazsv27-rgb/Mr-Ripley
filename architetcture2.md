Below is a concrete architecture sketch for the **three vertical layers**, centered around **Events** as the shared contract and the **Macro Driver Engine** as the spine.

---

## Layer 1 — Curated RSS + Event Extractor

**Purpose:** convert *current narrative signals* into **interpretable structured events**.

### Inputs

* Curated RSS feeds (central banks, macro portals, selected financial outlets)
* Optional: institutional pages with clean RSS (ECB/BoE/Fed)

### Core components

* **Feed Registry**

  * list of RSS sources + reliability weighting + topic tags (rates/inflation/geopolitics/flows)
* **RSS Adapter**

  * fetch → parse → normalize (`title`, `published_at`, `url`, `source`)
* **Content Enricher**

  * fetch article text where permitted, extract snippet (or use RSS description)
* **Event Extractor**

  * rule-based + lightweight classifier
  * outputs **EventCandidate** objects
* **Event Normalizer**

  * maps candidate → canonical ontology (`event_type`, `actor`, `direction`, `magnitude`, `confidence`)
* **Event Emitter**

  * pushes events to the event bus + stores evidence pointers

### Outputs (contract)

* `EventCandidate` / `Event`

  * `event_id`, `event_type`, `actor`, `direction`, `time_anchor`, `confidence`
  * `evidence_refs[]` (URLs/snippets)
  * `tags[]`

---

## Layer 2 — Market & Macro Data APIs (Truth Layer)

**Purpose:** maintain the authoritative numerical history + latest state for gold and macro drivers.

### Inputs

* **Macro APIs:** FRED series (yields, CPI, FEDFUNDS, real yields, USD proxies)
* **Market APIs:** gold proxy prices (GLD/GC=F), optional metals API (OHLCV, volume where possible)

### Core components

* **Ingestion Scheduler**

  * backfill jobs + daily incremental updates
* **API Connectors**

  * FRED client, market data client(s)
* **Time-Series Store**

  * raw observations (normalized, versioned)
* **Feature Builder**

  * returns, vol, drawdowns, z-scores, correlations, spreads
* **Regime Engine (Macro Driver Engine)**

  * derives **MacroState** and regime labels:

    * inflation regime, real yield regime, USD regime, risk regime
* **MarketState Engine**

  * gold-centric market regime labels (trend/vol/flow proxies)

### Outputs (contract)

* `MacroState(t)` snapshot + regime ids
* `MarketState(t)` snapshot + regime ids
* Feature vector `x_t` (“market+macro embedding”) used by Layer 3

---

## Layer 3 — Knowledge Base + Historical Pattern Engine (Memory Layer)

**Purpose:** map the current event + state to **historical analogs** and return **probabilistic outcomes** with uncertainty measures—without scraping a decade of news.

### Inputs

* Events from Layer 1 (current narrative)
* States/features from Layer 2 (current and historical)

### Core components

* **Event Store**

  * canonical events (from RSS + synthetic macro events derived from data, e.g. rate step changes)
* **State Vector Store**

  * historical `x_t` vectors (standardized features)
* **Reaction Store**

  * precomputed reaction windows for gold returns:

    * `ret_1d, ret_3d, ret_5d, ret_10d`, drawdown, vol response
* **Analog Engine (Similarity Search)**

  * kNN retrieval over `x_t` (numeric similarity)
  * optional conditioning by event_type/actor/direction
* **Pattern Engine**

  * aggregates analog outcomes into distributions
  * learns conditional statistics by regime/event
* **Uncertainty Engine**

  * confidence from:

    * analog count, distance dispersion, regime agreement
* **Scenario Engine**

  * merges:

    * Layer 1 event hypothesis
    * Layer 2 macro/market state
    * Layer 3 analog distributions
  * produces scenarios + probability bands + “why” explanations
* **Evidence / Explanation Layer (optional)**

  * small curated institutional documents per regime (not mass news archive)

### Outputs (contract)

* `ScenarioResult`

  * `P(up)`, expected return, percentile bands, tail risk
  * top analog cases (timestamps + event labels + distances)
  * uncertainty metrics + explanation trace

---

## Cross-layer plumbing (recommended)

### Event Bus (logical, can be simple)

* Topic: `events.new`, `states.updated`, `scenarios.requested`
* Keeps layers decoupled.

### Shared Ontology + Schemas

* `Event`, `MacroState`, `MarketState`, `FeatureVector`, `ScenarioResult`
* This is what makes the architecture scalable.

---

## End-to-end flow (runtime)

1. Layer 1 emits `EventCandidate` (“Fed speech: dovish tilt”, confidence 0.72).
2. Layer 2 updates `MacroState(t)` + `MarketState(t)` and computes `x_t`.
3. Layer 3 retrieves top-k analog states similar to `x_t`, optionally filtered by `event_type`.
4. Scenario Engine returns probabilistic outcomes + uncertainty + analog explanations.

---

## End-to-end flow (offline backfill)

1. Layer 2 backfills macro + gold series and computes historical features.
2. Layer 3 generates synthetic “macro events” from series changes and stores reaction windows.
3. Analog Engine becomes immediately usable even before Layer 1 is rich.

---

If you want, I can also sketch this as a simple component diagram (boxes + arrows) and propose the exact storage layout (Postgres tables) for each layer.
