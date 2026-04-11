> **HISTORICAL / NON-CANONICAL**
> This file is not part of the canonical 7-document authority set.
> Canonical truth is defined by the canonical documentation set and `CLAUDE.md`.

Rendben — akkor a hangsúlyt most nem a saját elméleti architektúrátokra teszem, hanem arra, hogy *a Claude Code hivatalos megoldásaival ezt pontosan hogyan lehet megvalósítani*.

## Mit érdemes másképp nézni

A jelenlegi tervetek jó, csak eddig inkább *belső governance logikaként* volt leírva. A következő lépés az, hogy ezt lefordítsátok a Claude Code tényleges építőelemeire. Az Anthropic dokumentáció alapján ehhez a legerősebb, hivatalosan támogatott komponensek ezek:

* *Subagentek* szerepkörös delegálásra és tool-korlátozásra. A Claude Code támogatja, hogy a subagentekhez külön description, tools, disallowedTools, mcpServers, hooks, skills, memory, isolation és egyéb mezőket adjatok meg. A subagentek alapból öröklik a fő beszélgetés eszközeit, de ezt allowlisttel vagy denylisttel le lehet szűkíteni. ([Claude API Docs][1])
* *Hookok* valós idejű guardolásra. A hooks rendszer támogat PreToolUse, PostToolUse, PostToolUseFailure, PermissionRequest és más eventeket, és az MCP toolokat is ugyanúgy lehet hookkal figyelni, mert normál toolként jelennek meg mcp__<server>__<tool> névformában. ([Claude API Docs][2])
* *Skillek* újrahasználható, csak szükség esetén betöltődő működési egységként. A skill leírások betöltődnek, de a teljes skill tartalom csak akkor kerül kontextusba, amikor tényleg invoke-oljátok; viszont a preloadolt skilles subagentek másként működnek, mert ott a teljes skilltartalom startupkor bekerülhet. Skillen belül allowed-tools mezővel lehet korlátozni az aktív eszközöket. ([Claude API Docs][3])
* *MCP* kontrollált tool- és adatforrás-hozzáférésre. A Claude Code project scope-on `.mcp.json`-ban tud közösen használt MCP szervereket kezelni, támogat environment variable expansiont, tool searcht és OAuth alapú vagy egyéb auth megoldásokat. ([Claude API Docs][4])
* *Tool Search* a kontextusterhelés csökkentésére. Az MCP tool definíciók deferred módon működnek, vagyis alapból nem minden tool schema töltődik be upfront; ez kifejezetten segít a context-terhelés és tokenfogyasztás kordában tartásában. ([Claude API Docs][4])
* *Project memory* és a Claude által karbantartott memóriafájlok. A Claude Code a projektmemóriát on-demand olvassa és írja a projektmemória könyvtárban, tehát van hivatalos mechanizmus a hosszabb távú, sessionök közti tudásréteghez. ([Claude API Docs][5])

Most az a kérdés, hogyan lehet a ti roadmapeteket ezekre a hivatalos mechanizmusokra ráültetni.

## Hol tartotok most, Claude Code nyelvre lefordítva

A projektetekben már megvan a *constitutional layer* és a *canonical doc authority modell*. Ezt a Claude Code oldaláról úgy lehet felfogni, hogy a CLAUDE.md már egy rögzített, projekt-specifikus governance forrás, a system-orchestration.yaml pedig már egy deklaratív workflow blueprint. Vagyis a “mit kellene csinálni” szintje nagyjából kész.

Ami még nincs teljesen kész, az a “Claude Code pontosan milyen mechanizmusával fogjuk ezt kikényszeríteni” szint. Itt jön be a Subagent + Hook + Skill + MCP négyese.

## Hova akartok eljutni, Claude Code szempontból

A célállapot egy olyan Claude Code projektkonfiguráció, ahol:

* a *subagentek* specializáltak és nem örökölnek fölösleges toolokat;
* a *skillek* csak akkor töltődnek be, amikor tényleg kell, és ahol kell, ott allowed-tools mezővel további szűkítés van;
* a *hookok* a kritikus szabályokat ténylegesen blokkolják, nem csak dokumentációban írják le;
* az *MCP* szűk, project-scoped és policy-vezérelt;
* a *Tool Search* és a context policy együtt csökkentik a tokenpazarlást;
* a *memory* nem kontrollálatlan szemétlerakó, hanem karbantartott projektmemória.

Más szóval: a célállapot nem egy “sok Claude-feature egyszerre” rendszer, hanem egy *szigorúan konfigurált Claude Code runtime*.

## A roadmap most már Claude Code feature-ökre vetítve

### 1. Egyetlen végleges CLAUDE.md és constitution-change szabály

Ez már megvan, de a Claude Code hivatalos működéséhez igazítva itt az a következő lépés, hogy a constitution változásait *hookkal és workflow-val kössétek össze*. A hook rendszer erre alkalmas, mert tool-eseményeknél beavatkozhat, a common workflows dokumentáció pedig kifejezetten javasolja a projekt-specifikus subagenteket és a szűk eszközhasználatot. ([Claude API Docs][2])

*Mit jelent ez konkrétan?*
Ha valaki a `CLAUDE.md`-t módosítja, a rendszernek nem csak diffet kell látnia, hanem automatikusan el kell indítania:

* a role-matched review-t,
* a workflow review-t,
* és a governance skillek hatásvizsgálatát.

Ezt legjobban egy *PostToolUse hook + change-impact szabály* kombinációval tudjátok megfogni.

### 2. Minimal-context routing megvalósítása subagentekkel és skillekkel

Ez a roadmapetek egyik legfontosabb pontja, és Claude Code oldalon erre a leghivatalosabb eszköz a *subagent tool restriction + skill invocation model*.

Az Anthropic docs szerint a subagenteknél lehet:

* tools allowlistet adni,
* disallowedTools denylistet adni,
* külön skills listát adni,
* és akár mcpServers és hooks szintű szűkítést is alkalmazni. ([Claude API Docs][1])

*Nálatok ezt így érdemes megcsinálni:*

* A doc-truth-classification ne legyen egy általános agent. Legyen egy olyan subagent vagy skillvezérelt alagent, amely csak olvasási toolokat kap:

  * Read
  * Grep
  * Glob
  * esetleg egy nagyon szűk GitHub vagy repo-olvasó eszköz
    és *ne kapjon*
  * Edit
  * Write
  * semmilyen write-capable MCP-t
  * DB write vagy shell write hozzáférést.
    Az Anthropic docs konkrét példát adnak arra, hogy egy subagentet csak olvasó toolokra korlátozzatok. ([Claude API Docs][1])

* A build-sequence-compliance-check szintén kapjon csak olvasó toolokat, és a skills mezőben csak a build-sequence logikát hordozó skillje legyen aktív.

* A snapshot-contract-check kaphat olvasó code access-t, és opcionálisan read-only MCP-t, de ne kapjon semmilyen külső write toolt.

* A jövőbeli PR / issue agent lehet az, amelyik GitHub MCP-t kap, de ez ne öröklődjön át automatikusan minden más agentre.

Ez a Claude Code nyelvén azt jelenti, hogy *a minimal-context routing nem egy elméleti elv lesz, hanem a subagent frontmatter és skill frontmatter eszközkorlátozásából következik*.

### 3. Change-impact map megvalósítása hookokkal és a workflow blueprinttel

A change-impact logika a Claude Code-ban nincs készen “Mr. Ripley impact graph” néven, de a hook rendszer és a strukturált workflow ezt nagyon jól támogatja. A hooks docs szerint a hookok minták alapján képesek konkrét toolhasználatot, toolnevet vagy eseményt megfogni. Az Agent SDK dokumentáció is jelzi, hogy matcher alapú hook-konfiguráció létezik. ([Claude API Docs][2])

*Nálatok a change-impact map első verzióját így érdemes megcsinálni:*

* a system-orchestration.yaml`-ba tegyetek egy deklaratív change_impact_map` blokkot;
* a hook figyelje, hogy melyik fájl változott;
* a hook vagy a kapcsolódó skill ennek alapján generáljon egy “required re-check” listát.

Ez még nem AST-szintű csodatechnika, de bőven elég első körre. Claude Code oldalról ezt a hookokkal és a projektfájlok szerkezeti lekérdezésével simán meg lehet támogatni.

### 4. Hookok prioritás szerinti implementálása

Ez a pont szinte egy az egyben Claude Code hooks funkcionalitás. Itt az a kulcs, hogy ne egyből mindent akarjatok automatizálni, hanem tényleg a legnagyobb értékű guardokkal kezdjetek.

Az első hullámnál ezeket érdemes közvetlenül hookokra építeni:

* **snapshot-boundary-guard**
  PreToolUse vagy PostToolUse hookkal figyelhető, hogy történik-e tiltott downstream hozzáférés a nyers Layer-2 truth felé. Az MCP toolokat is ugyanígy lehet nézni, mert normál toolnévként jelennek meg. ([Claude API Docs][2])

* **role-matched-doc-guard**
  Ez lehet olyan guard, amely bizonyos edit vagy write esemény után ellenőrzi, hogy a strong claim-ekhez megfelelő canonical source volt-e használva.

* **live-readiness-claim-blocker**
  Ezt különösen jól lehet hookkal csinálni, mert a rendszeretekben a live execution továbbra is tiltott; tehát minden olyan tartalom, amely live-ready vagy execution-enabled állítást próbál beírni, blokkolható.

Ez a Claude Code feature-készletével teljesen natív módon megvalósítható; itt tényleg nem kell semmi idegen kerülőút.

### 5. Skill-rendszer tudatos szétválasztása

A ti skilleitek közül a mostaniak tipikusan *workflow/governance skill-ek*, nem capability uplift skill-ek. Claude Code oldalról ez azért jó, mert a skillek pontosan erre valók: célzott, újrahasználható viselkedési csomagok, amelyek csak invoke esetén töltődnek teljesen be. Ugyanakkor az Anthropic docs figyelmeztetnek, hogy ha egy subagent preloadolt skillt használ, akkor annak teljes tartalma startupkor bekerülhet a kontextusba. ([Claude API Docs][3])

*Ez nálatok gyakorlati döntést jelent:*

* a nagy, hosszú governance skill-eket ne preloadoljátok feleslegesen minden subagenthez;
* inkább legyenek invoke-olható, különálló skill-ek;
* csak a tényleg szükséges agent kapja meg őket.

Így a skill-réteg nem fogja tönkretenni azt a tokenfegyelmet, amit a minimal-context routinggel éppen meg akartok nyerni.

### 6. MCP-réteg: szűk, project-scope, policy-vezérelt

A Claude Code MCP dokumentációból a legfontosabb tanulság nálatok az, hogy a *project scope* a megfelelő hely a közösen használt, repo-szintű MCP-khez, és ezt `.mcp.json`-ban tudjátok tárolni. A docs támogatják az environment variable expansiont is, tehát nincs mentség arra, hogy plain text secret kerüljön a repóba. ([Claude API Docs][4])

*Mr. Ripley MCP v1 javaslat, Claude Code szerint:*

* github project-scope szerver
* context7 project-scope szerver
* egy read-only internal/stdio vagy hasonló belső szerver, amely csak a szükséges metainformációkat adja
* minden más maradjon local vagy user scope, vagy egyáltalán ne legyen bekötve

A docs alapján a project-scoped MCP szerverek csapatmegosztásra valók, és a .mcp.json erre van kitalálva. A tool search miatt az MCP-k nem terhelik azonnal túl a kontextust, mert a tool definíciók deferred módon kezelődnek. ([Claude API Docs][4])

*Ez nálatok azt jelenti:*

* lehet MCP-t használni anélkül, hogy azonnal tokenkatasztrófát csinálnátok;
* de csak akkor, ha kevés szerveretek van és minden role-scoped.

### 7. Tool access segmentation: subagentenkénti allowlist / denylist

A Claude docs egyik legerősebb, és nektek legfontosabb megoldása, hogy a subagentek toolkészlete explicit korlátozható. A common workflows dokumentáció még külön ki is mondja, hogy limitáljátok a tool access-t arra, amire az adott subagentnek ténylegesen szüksége van. ([Claude API Docs][1])

*Ez a ti megvalósításotokban így nézzen ki:*

* audit agent: csak olvasó toolok
* classification agent: csak olvasó toolok + releváns skill
* PR agent: GitHub MCP + olvasó repo toolok
* MCP-s hozzáférést csak annak az agentnek adjatok, akinek muszáj
* ahol van MCP, ott a hookok figyeljék és korlátozzák a használatot

Ez a lépés fogja a legerősebben megakadályozni, hogy az egész rendszerből szépen megszervezett, de drága káosz legyen.

### 8. Memory hygiene: ne hagyjátok, hogy a memória legyen az új káosz

A Claude Code memóriafájljait a rendszer projekt-szinten olvassa és írja, tehát van beépített mechanizmus a sessionök közötti tudásra. De ez nem jelenti azt, hogy mindent oda kell önteni. A docs alapján Claude a projektmemóriát on-demand kezeli. ([Claude API Docs][5])

*Nálatok ezt így kell használni:*

* a memory ne legyen authority source;
* a memory legyen inkább rövid, konszolidált operational note réteg;
* canonical truth továbbra is a docs és a constitution;
* időnként legyen memory hygiene pass, hogy ne növekedjen kontroll nélkül.

### 9. Költség- és context-fegyelem mérése

A Claude Code docs javasolják a /context használatát arra, hogy lássátok, mi fogyasztja a kontextust, és a status line rendszer is alkalmas arra, hogy költséget és context usage-et megjelenítsetek. Emellett a Tool Search és az MCP deferred loading is pont azért van, hogy ezt kordában tartsátok. ([Claude API Docs][6])

*Ez gyakorlati ajánlás nálatok:*

* minden nagyobb subagent / skill / MCP rollout után nézzétek meg a /context képet;
* ha valami túl sokat visz, nem újabb modell kell, hanem jobb context policy;
* akár status line-ban is kitehetitek a context usage és cost indikátort.

## Mit csinálnék most pontosan, ha ezt Claude Code-hivatalos módon kellene végigvinni

Először lezárnám a constitutiont és a terminológiát. Utána minden meglévő subagenthez és skillhez írnék explicit tool és context policy-t. Ezután bekötném a három P1 hookot natív hooks mechanizmussal. Ezután jönne a declarative change-impact map a YAML-ben. Csak ezek után vezetném be a szűkített project-scope MCP v1-et, és csak ezután finomítanám a memoryt és a költségfigyelést.

Vagyis Claude Code oldalról a sorrend ez lenne:

1. *Subagent config rendbetétele* (tools, disallowedTools, skills, esetleg mcpServers) ([Claude API Docs][1])
2. *Skill invoke/logika finomítása* és preload kerülése, ahol nem kell ([Claude API Docs][3])
3. *Hookok implementálása* a P1 guardokra ([Claude API Docs][2])
4. **Project-scope .mcp.json** minimális szerverkészlettel, env expansionnel ([Claude API Docs][4])
5. *Tool Search bekapcsolva hagyása* és context/cost mérés ([Claude API Docs][4])
6. *Project memory hygiene* mint külön karbantartási rutin ([Claude API Docs][5])

## A lényeg, nagyon tisztán

A ti projekteteknél a Claude Code hivatalos megoldásaiból *nem mindent* kell használni, hanem ezt a kombinációt:

* *subagentek* a role-szűkítéshez,
* *skillek* az invoke-olható governance logikához,
* *hookok* a valós idejű blokkoláshoz,
* *MCP* a szűk, kontrollált tool-réteghez,
* *Tool Search* a tokenfegyelemhez,
* *memory* pedig csak karbantartott másodlagos operational rétegként.

Egy mondatban:

*Mr. Ripley-ben ezt Claude Code-dal úgy lehet jól megvalósítani, hogy a governance modell minden elemét egy hivatalos Claude mechanizmushoz kötitek: a szerepeket subagentekhez, a szabályokat skillekhez, a védelmet hookokhoz, a külső hozzáférést MCP-hez, a tokenfegyelmet pedig Tool Search-höz és explicit context policy-hoz.*

Ha szeretnéd, a következő körben ebből csinálok egy *konkrét “Claude Code implementation blueprint for Mr. Ripley”* dokumentumot, szekciónként: Subagents, Skills, Hooks, MCP, Memory, Tool Policy.

[1]: https://docs.anthropic.com/en/docs/claude-code/sub-agents?utm_source=chatgpt.com "Create custom subagents - Claude Code Docs"
[2]: https://docs.anthropic.com/en/docs/claude-code/hooks?utm_source=chatgpt.com "Hooks reference - Claude Code Docs"
[3]: https://docs.anthropic.com/en/docs/claude-code/slash-commands?utm_source=chatgpt.com "Extend Claude with skills - Claude Code Docs"
[4]: https://docs.anthropic.com/en/docs/claude-code/mcp?utm_source=chatgpt.com "Connect Claude Code to tools via MCP"
[5]: https://docs.anthropic.com/en/docs/claude-code/memory?utm_source=chatgpt.com "How Claude remembers your project - Claude Code Docs"
[6]: https://docs.anthropic.com/en/docs/claude-code/costs?utm_source=chatgpt.com "Manage costs effectively - Claude Code Docs"