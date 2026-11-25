# Verifica del bundle Omics nell'arrival check (#85)

Il controllo in [check_omics_arrival.py](../../projects/nig/backend/scripts/check_omics_arrival.py)
legge l'header BAM con `samtools view --no-PG -H` (timeout 60 s).
Non modifica il BAM e non aggiunge una riga `@PG` di samtools. I controlli
preesistenti su dizionario binario, `@SQ`, read group e indici restano invariati.

La sezione `genome` di [joint.yaml](../../projects/nig/backend/snakemake/joint.yaml)
è la fonte di `reference_id` e `omics_reference_root`. Il root identifica il
mount Omics del mapping `nig_hg38`, non il mount NIG `/resources`.
Per ambienti con mount differenti aggiornare il root nella configurazione
genome; il comando standalone consente l'override `--omics-reference-root`.
L'eseguibile è selezionabile con `--samtools`.

Quando viene fornito il BAM, il report richiede una sola riga `@PG` con
`PN` oppure `ID` uguale a `pbrun fq2bam` e una command line valida. Deve contenere:

- un `--ref`;
- esattamente tre `--knownSites` distinti;
- un `--interval-file`.

Tutti i path devono essere assoluti e contenuti in
`<omics_reference_root>/<reference_id>/bundle/`. Un altro bundle, un prefisso
simile, traversal, parametri mancanti o duplicati producono `FAIL`.
Il report conserva solo i path delle risorse trovate, mai l'intera command line
con input, read group e identificativi remoti. Un errore di esecuzione/timeout
rimane un errore tecnico e il fetch conserva i checkpoint per il retry.

Il fetch chiama automaticamente l'arrival check prima delle DELETE. Un `FAIL`
del controllo bundle porta il dataset a `ERROR` e conserva gli output remoti;
gli errori tecnici restano recuperabili dal poller. Senza `--bam`, il controllo
standalone continua a verificare soltanto il gVCF: non certifica la provenienza
fq2bam.

I path in `@PG` provano la selezione della directory versionata, **non** il
contenuto dei file. Restano necessari checksum sull'installazione Omics e
immutabilità del bundle. T10 è chiuso in dev (16/16 checksum verificati il
2026-11-24); il checksum va ripetuto sul nuovo cloud produttivo.