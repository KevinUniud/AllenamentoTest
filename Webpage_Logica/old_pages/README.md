# HTML precedenti alla migrazione Next.js

Questa cartella conserva una copia dei 21 HTML legacy ancora presenti nel
progetto, con contenuto e struttura delle sottocartelle invariati.

Gli originali restano nei rispettivi percorsi di `Webpage_Logica/`: durante
la migrazione incrementale, `src/lib/pages.mjs` li legge per generare le
pagine Next.js. Per modificare il sito corrente usare quei sorgenti o i
componenti React, senza aggiornare automaticamente questo archivio.

`old_pages/` e un archivio dei soli HTML, non una copia autonoma del sito:
i riferimenti relativi a CSS, script e immagini conservano i percorsi originali.
La cartella non viene copiata in `public/`, nell'export Next o nell'immagine
Docker Web. Rimane invece disponibile nei sorgenti e nei futuri bundle.
