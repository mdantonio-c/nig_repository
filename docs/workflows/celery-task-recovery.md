# Celery: task lunghi, ack anticipato e recupero (#86)

## Contratto

`launch_pipeline`, `launch_joint_analysis`, `omics_run_batch` e
`omics_fetch_results` dichiarano `idempotent=False`: RAPyDo 2.4 traduce il valore
in `acks_late=False`. Il messaggio viene confermato prima dell'esecuzione e Redis
non lo riconsegna allo scadere del `visibility_timeout` predefinito (un'ora).
I retry espliciti e `autoretry_for=(ConnectionResetError,)` rimangono invariati;
RAPyDo aggiunge `CeleryRetryTask`, con massimo cinque retry e backoff/jitter.
`omics_poll_tasks`, `omics_cleanup` e `test_task` mantengono l'ack tardivo.

**Compromesso:** un processo worker perso dopo l'ack non causa una riconsegna
automatica. Stato e output parziali rimangono nei checkpoint già persistiti.
Non confondere un task Celery `SUCCESS` con il completamento della pipeline:
la joint attuale non controlla il booleano restituito da Snakemake e non ha un
campo di esito sul job. Verificare log, callset e output.

La guardia in `launch_joint_analysis` rifiuta di rieseguire un UUID già presente
su `JointAnalysisJob`, anche quando ci sono duplicati storici. Non è un lock
distribuito fra UUID differenti né una procedura di resume: un retry dopo la
creazione del job è deliberatamente bloccato, per non ripetere un update parziale.
La pipeline locale conserva invece il comportamento dei retry applicativi
preesistente, senza guardia sul nodo `Job`: un retry esplicito dopo la sua
creazione può produrre un altro job con lo stesso UUID. L'early ack elimina la
redelivery Redis, non rende idempotente un retry o un rilancio manuale.

## Prima di recuperare

1. Ottenere autorizzazione sull'ambiente e sull'insieme esatto dei dataset.
2. Verificare worker attivi, task riservati e processi figli Snakemake/GATK:
   l'assenza di avanzamento in Neo4j **non** prova che il processo sia morto.
   Le operazioni lunghe possono mantenere lo stesso timestamp per ore.
3. Archiviare fuori da git UUID task/batch/dataset, stato, relazioni, log e
   checkpoint. Non registrare token, credenziali o sequenze genomiche.
4. Non rilanciare un task sullo stesso output/workspace mentre un'altra
   esecuzione potrebbe essere attiva. Nessun reset massivo di `RUNNING`.

## Recupero per task

| Task/checkpoint | Comportamento dopo crash | Azione |
|---|---|---|
| `launch_pipeline`: `QUEUED`/`RUNNING`, relazione `ANALYZED_BY` | Nessun recupero automatico del dispatcher (seleziona solo `UPLOAD COMPLETED`) | Segnalare agli operations; confermare assenza di processi, FASTQ disponibili e checkpoint. Con approvazione rilanciare un nuovo task sulla lista esplicita con `force=False`, preservando job storico e intermedi. La pipeline esegue già `force_incomplete=True` e QC finali. Non impostare `COMPLETED` manualmente. |
| `launch_joint_analysis`: job creato, `joint_analysis=True` | Stato utente del dataset non passa a `RUNNING`: i dataset erano già `COMPLETED`; l'esito joint va letto dai log | Un UUID esistente è bloccato dalla guardia. Verificare il workspace e il manifest; per un update parziale serve backup consistente e ripristino approvato prima di un nuovo UUID. Non assumere che ripetere GenomicsDBImport sia sicuro. Non rimuovere il job per aggirare la guardia. |
| `omics_run_batch`: ancora `QUEUED`, senza `omics_task_id` | Upload può essere incompleto; batch resta attivo | Dopo aver escluso worker concorrenti, rilanciare sul batch originale e lista esplicita. Gli upload riprendono per nome remoto/checkpoint e i dataset con task ID vengono saltati. Non creare un nuovo batch o liberare i claim alla cieca. |
| `omics_run_batch`: `SUBMITTING`/`SUBMIT_UNKNOWN` | Submit forse accettata, risposta non registrata | Non reinviare né cancellare gli input. Il rilancio del batch converte `SUBMITTING` in `SUBMIT_UNKNOWN` senza una seconda submit. Riconciliare con Omics, richiedendo eventuale sblocco manuale. Un ID remoto noto in `SUBMIT_UNKNOWN` non basta: il poller non seleziona questo stato. |
| Omics `SUBMITTED`/`RUNNING` con `omics_task_id` | L'elaborazione remota continua | Il poller esistente legge lo stato Omics e avvia il fetch quando il task è completo. Nessun nuovo upload/submit. |
| `omics_fetch_results`: `FETCHING` | File `.part` o artifact parziali; nessuna DELETE prima dei controlli locali | Il poller riaccoda dopo `OMICS_FETCH_RETRY_MINUTES` (default 60), fino a `OMICS_FETCH_MAX_ATTEMPTS` (default 5), poi segnala `ERROR`. Artifact locali già registrati non vengono riscaricati; il download interrotto riparte da zero. |
| `omics_fetch_results`: `CLEANUP PENDING` | Output già verificati, DELETE incompleta | Il poller ritenta il cleanup senza limite di tentativi. Non cancellare output locali; DELETE ripetute su Omics sono idempotenti. |

Il dispatcher segnala i batch stale tramite `OMICS_BATCH_STALE_HOURS` (default
48), ripetendo l'avviso al massimo una volta per tale finestra;
`check_omics_state` aiuta a verificare i
checkpoint, ma **non** ripara automaticamente uno stato di submit incerto.
Il fetch può essere riaccodato dal poller anche se un download è soltanto lento:
l'early ack elimina la redelivery Redis, non introduce un lease contro quella
concorrenza applicativa. Prima dei WGS produttivi verificare il backoff rispetto
alla durata del fetch e l'assenza di fetch simultanei.

## Duplicato storico joint in dev

Per il task `9707af5b-18a9-43d2-8e1a-cf3f6a4471a6`, il precheck del 2026-11-25
ha trovato due job con stesso tipo/reference e stessi tre dataset. Conservare il
job originale; eliminare **solo** il nodo della riconsegna e le sue relazioni
duplicate, dopo confronto dei checkpoint. Workspace, marker, manifest e output
non vanno toccati. Conservare il report di rollback fuori dal repository.

## Validazione e deploy

- Test unitari dei quattro decoratori e dei tre task lasciati invariati.
- Test della guardia joint su prima/seconda consegna e duplicati storici.
- Test già presenti sui checkpoint di batch, polling e fetch.
- Prova isolata in dev con task oltre un'ora e verifica assenza di seconda
  esecuzione. Un task diagnostico non certifica da solo il recupero di un update
  GenomicsDB parziale: quella prova rimane separata.
- Il codice bind-mounted non aggiorna un worker già avviato: serve un restart
  autorizzato, dopo drenaggio dei task e verifica dei processi figli. Il rollout
  non può considerare il fix attivo prima di controllare `acks_late` sui quattro
  task effettivamente registrati nel nuovo worker.
- Commit e MR verso `dev` a cura dell'utente; aggiornare le issue soltanto dopo
  il merge.

### Evidenza diagnostica dev — 2026-11-25

Prova autorizzata su nig-dev, processo worker effimero separato (`prefork`,
concorrenza 1), coda dedicata, Celery 5.2.7 e connector RAPyDo 2.4 reali.
Le quattro dichiarazioni locali sono state registrate tramite il decorator
RAPyDo su funzioni diagnostiche senza effetti: `acks_late=False` per tutte.
Il broker Redis aveva `visibility_timeout=3600` secondi.

- Task diagnostico `170af689-7664-4551-b89d-f1cf8e92ff81`.
- Inizio 12:19:24 UTC, termine 13:24:24 UTC.
- Durata misurata **3900,001 secondi**, una esecuzione osservata, `PASS`.
- Arresto automatico del solo worker diagnostico; coda già assente e binding
   diagnostico ripulito alle 13:25 UTC.
- Nessuna pipeline genomica, modifica agli output, upload Omics o restart del
   worker ordinario.

Questa prova verifica l'ack anticipato oltre la soglia Redis, non l'esecuzione
dei quattro task applicativi completi né il recupero di un update GenomicsDB
interrotto. Il worker ordinario deve ancora ricevere il codice e la nuova
configurazione con deploy/restart autorizzato e controllo dei task registrati.
La suite unitaria locale conta **301 passed**, con cinque warning di dipendenze.