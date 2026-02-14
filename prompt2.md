Nagyon jó kérdés.
Most **strukturáltan** adom meg, hogy:

* mely **US és UK ingyenes hírforrások** jók,
* melyeknek van **RSS**,
* melyekhez van **API**,
* és melyek alkalmasak arany / makró / geopolitika figyelésre.

Nem “random listát” adok, hanem **architektúra szempontból használható stack-et**.

---

# 🇺🇸 USA – Ingyenes, Stabil Források

## 1️⃣ Reuters (US edition)

**Miért fontos?**

* Gyors
* Strukturált
* Kevés szenzáció
* Arany és makró témában elsődleges

**Elérés:**

* RSS: ✅
* API: ❌ hivatalos fizetős, de RSS jól használható
* Scrape: ⚠️ óvatosan

👉 Aranyhoz: commodity + macro feed

---

## 2️⃣ Federal Reserve (Fed)

**Miért kritikus?**

* Kamatdöntések
* Beszédek
* Minutes

**Elérés:**

* RSS: ✅
* API: ❌
* Strukturált HTML: ✅

👉 Ez top priority source (99-es hitelesség)

---

## 3️⃣ U.S. Bureau of Labor Statistics (BLS)

* Infláció (CPI)
* Munkanélküliség
* Foglalkoztatottság

**Elérés:**

* API: ✅ (ingyenes, kulcs kell)
* JSON response
* Dokumentált

👉 Kontextus-modulhoz kiváló

---

## 4️⃣ FRED (St. Louis Fed)

* Makró idősorok
* Infláció
* GDP
* Rates

**Elérés:**

* API: ✅ (ingyenes)
* JSON
* Nagyon stabil

👉 Kontextusérzékenységhez kötelező

---

## 5️⃣ Yahoo Finance

* Árfolyam adatok
* Történelmi ár

**Elérés:**

* Nem hivatalos API
* Python library: yfinance

👉 Feedback loophoz jó

---

## 6️⃣ CNBC (US)

* RSS: ✅
* API: ❌
* Gyors, de nem elsődleges

---

# 🇬🇧 UK – Ingyenes Források

## 1️⃣ Bank of England (BoE)

* Kamatdöntések
* Monetary Policy Report

RSS: ✅
API: ❌

---

## 2️⃣ Office for National Statistics (ONS)

* UK infláció
* GDP
* Munkaerőpiac

API: ✅ (JSON)

---

## 3️⃣ Financial Times (FT)

* RSS: részben
* API: ❌ (fizetős)
* Scrape: ⚠️

Nem elsődleges MVP-ben.

---

## 4️⃣ BBC Business

RSS: ✅
Megbízható, de másodlagos.

---

# 🟡 Arany-specifikus szakmai források

## 1️⃣ Kitco

RSS: ✅
Gold news specifikus.

## 2️⃣ World Gold Council

RSS: ✅
Elemzések, nem breaking.

## 3️⃣ Mining.com

RSS: ✅
Kínálati oldal.

---

# 🌍 Geopolitikai Források

* Reuters World RSS
* AP News RSS
* BBC World RSS

API: általában nincs, RSS van.

---

# 🧠 Ajánlott API-k (amit tényleg érdemes használni)

Ha stabil rendszert akartok:

## 🟢 Ingyenes API-k

* FRED API
* BLS API
* ONS API
* Yahoo Finance (áradat)
* Alpha Vantage (limitált, de jó)

---

## 🟡 Olcsó, de profi opció (később)

* NewsAPI.org
* GNews API
* Polygon.io (áradat)
* TwelveData

---

# 🎯 MVP Ajánlott Forrás Stack (Gold MVP)

Kezdéshez csak ezek:

**Hírek:**

* Reuters Gold RSS
* Fed RSS
* Kitco RSS

**Makró adat:**

* FRED API
* BLS API

**Ár adat:**

* Yahoo Finance (GC=F vagy XAUUSD)

Ennyi bőven elég MVP-hez.

---

# ⚙️ Architektúra Szempontból

Javasolt forráskategóriák:

1. CORE (5-15 perc polling)

   * Reuters
   * Fed
   * BoE
   * ECB

2. DATA API (strukturált makró)

   * FRED
   * BLS
   * ONS

3. CONTEXT / CONFIRMATION

   * Kitco
   * CNBC
   * BBC

4. EARLY SIGNAL (később)

   * Twitter/X
   * Telegram

---

# ⚠️ Fontos

Ne akarjatok 20 forrást első hónapban.
3–5 forrás bőven elég.

A rendszer minőségét nem a források száma adja,
hanem:

* deduplikáció
* kontextus értelmezés
* hitelesség súlyozás
* feedback loop

---

Ha szeretnéd, csinálok:

* egy konkrét gold_sources.yaml mintát
* vagy egy prioritás + polling idő stratégiai tervet
* vagy egy “melyik API mire való pontosan” térképet

Mondd melyiket.
