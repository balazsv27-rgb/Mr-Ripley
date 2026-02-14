A források alapján a **Trading Sims 2024** (más néven **MarketMentor**) technikai architektúrája nem egy hagyományos kereskedési platformot, hanem egy „globális pénzügyi nyelvtanfolyamot” szolgál ki, ahol a cél a piaci összefüggések és a kereskedési pszichológia megértése. Az architektúra elsődleges technikai célja a **„raw signal → strukturált event”** átalakítás, amely lehetővé teszi a narratívák és kockázatok számszerűsítését.

Az architektúra kulcsfontosságú moduljai a következők:

### 1. Ingestion Layer (Adatbeviteli réteg)
Ez a réteg felelős a piaci adatok, hírek és metaadatok begyűjtéséért. A források prioritási szintekre vannak osztva a hitelesség növelése érdekében:
*   **Priority 1 (Core):** Fed, ECB, Reuters, Bloomberg – ezek a legmagasabb hitelességű források.
*   **Adatforrások:** A rendszer hibrid módon használ RSS feedeket, API-kat (pl. FRED, BLS API a makroadatokhoz) és strukturált HTML scrapinget.
*   **Zajszűrés:** SHA-256 alapú duplikáció-szűrést és forrás-súlyozást alkalmaznak, hogy elkerüljék a piaci zajt.

### 2. Event-Driven Pipeline és Event Bus
A rendszer skálázhatóságát és rugalmasságát egy **eseményvezérelt architektúra** biztosítja, amelynek központi eleme a **Redis + RQ/Celery** alapú **Event Bus**.
*   Ez a megoldás lehetővé teszi a modulok (crawler, AI worker, scoring engine) közötti laza csatolást.
*   Minden hír egy egyedi **Event objektumként** halad végig a folyamaton, amely rögzíti a forrást, az időpontot és a hozzárendelt narratívát.

### 3. AI Processing és Scoring Engine
Az elemzési fázisban az NLP (természetes nyelvfeldolgozás) parsing során a rendszer felismeri az entitásokat (pl. Fed, Powell) és a témákat (pl. infláció, kamatdöntés).
*   **Domain-specific Scoring Layer:** Egy konfigurálható (YAML alapú) réteg, amely a traderek tudását matematikai súlyokká alakítja.
*   **Narrative Engine:** Az eseményeket időbeli klaszterekbe rendezi, felismerve a domináns piaci történeteket (pl. „kamatvágás várható”).
*   **Uncertainty Engine:** Egy 0–100 közötti indexet számol, amely a hírek ellentmondásossága és a piaci volatilitás alapján jelzi a rendszer bizonytalanságát.

### 4. Scenario Generator és AI Mentor
Az architektúra legfontosabb kimenete nem egy egyszerű árjóslat, hanem **szcenáriók generálása**.
*   **Valószínűségi alapú előrejelzés:** A rendszer historikus analógiákat keres (pl. „a múltbeli 24 hasonló Fed-beszédből 17-szer emelkedett az ár”), és sávos előrejelzést ad konfidenciaszinttel.
*   **AI Mentor:** Ez a réteg magyarázza el a felhasználónak az „ok-okozati láncot” (pl. Fed kamatemelés → erősödő dollár → gyengülő arany), összekötve a technikai adatokat a pedagógiai tartalommal.

### 5. Simulation és Portfolio Engine
A rendszer támogatja a kockázatmentes gyakorlást virtuális portfóliók segítségével.
*   **Simulation Microservice:** Snapshotokat készít az árakról, és követi a fiktív pozíciókat, miközben a háttérben futó **Tisza-pipeline** folyamatosan szállítja a narratívákat a döntések kiértékeléséhez.
*   **Backtesting:** Lehetővé teszi korábbi időszakok eseményeinek visszajátszását, segítve a „mi lett volna, ha” típusú tanulást.

Az architektúra moduláris felépítése biztosítja, hogy a rendszer később könnyen bővíthető legyen más eszközosztályokra (olaj, részvények, kripto) is, csupán új adatadapterek és scoring szabályok hozzáadásával.