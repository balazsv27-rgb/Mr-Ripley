> **HISTORICAL / NON-CANONICAL**
> This file is not part of the canonical 7-document authority set.
> Canonical truth is defined by the canonical documentation set and `CLAUDE.md`.

## Mr. Ripley — Governance és Claude Orchestration Implementációs Terv

---

## 1. Current State Assessment

### Jelenlegi helyzet összefoglalása

A projekt jelenlegi állapota alapján a *dokumentációs és governance alapok nagyrészt már stabilizálódtak*, miközben a tényleges operatív orchestration-réteg még csak részben került bekötésre.

A legfontosabb eredmények:

* A *Layer-2 truth boundary* működőképes.
* A *snapshot-alapú handoff contract* rendelkezésre áll, így a Layer-3 bootstrap technikailag már erre építhető.
* Elkészült az **egyetlen végleges CLAUDE.md**, amely a rendszer constitutional authority forrása.
* Összehangolásra került a *7 dokumentumos canonical current-state set*.
* A **system-orchestration.yaml** már ehhez a constitutional modellhez illeszkedik.
* A három fő governance skill össze lett hangolva:

  * doc-truth-classification
  * build-sequence-compliance-check
  * snapshot-contract-check

### Fő kihívások

A jelenlegi állapot nem tartalmi káosz, hanem inkább *operatív éretlenség*.

A fő problémák:

* a role-scoped authority modell már megvan, de *a valódi minimal-context routing még nincs operatívan bevezetve*
* a change-impact logika még részben *fejben tartott tudás*, nem strukturált dependency-rendszer
* a hookok blueprintje megvan, de *a legfontosabb guardok még nincsenek teljesen implementálva*
* maradtak kisebb *terminológiai eltérések*, amelyek később routing- és guard-zajt okozhatnak
* az MCP-réteg használata jelenleg még inkább lehetőség, mint kontrollált eszközpolitika

### Jelenlegi korlátok

* Layer-3 továbbra sem implementált.
* Live execution továbbra is tiltott.
* A governance graph még nem teljesen operatív, inkább részben deklaratív.
* A subagentek és skillek szétválasztása már látszik, de a hozzájuk tartozó context- és tool-policy még nem teljes.

### Rövid vezetői megállapítás

A projekt jelenlegi helyzete kedvező abból a szempontból, hogy az *alkotmányos és dokumentációs alap már nem a fő kockázat*. A következő kritikus munkaszakasz az, hogy a meglévő governance modellt *futó, védett, kis kontextusú orchestration-rendszerré* alakítsátok.

---

## 2. Required Changes & Target State

## Célállapot

A kívánt végállapot egy olyan *operatív governance graph*, amelyben:

* minden subagent és skill *szerepkörösen korlátozott*
* minden komponens csak a *minimálisan szükséges kontextust* kapja meg
* a változásokhoz *impact-routing* tartozik
* a fő constitutional szabályokat *hookok valós időben védik*
* az MCP-réteg *kontrollált, role-scoped és tokenkímélő*
* a canonical docs maradnak az elsődleges truth authority források
* a Claude-réteg nem “még egy okos asszisztens”, hanem *projektinfrastruktúra*

---

### Prioritási bontás

## Critical

### 1. Egyetlen constitutional authority fenntartása

* A végleges CLAUDE.md maradjon az egyetlen aktív constitutional forrás.
* Minden constitution-változás kötelező review-t váltson ki a workflow és governance skill-ek oldalán.

*Desired end state:*
Nincs több párhuzamos authority-modell vagy konkurens constitutional változat.

### 2. Hookok P1 implementálása

Elsőként implementálandó guardok:

* snapshot-boundary-guard
* role-matched-doc-guard
* live-readiness-claim-blocker

*Desired end state:*
A legsúlyosabb constitutional és routing hibák automatikusan blokkolódnak.

### 3. Terminológiai egységesítés

Fagyasztandó kulcskifejezések:

* Mr. Ripley
* default_no_trade_path
* canonical current-state set
* authoritative by role, not interchangeable by convenience
* published snapshots only

*Desired end state:*
Nincs terminológiai drift a docs, skills, hooks és workflow között.

---

## High

### 4. Minimal-context routing bevezetése

Skill- és subagent-szintű context policy:

* required
* optional
* forbidden_by_default

*Desired end state:*
Minden komponens csak a feladatához szükséges dokumentumokat, állapotot és kódrészeket látja.

### 5. Change-impact map kialakítása

Deklaratív dependency-rendszer a kritikus fájlokra, dokumentumokra, skillekre és hookokra.

*Desired end state:*
Egy módosítás után azonnal látható, hogy mit kell újraauditálni.

### 6. Hookok P2 implementálása

* doc-code-sync-guard
* pre-pr-governance-gate

*Desired end state:*
PR- és commit-szinten is érvényesül a governance védelem.

---

## Medium

### 7. MCP Policy v1 kialakítása

Első körös, kontrollált MCP-k:

* GitHub
* Context7
* read-only internal access

*Desired end state:*
Claude csak célzott, kontrollált eszközökhöz fér hozzá.

### 8. Tool access segmentation

Subagentenként tool allowlist / denylist bevezetése.

*Desired end state:*
Az audit- és classification-szerepek nem kapnak fölösleges vagy kockázatos eszközhozzáférést.

### 9. End-to-end governance audit

A teljes lánc auditálása:

* docs
* constitution
* workflow
* skills
* hooks
* MCP
* tool access

*Desired end state:*
A governance graph nem csak elméletben, hanem működésben is konzisztens.

---

## 3. Strategic Roadmap

## Fázisstruktúra

| Fázis                         | Fókusz                                 | Fő deliverable                           | Függőségek           |
| ----------------------------- | -------------------------------------- | ---------------------------------------- | -------------------- |
| Phase 1 — Foundation          | Constitutional és terminology lezárás  | Stabil authority + egységes szóhasználat | Végleges CLAUDE.md |
| Phase 2 — Governance Buildout | Context routing, impact map, P1 hookok | Operatív governance alap                 | Phase 1              |
| Phase 3 — Enforcement & Sync  | P2 hookok, doc-code sync, PR gate      | Folyamatos governance védelem            | Phase 2              |
| Phase 4 — Controlled Tooling  | MCP policy és minimális rollout        | Kontrollált eszközréteg                  | Phase 3              |
| Phase 5 — Validation          | End-to-end governance audit            | Auditált, operatív governance graph      | Phase 4              |

---

### Phase 1 — Foundation

*Cél:* Az alkotmányos és terminológiai alap lezárása.

*Fő mérföldkövek:*

* M1 — Constitutional Freeze
* M2 — Terminology Lock

*Deliverable:*

* egyetlen végleges CLAUDE.md
* egységes terminology map
* alignment pass docs / workflow / skills között

---

### Phase 2 — Governance Buildout

*Cél:* A deklaratív governance modellt működő orchestration-réteggé tenni.

*Fő mérföldkövek:*

* M3 — Context Policy v1
* M4 — Change-Impact Map v1
* M5 — Governance Hooks P1

*Deliverable:*

* skill- és subagent-szintű context policy
* első change-impact térkép
* működő P1 guardok

---

### Phase 3 — Enforcement & Sync

*Cél:* A governance működést a fejlesztési workflow-ba bekötni.

*Fő mérföldkövek:*

* M6 — Governance Hooks P2

*Deliverable:*

* doc-code-sync guard
* pre-PR governance gate
* erősebb folyamatszintű védelem

---

### Phase 4 — Controlled Tooling

*Cél:* Kontrollált, minimális MCP-réteg bevezetése.

*Fő mérföldkövek:*

* M7 — MCP Policy v1
* M8 — Minimal MCP Rollout
* M9 — Tool Access Segmentation

*Deliverable:*

* .mcp.json policy
* csak jóváhagyott MCP-k
* subagent tool segmentation

---

### Phase 5 — Validation

*Cél:* Az egész governance graph végponti validálása.

*Fő mérföldkövek:*

* M10 — End-to-end Governance Audit

*Deliverable:*

* audit report
* maradék eltérések listája
* corrective action backlog

---

## 4. Implementation Plan

## 4.1 Végrehajtási megközelítés

A megvalósítást *kis, jól auditálható, egymásra épülő lépésekben* érdemes végrehajtani. Nem egyetlen nagy átépítésre van szükség, hanem fokozatos szigorításra.

A végrehajtás fő elvei:

* constitutional first
* minimal-context by design
* fail-closed enforcement
* explicit dependency mapping
* controlled tooling, not tool sprawl

---

## 4.2 Fő akciók

### Akciócsoport A — Constitutional stabilizálás

*Teendők:*

* végleges CLAUDE.md rögzítése
* constitution update rule hozzáadása
* terminology map létrehozása
* végső szóhasználati pass a fő docs / YAML / skills között

*Kimenet:*

* stabil authority-réteg
* egységes nyelv a rendszer minden részében

---

### Akciócsoport B — Context policy kialakítása

*Teendők:*

* minden skillhez context policy
* minden subagenthez allowed context scope
* default tiltás, ahol nem kell teljes repo-context

*Kimenet:*

* kevesebb token
* kevesebb kontextus-alapú ellentmondás
* jobban elszigetelt agent-szerepkörök

---

### Akciócsoport C — Change-impact engine v1

*Teendők:*

* kritikus fájlok listázása
* dependency mapping létrehozása
* változás → érintett docs/skills/hooks összerendelése

*Kimenet:*

* gyorsabb review
* gyorsabb újraauditálás
* kisebb regressziós kockázat

---

### Akciócsoport D — Hook implementáció

*Teendők:*

* P1 guardok megvalósítása
* majd P2 guardok megvalósítása
* végül logolás és governance evidence output finomítása

*Kimenet:*

* valódi enforcement, nem csak dokumentált szabályok

---

### Akciócsoport E — MCP policy és rollout

*Teendők:*

* approved MCP lista
* deny/allow policy
* secrets kivétele a repóból
* project-scope .mcp.json
* tool allowlist subagentenként

*Kimenet:*

* kontrollált tool-hozzáférés
* kisebb biztonsági és prompt-injection kockázat
* jobb kontextusfegyelem

---

## 4.3 RACI mátrix

### Szerepkörök

* *IM* = Implementation Manager / projektkoordináció
* *GA* = Governance Architect / constitutional és orchestration felelős
* *CE* = Claude Environment Engineer / .claude, skills, hooks, MCP kivitelezés
* *DR* = Documentation Reviewer / dokumentációs konzisztencia
* *TL* = Technical Lead / végső technikai döntéshozó
* *TM* = Teammate / együttműködő fejlesztő

| Munkaterület             | R  | A  | C      | I      |
| ------------------------ | -- | -- | ------ | ------ |
| CLAUDE.md véglegesítés | GA | TL | DR     | IM, TM |
| Terminology lock         | DR | GA | TL     | IM, TM |
| Context policy v1        | CE | GA | TL, DR | IM, TM |
| Change-impact map v1     | CE | GA | DR, TL | IM, TM |
| Hookok P1                | CE | TL | GA     | IM, TM |
| Hookok P2                | CE | TL | GA, DR | IM, TM |
| MCP Policy v1            | CE | TL | GA     | IM, TM |
| MCP rollout              | CE | TL | GA, TM | IM, DR |
| End-to-end audit         | DR | TL | GA, CE | IM, TM |

---

## 4.4 Szükséges erőforrások

### Emberi erőforrás

* 1 governance / documentation owner
* 1 .claude / workflow / hooks implementáló
* 1 technical decision owner
* 1 review/QA szerepkör

### Technikai erőforrás

* véglegesített canonical dokumentáció
* működő .claude struktúra
* végleges CLAUDE.md
* végleges system-orchestration.yaml
* skill fájlok
* project-scope .mcp.json
* GitHub branch / review workflow

### Szervezeti erőforrás

* egyértelmű authority a constitutional döntésekre
* merge discipline
* issue / PR governance szokásrend

---

## 4.5 Kockázatok és mitigáció

| Kockázat                                           | Hatás   | Valószínűség | Mitigáció                                                     |
| -------------------------------------------------- | ------- | -----------: | ------------------------------------------------------------- |
| Újra több constitutional változat jelenik meg      | Magas   |      Közepes | Egyetlen hivatalos CLAUDE.md, superseded policy             |
| Terminológiai drift visszatér                      | Közepes |        Magas | terminology map + final alignment pass                        |
| Hook blueprint marad, de enforcement nem készül el | Magas   |      Közepes | P1 hookok külön sprintként kezelése                           |
| Túl sok context jut a subagentekhez                | Magas   |        Magas | explicit context policy, default tiltás                       |
| MCP túl gyorsan bővül                              | Magas   |      Közepes | minimal MCP rollout, allowlist-first                          |
| Külső MCP tartalom truth-source szerepbe csúszik   | Magas   |      Közepes | role-matched doc guard + MCP usage guard                      |
| Change-impact logika nem kerül formalizálásra      | Közepes |        Magas | declarative map v1 még az első governance buildout szakaszban |
| Docs és runtime újra szétcsúszik                   | Magas   |      Közepes | doc-code-sync guard + end-to-end audit                        |

---

## 5. Executive Conclusion

A projekt következő szakaszának sikere nem azon múlik, hogy hány új agentet vagy eszközt kapcsoltok be, hanem azon, hogy a már kialakult governance modellt *fegyelmezett, operatív rendszerré* tudjátok-e alakítani.

A jelenlegi állapot elég stabil ahhoz, hogy továbblépjetek. A fő feladat most már nem a constitutional alap újraírása, hanem az, hogy:

* a context routing valódivá váljon,
* a változásokhoz impact-routing tartozzon,
* a fő constitutional guardok ténylegesen fussanak,
* a tool-hozzáférés role-scoped és kontrollált legyen,
* és a rendszer egészéről auditálható módon meg lehessen mondani, hogy konzisztens-e.

A javasolt megközelítés alapján a következő legjobb lépés a *Phase 1 és Phase 2 lezárása egymás után*, majd erre építve a hook enforcement és a kontrollált MCP rollout. Ha ezt a sorrendet tartjátok, a .claude réteg nem csupán dokumentált szándék marad, hanem tényleges projekt-operációs infrastruktúra lesz.