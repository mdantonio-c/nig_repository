# Standardizzazione file VCF per piattaforma NIG

**Sara Devito, Khadija Sana Hafeez, Elisabetta Casalone, Giuseppe Matullo**

*Genomic Variation, Complex Diseases and Population Medicine Unit, Department of Medical Sciences, University of Turin, 10126 Turin, Italy*

---

> **Documento riservato — Non condividere senza autorizzazione.**

---

Con la seguente guida ci si pone l'obiettivo di illustrare come eseguire un'Analisi delle Componenti Principali (PCA) a partire da un file VCF aggregato, come identificare e marcare gli outlier nello spazio delle componenti principali, ed infine, come calcolare le frequenze alleliche e genotipiche per tutti i sample che non sono marcati come outlier. Al termine dell'analisi, vengono prodotti due file di output:

- un file VCF annotato, chiamato `groups_INFOtags_your_cohort.vcf.gz` come mostrato nella Sezione 8.3,
- un file `.txt` chiamato `outliers_mixedgroups.txt` (Sezione 8.3) contenente per ogni ID le macrocategorie fenotipiche di riferimento, utili per analisi successive di annotazione e stratificazione.

I due file di output così prodotti (`groups_INFOtags_your_cohort.vcf.gz` e `outliers_mixedgroups.txt`) sono quelli che andranno poi condivisi con il centro Cineca e UniTo per il progetto NIG.

---

## Indice

1. [Introduzione](#1-introduzione)
2. [Prerequisiti e Strumenti necessari](#2-prerequisiti-e-strumenti-necessari)
3. [Descrizione delle Coorti di input](#3-descrizione-delle-coorti-di-input)
   - 3.1 [Normalizzazione dei file VCF](#31-normalizzazione-dei-file-vcf)
4. [Rimozione di individui imparentati (PLINK 2.0)](#4-rimozione-di-individui-imparentati-plink-20)
   - 4.1 [Calcolo della parentela con PLINK 2.0 (KING table)](#41-calcolo-della-parentela-con-plink-20-king-table)
   - 4.2 [Creazione della lista dei campioni da rimuovere](#42-creazione-della-lista-dei-campioni-da-rimuovere)
   - 4.3 [Rimozione dei campioni imparentati dal VCF originale](#43-rimozione-dei-campioni-imparentati-dal-vcf-originale)
5. [Unione delle Coorti](#5-unione-delle-coorti)
   - 5.1 [Intersezione delle varianti comuni](#51-intersezione-delle-varianti-comuni)
   - 5.2 [Intersezione e unione delle coorti con PLINK 1.9 (WGS e dataset di grandi dimensioni)](#52-intersezione-e-unione-delle-coorti-con-plink-19-wgs-e-dataset-di-grandi-dimensioni)
     - 5.2.1 [Conversione dei VCF in formato PLINK](#521-conversione-dei-vcf-in-formato-plink)
6. [Esecuzione della PCA con PLINK](#6-esecuzione-della-pca-con-plink)
   - 6.1 [Identificazione e Marcatura degli Outlier](#61-identificazione-e-marcatura-degli-outlier)
   - 6.2 [Implementazione in R](#62-implementazione-in-r)
7. [Suddivisione del VCF per categorie di campioni (Trio)](#7-suddivisione-del-vcf-per-categorie-di-campioni-trio)
8. [Marcatura degli Outlier](#8-marcatura-degli-outlier)
   - 8.1 [Annotazione del file VCF con bcftools](#81-annotazione-del-file-vcf-con-bcftools)
     - 8.1.1 [Visualizzazione dei campi INFO](#811-visualizzazione-dei-campi-info)
   - 8.2 [Calcolo della frequenza allelica per italiani e outlier](#82-calcolo-della-frequenza-allelica-per-italiani-e-outlier)
   - 8.3 [Annotazione completa in un unico passaggio](#83-annotazione-completa-in-un-unico-passaggio)
   - 8.4 [Facoltativo: rimozione degli outliers dalla coorte](#84-facoltativo-rimozione-degli-outliers-dalla-coorte)

---

## 1 Introduzione

La coorte qui utilizzata come riferimento viene denominata *ITvarGM*, è composta da 300 campioni e un totale di 14832 varianti selezionate ad hoc performando linkage disequilibrium.

Si consideri, in questo studio, la coorte *ITvarGM* come rappresentativa della popolazione italiana. *ITvarGM* è stata costruita a partire da studi di popolazione, in particolare *Whole Exome Sequencing* (WES) e *SNP array*.

La coorte *ITvarGM* viene condivisa, in allegato, come set di riferimento per consentire la normalizzazione di nuove coorti di studio, garantendo così l'omogeneità dei dati genetici tra dataset differenti. Attraverso questa normalizzazione, è possibile eseguire in modo coerente analisi di *Principal Component Analysis* (PCA) e studi di stratificazione della popolazione, permettendo il confronto e l'integrazione dei risultati con quelli ottenuti dalla coorte di riferimento.

---

## 2 Prerequisiti e Strumenti necessari

Per eseguire questa pipeline sono richiesti:

- **PLINK v1.9/v2** (installato direttamente o tramite Docker container)
- **R** (consigliata versione ≥ 4.0) con le principali librerie per visualizzazione (`MASS`, `ggplot2`, `dplyr`, `readxl`)
- **BCFtools** (installato direttamente o tramite Docker container)
- **File di conversione dei nomi dei cromosomi:**

  1. File `no_chr_name_convention.txt`, con due colonne:
     ```
     chr1    1
     chr2    2
     ...
     chr22   22
     chrX    X
     ```

  2. File `chr_name_convention.txt`, con le colonne invertite:
     ```
     1    chr1
     2    chr2
     ...
     22   chr22
     23   chrX
     ```

- **Genoma di riferimento** in formato `.fa` e relativo indice `.fai` (per coerenza tra dati si consiglia l'utilizzo del build hg38). Disponibile da UCSC Genome Browser.

### Nota 1

Plink accetta in input file `VCF.gz` accompagnati dal relativo file di indice `.tbi`, è inoltre necessario che i VCF contengano il campo `GT` (genotipo) in quanto Plink utilizzerà questo campo per performare PCA.

### Nota 2

In questa analisi sotto la colonna `CHROM` gli elementi devono essere in formato `chrN`, dove N indica un qualsiasi cromosoma, invece ogni elemento della colonna `ID` deve essere riportato nella forma:

```
CHROM:POS:REF:ALT
```

Tale nomenclatura della colonna `ID` è stata scelta per rendere più semplice l'individuazione delle varianti comuni ai due file gVCF da intersecare.

---

## 3 Descrizione delle Coorti di input

- **ITvarGM**: utilizzato come coorte di riferimento, è fornito in build hg38 (disponibile anche in hg19), include 300 campioni italiani e contiene 14832 varianti, fornito con gli elementi della colonna `CHROM` con prefisso `chr` e con colonna `ID` con elementi formattati come `CHROM:POS:REF:ALT`.

- **your\_cohort**: Seconda coorte da confrontare con ITvarGM (possibilmente allineata su hg38).

### 3.1 Normalizzazione dei file VCF

Per normalizzare i VCF è necessario assicurarsi che:

- la colonna `CHROM` inizi con il prefisso `chr`,
- la colonna `ID` sia nel formato `CHROM:POS:REF:ALT`.

La nomenclatura che ci si aspetta di ritrovare nelle prime 5 colonne (dopo l'header) del VCF è la seguente:

| CHROM | POS   | ID               | REF | ALT |
|-------|-------|------------------|-----|-----|
| chr1  | 12345 | chr1:12345:A:T   | A   | T   |
| chr2  | 67890 | chr2:67890:G:C   | G   | C   |
| chrX  | 98765 | chrX:98765:T:TA  | T   | TA  |

Per riformattare la colonna `ID` come detto sopra:

```bash
bcftools annotate --rename-chrs /path/to/chr_name_convention.txt \
  /path/to/your_cohort.vcf.gz | \
  bcftools norm -Ou -f /path/to/hg38.fa | \
  bcftools annotate -Oz -x ID -I +'%CHROM:%POS:%REF:%ALT' \
  -o /path/to/newID_your_cohort.vcf.gz
```

Se la colonna `CHROM` non si presenta con il prefisso `chr`, si può modificare il prefisso utilizzando il seguente snippet:

```bash
bcftools annotate --rename-chrs /path/to/no_chr_name_convention.txt \
  /path/to/newID_your_cohort.vcf.gz \
  -Oz -o /path/to/noCHR_newID_your_cohort.vcf.gz
```

---

## 4 Rimozione di individui imparentati (PLINK 2.0)

La rimozione degli individui imparentati è un passaggio fondamentale per evitare distorsioni nelle analisi genetiche basate su varianti comuni. Una buona pratica consiste nell'applicare preliminarmente un processo di LD pruning, così da ridurre la correlazione tra varianti. Tuttavia, è importante notare che il metodo KING implementato in PLINK 2.0 è considerato robusto anche senza aver effettuato LD pruning, in questa guida non verrà mostrato come performarlo. Di seguito si mostra come eseguire l'identificazione e la rimozione dei campioni imparentati utilizzando direttamente PLINK 2.0 sul file VCF di partenza. Si noti che, qualora la coorte sia costituita da trii (genitori-probando), è possibile saltare questo passaggio, in quanto nella Sezione 7 verrà mostrato come suddividere il VCF dei trii in due VCF di genitori e probandi; nel caso quindi la coorte sia costituita da trii si può procedere direttamente alla Sezione 5.

### 4.1 Calcolo della parentela con PLINK 2.0 (KING table)

```bash
# Rimozione dei pazienti imparentati
plink2 \
  --vcf /path/to/your_cohort.vcf.gz \
  --make-king-table \
  --king-table-filter 0.088 \
  --king-cutoff 0.088 \
  --out /path/to/your_cohort
```

Questo comando produce il file `your_cohort.king.cutoff.out.id` che contiene gli ID degli individui considerati imparentati secondo la soglia di kinship scelta. Il file ha il formato:

```
#IID
ID_1
ID_34
ID_78
ID_102
...
```

### 4.2 Creazione della lista dei campioni da rimuovere

```bash
# Creo la lista degli individui da rimuovere
awk 'NR>1' your_cohort.king.cutoff.out.id > related_samples.txt
```

Il file `related_samples.txt` conterrà una singola colonna senza header, con un ID per riga come mostrato di seguito:

```
ID_1
ID_34
ID_78
ID_102
...
```

### 4.3 Rimozione dei campioni imparentati dal VCF originale

Si procede ora all'esclusione degli individui con parentela significativa, utilizzando direttamente il file VCF di partenza:

```bash
# Facoltativa rimozione degli outliers / individui imparentati
bcftools view --force-samples -S ^/path/to/related_samples.txt \
  /path/to/your_cohort.vcf.gz \
  -Oz -o /path/to/unrelated_your_cohort.vcf.gz
```

Il file risultante `unrelated_your_cohort.vcf.gz` contiene esclusivamente i campioni non imparentati e può essere utilizzato nelle analisi successive.

In questo modo si ottiene un dataset contenente esclusivamente individui non imparentati, da utilizzare nelle analisi successive. È importante sottolineare che la rimozione degli individui imparentati viene effettuata a partire dal file originale `your_cohort.vcf.gz`, poiché l'intera procedura fa sempre riferimento a questa coorte di partenza. Nelle sezioni successive, infatti, continueremo a utilizzare il file iniziale `your_cohort.vcf.gz` (supponendo che in esso non ci siano individui imparentati) e non il file derivato `unrelated_your_cohort.vcf.gz`. Quest'ultimo dovrà infatti essere impiegato, al posto di `your_cohort.vcf.gz`, solo nel caso in cui siano stati effettivamente individuati individui con relazioni di parentela all'interno della coorte.

---

## 5 Unione delle Coorti

Una volta che entrambi i file VCF sono stati normalizzati, è possibile individuare le varianti comuni. Le coorti verranno indicate come:

```
/path/to/ITvarGM.vcf.gz
/path/to/noCHR_newID_your_cohort.vcf.gz
```

### 5.1 Intersezione delle varianti comuni

```bash
bcftools isec -n=2 -w1 \
  /path/to/ITvarGM.vcf.gz \
  /path/to/noCHR_newID_your_cohort.vcf.gz \
  -Oz | bcftools query -f '%ID\n' \
  > /path/to/common_ids.txt
```

Così facendo è possibile selezionare, tramite la colonna `ID`, solo le varianti comuni ad entrambe le coorti, quindi ci si aspetta al più 14832 varianti.

Si possono ora estrarre solo le varianti comuni da ciascun file:

```bash
bcftools view --include 'ID=@/path/to/common_ids.txt' \
  /path/to/ITvarGM.vcf.gz \
  -Oz -o /path/to/common_var_ITvarGM.vcf.gz
```

```bash
bcftools view --include 'ID=@/path/to/common_ids.txt' \
  /path/to/noCHR_newID_your_cohort.vcf.gz \
  -Oz -o /path/to/common_var_your_cohort.vcf.gz
```

Infine, si possono unire le due coorti:

```bash
bcftools merge --threads 64 \
  /path/to/common_var_ITvarGM.vcf.gz \
  /path/to/common_var_your_cohort.vcf.gz \
  -Oz -o /path/to/commonVar_ITvarGM_yourCohort.vcf.gz
```

### 5.2 Intersezione e unione delle coorti con PLINK 1.9 (WGS e dataset di grandi dimensioni)

Nel caso di dataset di grandi dimensioni, come quelli derivanti da sequenziamento dell'intero esoma (WES) o dell'intero genoma (WGS), l'integrazione di file VCF basata esclusivamente sulle varianti comuni può risultare estremamente onerosa in termini di risorse computazionali se effettuata tramite `bcftools`. Per ottimizzare le prestazioni, questa guida suggerisce l'impiego di PLINK 1.9 o PLINK 2.0, strumenti in grado di operare con elevata efficienza su formati binari (`.bed/.bim/.fam`). Per adottare tale approccio si ricorda, innanzitutto, che è necessario utilizzare file VCF le cui varianti multialleliche siano state preventivamente splittate, in quanto PLINK 1.9 gestisce correttamente solo varianti bialleliche. Parallelamente, occorre considerare che la conversione in formato binario preserva esclusivamente l'informazione del genotipo, comportando la perdita della quasi totalità dei metadati e dei tag INFO presenti nel VCF originale. Nonostante queste limitazioni, i file binari di PLINK 1.9 risultano estremamente vantaggiosi per la loro scalabilità in analisi che non richiedono informazioni di alta precisione sui singoli alleli, come la *Principal Component Analysis* (PCA), obiettivo del presente studio, o il calcolo delle frequenze alleliche.

#### 5.2.1 Conversione dei VCF in formato PLINK

Si parte dai VCF `ITvarGM.vcf.gz` e `newID_your_cohort.vcf.gz` che hanno la colonna `ID` modificata come `CHROM:POS:REF:ALT`. Tali file VCF vengono convertiti in formato binario PLINK.

```bash
plink \
  --vcf /path/to/ITvarGM.vcf.gz \
  --double-id \
  --make-bed \
  --out /path/to/plink/ITvarGM
```

```bash
plink \
  --vcf /path/to/newID_your_cohort.vcf.gz \
  --double-id \
  --make-bed \
  --allow-extra-chr \  # Se necessario
  --out /path/to/plink/newID_your_cohort
```

Le varianti comuni vengono individuate come intersezione tra gli ID presenti nei file `.bim` delle due coorti.

```bash
cut -f2 ITvarGM.bim | sort > ITvarGM.vars
cut -f2 newID_your_cohort.bim | sort > newID_your_cohort.vars

comm -12 ITvarGM.vars newID_your_cohort.vars > common.vars
```

Il file `common.vars` contiene l'elenco delle varianti condivise tra le due coorti, basato su `CHROM:POS:REF:ALT`. Le due coorti vengono filtrate mantenendo esclusivamente le varianti comuni.

```bash
plink \
  --bfile /path/to/plink/ITvarGM \
  --extract common.vars \
  --make-bed \
  --out /path/to/plink/ITvarGM_common
```

```bash
plink \
  --bfile /path/to/plink/newID_your_cohort \
  --extract common.vars \
  --make-bed \
  --allow-extra-chr \  # Se necessario
  --out /path/to/plink/newID_your_cohort_common
```

Infine, le due coorti filtrate vengono unite tramite PLINK.

```bash
plink \
  --bfile /path/to/plink/ITvarGM_common \
  --bmerge /path/to/plink/newID_your_cohort_common \
  --make-bed \
  --out /path/to/plink/commonVar_ITvarGM_yourCohort
```

Il file risultante contiene esclusivamente le varianti comuni tra le due coorti.

---

## 6 Esecuzione della PCA con PLINK

### PLINK v1.9

Una volta ottenuto il file VCF finale unificato (`commonVar_ITvarGM_yourCohort.vcf.gz`), si può performare la PCA:

```bash
plink --vcf /path/to/commonVar_ITvarGM_yourCohort.vcf.gz \
      --pca --double-id --out pca_commonVar_ITvarGM_yourCohort
```

Si noti che se si è effettuato il merging dei file di partenza utilizzando PLINK 1.9 come mostrato in Sezione 5.2, il file di input di PLINK sarà il seguente:

```bash
plink --bfile /path/to/commonVar_ITvarGM_yourCohort \
      --pca --double-id --out pca_commonVar_ITvarGM_yourCohort
```

**Opzioni principali:**

- `--vcf`: specifica il file di input;
- `--pca`: esegue la PCA;
- `--double-id`: mantiene Family ID e Sample ID identici;
- `--allow-extra-chr`: permette di mantenere i cromosomi identificati da codici;
- `--out`: prefisso dei file di output (`.eigenvec`, `.eigenval`, `.log`).

### PLINK v2

```bash
plink2 --vcf /path/to/commonVar_ITvarGM_yourCohort.vcf.gz \
       --make-pgen --out /path/to/pca/commonVar_ITvarGM_yourCohort
```

Poi:

```bash
plink2 --pfile /path/to/pca/commonVar_ITvarGM_yourCohort \
       --freq counts \
       --pca allele-wts vcols=chrom,ref,alt \
       --out /path/to/pca/pca_commonVar_ITvarGM_yourCohort
```

**Opzioni principali:**

- `--vcf`: specifica il file di input in formato VCF (può essere compresso con `.gz`);
- `--make-pgen`: converte il file VCF in formato binario PLINK 2 (`.pgen`, `.pvar`, `.psam`), necessario per le analisi successive;
- `--pfile`: indica il prefisso del file in formato PLINK 2 precedentemente generato (`.pgen/.pvar/.psam`);
- `--freq counts`: calcola le frequenze alleliche e genotipiche per ciascuna variante, includendo il conteggio degli alleli osservati;
- `--pca allele-wts`: esegue l'analisi delle componenti principali (PCA) utilizzando i pesi allelici per il calcolo delle varianze;
- `--allow-extra-chr`: permette di mantenere i cromosomi identificati da codici;
- `vcols=chrom,ref,alt`: specifica le colonne da includere nel file di output della PCA (cromosoma, allele di riferimento, allele alternativo);
- `--out`: definisce il prefisso per i file di output generati (`.eigenvec`, `.eigenval`, `.log`).

### 6.1 Identificazione e Marcatura degli Outlier

Dopo aver eseguito la PCA, un passaggio fondamentale è l'identificazione degli outlier. Questi campioni possono rappresentare individui con diversa origine ancestrale, contaminazioni del campione o artefatti tecnici. Rimuoverli è importante perché possono distorcere le componenti principali e compromettere le analisi successive.

Per identificare outlier multidimensionali è possibile utilizzare la **distanza di Mahalanobis**. Questa metrica misura la distanza di ciascuna osservazione dal centro della distribuzione dei dati (cioè il vettore delle medie), tenendo conto della struttura di covarianza tra le variabili. In questo modo è possibile rilevare outlier considerando contemporaneamente più componenti principali (ad esempio le prime 10 PC), fornendo un criterio più robusto e affidabile rispetto agli approcci univariati.

### 6.2 Implementazione in R

Il seguente script R può essere utilizzato per identificare gli outlier a partire dal file `.eigenvec` generato da PLINK. Lo script esegue i seguenti passaggi:

1. Caricare il file degli autovettori outcome di PLINK (`.eigenvec`).
2. Calcolare la distanza di Mahalanobis per ciascun campione utilizzando le prime 10 componenti principali (PC). *(Si consiglia di utilizzare le prime 10 PC, perché sono sufficienti a spiegare il 90% della varianza ed inoltre sono di default per PLINK).*
3. Impostare la soglia basata sulla distribuzione del chi-quadro, specificando quantile e gradi di libertà (numero di componenti principali). In questo caso viene utilizzato il quantile 0.999.
4. Segnalare come outlier tutti i campioni che superano la soglia.
5. Generare un grafico PC1 vs PC2 con gli outlier evidenziati.
6. Creare un file di testo (`outliers_to_remove.txt`) contenente gli ID dei campioni da rimuovere.

**Prerequisiti in R**

Assicurarsi di avere installate le librerie `MASS`, `ggplot2` e `readxl`:

```r
install.packages("MASS")
install.packages("ggplot2")
install.packages("readxl")
```

**Codice R per l'Identificazione degli Outlier e la Visualizzazione delle Macroaree**

```r
# Carica le librerie necessarie
library(MASS)
library(ggplot2)
library(readxl)

# ===============================
# === 1. Carica i dati PCA ===
# ===============================
eigenvectors_path <- "pca_commonVar_ITvarGM_yourCohort.eigenvec" # <-- MODIFICARE CON IL PROPRIO PERCORSO
eigenvectors <- read.table(eigenvectors_path, header = FALSE)
# Nota: Plink non scrive un'intestazione, quindi deve essere creata manualmente
colnames(eigenvectors) <- c("FID", "ID", paste0("PC", 1:(ncol(eigenvectors)-2)))

# ===============================
# === 2. Analisi degli Outlier ===
# ===============================
pcs_to_use <- 10
pcs <- as.matrix(eigenvectors[, paste0("PC", 1:pcs_to_use)])

center <- colMeans(pcs)
covmat <- cov(pcs)
mahal <- mahalanobis(pcs, center, covmat)
threshold <- qchisq(0.999, df = pcs_to_use)
eigenvectors$is_outlier <- mahal > threshold

cat("Numero di outlier rilevati:", sum(eigenvectors$is_outlier), "\n")

# Grafico PC1 vs PC2 con outlier evidenziati
ggplot(eigenvectors, aes(x = PC1, y = PC2, color = is_outlier)) +
  geom_point(alpha = 0.7) +
  scale_color_manual(values = c("FALSE" = "black", "TRUE" = "red"), name = "Outlier?") +
  theme_minimal() +
  labs(title = "Rilevamento degli Outlier con Distanza di Mahalanobis",
       subtitle = paste(sum(eigenvectors$is_outlier), "outlier rilevati"),
       x = "Componente Principale 1 (PC1)",
       y = "Componente Principale 2 (PC2)") +
  coord_fixed()

# Esporta la lista degli outlier da rimuovere per PLINK
outliers_to_remove <- eigenvectors[eigenvectors$is_outlier, c("FID", "ID")]
output_file <- "outliers_to_remove.txt"
write.table(outliers_to_remove,
            file = output_file,
            sep = "\t",
            row.names = FALSE,
            col.names = FALSE,
            quote = FALSE)
cat("File '", output_file, "' creato con", nrow(outliers_to_remove), "campioni da rimuovere.\n")

# ===============================
# === 3. Aggiunta delle Macroaree ===
# ===============================
# Il file Excel deve contenere almeno due colonne:
# - 'ID': con gli ID dei campioni (uguali a quelli nel file .eigenvec)
# - 'MACROAREA': con la macroarea geografica di ciascun campione,
#   ad esempio: NORD, CENTRO, SUD, SARDEGNA
labels_path <- "path/to/covariate_file.xlsx" # <-- MODIFICARE CON IL PROPRIO FILE
labels <- read_excel(labels_path)

# Unisci le labels ai dati PCA
eigenvectors_merged <- merge(eigenvectors, labels, by = "ID", all.x = TRUE)

# Definisci una palette di colori personalizzata
custom_colors <- c('#1f78b4', '#ff7f00', '#d16ba5', 'purple4')

# Crea il grafico PCA colorato per Macroarea
pc_plot <- ggplot(eigenvectors_merged, aes(PC1, PC2, color = MACROAREA)) +
  geom_point(size = 1, alpha = 0.7) +
  scale_colour_manual(values = custom_colors, na.value = "grey70") +
  coord_equal() +
  theme_light() +
  theme(aspect.ratio = 1) +
  labs(title = "Distribuzione PCA per Macroarea",
       x = "Componente Principale 1 (PC1)",
       y = "Componente Principale 2 (PC2)",
       color = "Macroarea")

# Visualizza il grafico
print(pc_plot)
```

**Descrizione del file labels**

Si osservi che stiamo assumendo che si abbia il file delle covariate per tutti gli ID del case study. Nel caso non si disponesse dell'ID di una particolare coorte, si consiglia di mettere come labels della *MACROAREA* il nome della coorte. Il file `covariate_file.xlsx` deve contenere almeno due colonne:

- **ID**: identificativi dei campioni, corrispondenti alla colonna `ID` del file `.eigenvec`.
- **MACROAREA**: macroarea geografica di appartenenza di ciascun individuo. Nel caso specifico, le categorie previste sono: `NORD`, `CENTRO`, `SUD`, `SARDEGNA`.

Un esempio semplificato del file Excel è mostrato di seguito:

| ID     | MACROAREA |
|--------|-----------|
| ID_1   | NORD      |
| ID_34  | CENTRO    |
| ID_78  | SUD       |
| ID_102 | SARDEGNA  |
| ...    | ...       |

---

## 7 Suddivisione del VCF per categorie di campioni (Trio)

Prima di procedere all'annotazione del VCF prodotto, qualora la coorte in esame sia composta da trii (genitori e probandi), è necessario suddividere il file VCF originale (`your_cohort.vcf.gz`) in due file distinti prima di procedere con l'annotazione delle frequenze alleliche, come già accennato nella Sezione 4.

Avendo a disposizione un file di testo con gli ID dei genitori (`parents.txt`) e uno con gli ID dei probandi (`probands.txt`), è possibile utilizzare `bcftools` per generare separatamente i due VCF. Successivamente, si potrà procedere all'annotazione come descritto nella Sezione 8.

Partendo dal file `your_cohort.vcf.gz`, l'obiettivo è ottenere i file `your_cohort_probands.vcf.gz` e `your_cohort_parents.vcf.gz`. A tale scopo, eseguiremo due comandi distinti per filtrare i campioni desiderati.

```bash
# Creazione del VCF contenente esclusivamente i probandi
bcftools view --force-samples -S /path/to/probands.txt \
  /path/to/your_cohort.vcf.gz \
  -Oz -o /path/to/your_cohort_probands.vcf.gz
```

```bash
# Creazione del VCF contenente esclusivamente i genitori
bcftools view --force-samples -S /path/to/parents.txt \
  /path/to/your_cohort.vcf.gz \
  -Oz -o /path/to/your_cohort_parents.vcf.gz
```

Una volta generati i due VCF separati, sarà possibile riprendere il normale flusso della pipeline.

---

## 8 Marcatura degli Outlier

L'obiettivo dei seguenti paragrafi è quello di calcolare e integrare nel file VCF `your_cohort.vcf.gz` le seguenti informazioni:

- la frequenza allelica delle varianti, distinta tra campioni classificati come outlier e soggetti non outlier (italiani secondo la classificazione di Mahalanobis);
- la frequenza genotipica e il numero totale di alleli osservati, la minor allele frequency (MAF) ecc;
- la frequenza allelica interna alla coorte;
- la eventuale rimozione degli outliers per riperformare PCA ed evidenziare la stratificazione della popolazione nella coorte `commonVar_ITvarGM_yourCohort.vcf.gz`.

Per queste operazioni si utilizza il tool `bcftools +fill-tags`, che consente di annotare in modo efficiente il file VCF.

### 8.1 Annotazione del file VCF con bcftools

Il comando seguente aggiunge diverse statistiche aggregate nella sezione `INFO` di ciascuna variante:

```bash
bcftools +fill-tags /path/to/your_cohort.vcf.gz \
  -Oz -o /path/to/INFOtags_your_cohort.vcf.gz \
  -- -t AN,AC,AC_Hemi,AC_Hom,AC_Het,AF,MAF,NS
```

Dove i campi che vengono aggiunti nel campo `INFO` sono i seguenti:

- **AN**: Numero totale di alleli chiamati.
- **AC**: Conteggio degli alleli alternativi.
- **AC_Hemi**: Numero di campioni emizigoti per l'allele alternativo (solo per cromosomi sessuali).
- **AC_Hom**: Numero di omozigoti alternativi.
- **AC_Het**: Numero di eterozigoti.
- **AF**: Frequenza allelica dell'allele alternativo.
- **MAF**: Frequenza dell'allele meno comune (Minor allele frequency).
- **NS**: Numero di campioni con genotipo valido.

Si consiglia di inserire le statistiche elencate precedentemente (si presenteranno come colonne nel campo `INFO` del VCF in esame); queste ed altre statistiche che possono essere inserite nel VCF `your_cohort.vcf.gz` possono essere trovate nella pagina git di samtools.

**Analisi dei tag con `bcftools +fill-tags`**

Le frequenze **assolute** (es. `AC_Hom`, `AC_Het`) rappresentano conteggi, mentre le frequenze **relative** (es. `AF`, `MAF`) rappresentano proporzioni rispetto al numero totale di alleli o individui.

```
AN  = 2 × N_diploidi + 1 × N_emizigoti
AC  = 2 × N_omozigoti_alt + 1 × N_eterozigoti
AC_Hom  = N_genotipi con 1/1
AC_Het  = N_genotipi con 0/1 o 1/0
AC_Hemi = N_genotipi emizigoti con allele alt.
AF  = AC / AN
MAF = min(AF, 1 - AF)
NS  = N_campioni con genotipo non missing
```

#### 8.1.1 Visualizzazione dei campi INFO

Si può, inoltre, visualizzare il contenuto delle nuove etichette con `bcftools query`:

```bash
{
  echo -e "CHROM\tPOS\tREF\tALT\tAF\tMAF\tAN\tAC\tAC_Hom\tNS";
  bcftools query -f '%CHROM\t%POS\t%REF\t%ALT\t%INFO/AF\t%INFO/MAF\t%INFO/AN\t%INFO/AC\t%INFO/AC_Hom\t%INFO/NS\n' \
    /path/to/INFO_your_cohort.vcf.gz
} | head -n 3
```

**Esempio di output:**

| CHROM | POS     | REF | ALT | AF     | MAF    | AN   | AC | AC_Hom | NS  |
|-------|---------|-----|-----|--------|--------|------|----|--------|-----|
| chrN  | XXXXXXX | A   | G   | 0.XXXX | 0.XXXX | XXXX | XX | X      | XXX |
| chrN  | XXXXXXX | T   | C   | 0.XXXX | 0.XXXX | XXXX | XX | X      | XXX |
| chrN  | XXXXXXX | G   | A   | 0.XXXX | 0.XXXX | XXXX | XX | X      | XXX |

Dove N ∈ {1, 2, ..22, XX, XY} indica un cromosoma generico ed XXX indica un numero intero o decimale.

### 8.2 Calcolo della frequenza allelica per italiani e outlier

Di seguito viene mostrato come, a partire dal file `outliers_to_remove.txt` (prodotto nella Sezione 6.2) e da un file `all_samples.txt` contenente gli ID di tutti i campioni della coorte, sia possibile aggiungere al VCF le colonne corrispondenti alle frequenze alleliche dei due gruppi, `outliers` e `pca_ita`.

I passaggi principali sono i seguenti:

- estrarre dal file `your_cohort.vcf.gz` la lista completa degli ID dei campioni, salvandola in `all_samples.txt`;
- ripulire il file `outliers_to_remove.txt` da eventuali caratteri speciali (ad esempio `\r` provenienti da sistemi Windows);
- ottenere la lista dei campioni non outlier (gruppo `pca_ita`).

```bash
# Estrae l'elenco di tutti i campioni dal VCF
bcftools query -l your_cohort.vcf.gz > all_samples.txt

# Rimuove caratteri speciali (es. '\r' di Windows)
sed -i 's/\r//g' outliers_to_remove.txt

# Crea la lista 'pca_ita.txt' escludendo (-v) gli outlier
grep -v -F -f outliers_to_remove.txt all_samples.txt > pca_ita.txt
```

Per calcolare la frequenza allelica dei due gruppi individuati (`outliers` e `pca_ita`) è necessario fornire a `bcftools` un file di testo senza intestazione, composto da due colonne; la prima colonna contiene gli ID dei campioni e la seconda indica il gruppo di appartenenza.

```bash
# Assegna il gruppo 'outliers'
awk '{print $1 "\toutliers"}' outliers_to_remove.txt > groups.txt

# Assegna il gruppo 'pca_ita' e appende al file
awk '{print $1 "\tpca_ita"}' pca_ita.txt >> groups.txt
```

Il file `groups.txt` dovrà essere come segue:

```
ID_1      outliers
ID_2      outliers
...
ID_N-1    pca_ita
ID_N      pca_ita
```

Dove N è il numero totale dei samples del file `your_cohort.vcf.gz`.

Una volta creato il file di mappatura `groups.txt`, è possibile calcolare la frequenza allelica di ciascuna variante per i due gruppi utilizzando il plugin `+fill-tags` di `bcftools`:

```bash
bcftools +fill-tags /path/to/INFOtags_your_cohort.vcf.gz \
  -Oz -o /path/to/groups_INFOtags_your_cohort.vcf.gz \
  -- -S /path/to/groups.txt
```

Il comando genera un file denominato `groups_INFOtags_your_cohort.vcf.gz`, che conterrà le nuove colonne `AF_pca_ita` e `AF_outliers`, corrispondenti alle frequenze alleliche calcolate rispettivamente per i campioni italiani e per gli outlier.

**Calcolo della frequenza allelica per sesso con `bcftools +fill-tags`**

Per stimare la frequenza allelica (AF) separatamente per i campioni maschili e femminili, è possibile utilizzare il plugin `fill-tags` di `bcftools`. Questo approccio consente di calcolare le frequenze in base a gruppi di campioni definiti in un file esterno.

**1. Creazione del file dei gruppi (`sex_groups.txt`)**

Il file deve contenere due colonne senza intestazione (tab-separated): la prima colonna indica il nome del campione, la seconda il gruppo di appartenenza (in questo caso, il sesso).

```
ID_1      male
ID_2      male
...
ID_N-1    female
ID_N      female
```

Salvare il file come `sex_groups.txt`.

**2. Calcolo delle frequenze alleliche per sesso**

Il comando seguente utilizza il plugin `fill-tags` per aggiungere al file VCF i campi `AF_male` e `AF_female`, corrispondenti alle frequenze alleliche nei due gruppi.

```bash
bcftools +fill-tags /path/to/groups_INFOtags_your_cohort.vcf.gz \
  -Oz -o /path/to/sex_groups_INFOtags_your_cohort.vcf.gz \
  -- -S /path/to/sex_groups.txt
```

- `-t AF` specifica che si vuole calcolare solo la frequenza allelica.
- `-S sex_groups.txt` indica il file con i campioni suddivisi per sesso.
- `-O z` produce un VCF compresso in formato `.vcf.gz`.

Il file di output conterrà nuovi tag INFO del tipo:

```
##INFO=<ID=AF_male,Number=A,Type=Float,Description="Allele frequency in group male">
##INFO=<ID=AF_female,Number=A,Type=Float,Description="Allele frequency in group female">
```

> **Nota:** Si noti che questo metodo per aggiungere la frequenza allelica delle diverse categorie quali il sesso, la provenienza ma anche le macrocategorie fenotipiche, può essere reiterato più volte oppure si può generare un file `.txt` come mostrato in Sezione 8.3, che contiene per ogni ID del campione, una colonna con tutti i macrogruppi a cui appartiene.

### 8.3 Annotazione completa in un unico passaggio

Per semplificare l'analisi, è possibile combinare tutte le annotazioni illustrate in precedenza in un unico comando `bcftools +fill-tags`. Questo approccio consente di aggiungere simultaneamente:

- le statistiche aggregate della coorte (AN, AC, AF, MAF, ecc.);
- le frequenze alleliche per i gruppi di interesse (es. `pca_ita`, `outliers`);
- le frequenze alleliche per sesso (es. `male`, `female`).

Per farlo, è necessario creare un unico file di mappatura dei campioni, denominato `outliers_groups.txt`, contenente due colonne senza intestazione, separate da tabulazione:

```
ID_1    pca_ita,female
ID_2    pca_ita,male,cardio
ID_3    pca_ita,neuro,female
ID_4    pca_ita,cancer
ID_5    pca_ita,not_affected,male
ID_6    outliers,male
ID_7    pca_ita,cardio
ID_8    female,outliers
```

A partire da questo file è possibile generare automaticamente un file esteso, denominato `outliers_mixedgroups.txt`, in cui vengono aggiunti gruppi composti (ad esempio `ita_cardio`, `ita_cardio_male`, `ita_female`, ecc.) utili per calcolare frequenze alleliche su sottogruppi specifici della coorte.

**Generazione automatica del file dei gruppi misti in R**

```r
# === 1. Leggi il file di input ===
# Il file 'outliers_groups.txt' deve avere due colonne: ID e gruppi separati da tab.
df <- read.table("outliers_groups.txt",
                 sep = "\t", header = FALSE, stringsAsFactors = FALSE)
colnames(df) <- c("ID", "groups")

# === 2. Funzione per generare i gruppi composti ===
generate_groups <- function(group_str) {
  groups <- unlist(strsplit(gsub(" ", "", group_str), ",")) # rimuove spazi
  new_groups <- c()
  has <- function(x) x %in% groups

  # --- Regole per generare nuovi gruppi ---
  if (has("pca_ita") && has("male"))   new_groups <- c(new_groups, "ita_male")
  if (has("pca_ita") && has("female")) new_groups <- c(new_groups, "ita_female")

  if (has("pca_ita") && has("cardio")) {
    new_groups <- c(new_groups, "ita_cardio")
    if (has("male"))   new_groups <- c(new_groups, "ita_cardio_male")
    if (has("female")) new_groups <- c(new_groups, "ita_cardio_female")
  }
  if (has("pca_ita") && has("neuro")) {
    new_groups <- c(new_groups, "ita_neuro")
    if (has("male"))   new_groups <- c(new_groups, "ita_neuro_male")
    if (has("female")) new_groups <- c(new_groups, "ita_neuro_female")
  }
  if (has("pca_ita") && has("cancer")) {
    new_groups <- c(new_groups, "ita_cancer")
    if (has("male"))   new_groups <- c(new_groups, "ita_cancer_male")
    if (has("female")) new_groups <- c(new_groups, "ita_cancer_female")
  }
  if (has("pca_ita") && has("not_affected")) {
    new_groups <- c(new_groups, "ita_not_affected")
    if (has("male"))   new_groups <- c(new_groups, "ita_not_affected_male")
    if (has("female")) new_groups <- c(new_groups, "ita_not_affected_female")
  }

  paste(unique(c(groups, new_groups)), collapse = ",")
}

# === 3. Applica la funzione a ogni riga ===
df$groups_new <- sapply(df$groups, generate_groups)

# === 4. Salva il file di output ===
write.table(df[, c("ID", "groups_new")],
            file = "outliers_mixedgroups.txt",
            sep = "\t", quote = FALSE, row.names = FALSE, col.names = FALSE)
```

Il file risultante `outliers_mixedgroups.txt` potrà poi essere utilizzato come input diretto per `bcftools +fill-tags`, consentendo il calcolo simultaneo delle frequenze alleliche per tutti i gruppi, inclusi quelli composti (es. `ita_cardio_female`, `ita_neuro_male`, ecc.).

Il file di tabulazione finale chiamato `outliers_mixedgroups.txt`, sarà come quello che segue:

```
ID_1    pca_ita,female,ita_female
ID_2    pca_ita,male,cardio,ita_cardio,ita_cardio_male,ita_male
ID_3    pca_ita,neuro,female,ita_neuro,ita_neuro_female,ita_female
ID_4    pca_ita,cancer,ita_cancer
ID_5    pca_ita,not_affected,male,ita_not_affected,ita_not_affected_male,ita_male
ID_6    outliers,male
ID_7    pca_ita,cardio,ita_cardio
ID_8    female,outliers
```

In questo file, ogni campione è associato a più gruppi (separati da virgola). `bcftools` calcolerà automaticamente le statistiche per tutte le combinazioni presenti; inoltre il plugin di `bcftools` gestisce anche i gruppi missing.

**Annotazione completa con `+fill-tags`**

```bash
bcftools +fill-tags /path/to/your_cohort.vcf.gz \
  -Oz -o /path/to/groups_INFOtags_your_cohort.vcf.gz \
  -- -t AN,AC,AC_Hemi,AC_Hom,AC_Het,AF,MAF,NS \
     -S /path/to/outliers_mixedgroups.txt
```

In questo modo verranno calcolati:

- i tag generali di qualità e frequenza allelica per l'intera coorte;
- le frequenze per ciascun gruppo (`pca_ita`, `outliers`);
- le frequenze per sesso (`male`, `female`);
- le frequenze per i gruppi composti (`ita_cardio`, `ita_cardio_male`, `ita_neuro_female`, ecc.).

Il file di output `groups_INFOtags_your_cohort.vcf.gz` conterrà quindi, oltre ai tag standard, anche campi aggiuntivi come:

```
##INFO=<ID=AF_pca_ita,Number=A,Type=Float,Description="Allele frequency in group pca_ita">
##INFO=<ID=AF_outliers,Number=A,Type=Float,Description="Allele frequency in group outliers">
##INFO=<ID=AF_male,Number=A,Type=Float,Description="Allele frequency in group male">
##INFO=<ID=AF_female,Number=A,Type=Float,Description="Allele frequency in group female">
...
```

Dopo l'annotazione con `bcftools +fill-tags`, è possibile ispezionare i valori dei nuovi campi calcolati per i vari gruppi (es. `pca_ita`, `male`, `female`, `ita_cardio`) utilizzando `bcftools query`. Nel seguente esempio vengono estratti alcuni dei tag principali sia generali che specifici per gruppo:

```bash
{
  echo -e "CHROM\tPOS\tREF\tALT\tAF\tAF_pca_ita\tAF_male\tAF_female\tAF_ita_cardio\tAN\tAC_Het";
  bcftools query -f '%CHROM\t%POS\t%REF\t%ALT\t%INFO/AF\t%INFO/AF_pca_ita\t%INFO/AF_male\t%INFO/AF_female\t%INFO/AF_ita_cardio\t%INFO/AN\t%INFO/AC_Het\n' \
    groups_INFOtags_your_cohort.vcf.gz
} | head -n 11
```

**Esempio di output:**

| CHROM | POS     | REF | ALT | AF     | AF_pca_ita | AF_male | AF_female | AF_ita_cardio | AN   | AC_Het |
|-------|---------|-----|-----|--------|------------|---------|-----------|---------------|------|--------|
| chrN  | XXXXXXX | A   | G   | 0.XXXX | 0.XXXX     | 0.XXXX  | 0.XXXX    | 0.XXXX        | XXXX | XXX    |
| chrN  | XXXXXXX | T   | C   | 0.XXXX | 0.XXXX     | 0.XXXX  | 0.XXXX    | 0.XXXX        | XXXX | XXX    |
| chrN  | XXXXXXX | G   | A   | 0.XXXX | 0.XXXX     | 0.XXXX  | 0.XXXX    | 0.XXXX        | XXXX | XXX    |
| chrN  | XXXXXXX | C   | T   | 0.XXXX | 0.XXXX     | 0.XXXX  | 0.XXXX    | 0.XXXX        | XXXX | XXX    |
| chrN  | XXXXXXX | A   | C   | 0.XXXX | 0.XXXX     | 0.XXXX  | 0.XXXX    | 0.XXXX        | XXXX | XXX    |

Dove N ∈ {1, 2, ..22, XX, XY} indica un cromosoma generico ed XXX indica un numero intero o decimale.

### 8.4 Facoltativo: rimozione degli outliers dalla coorte

Dopo aver ottenuto la lista degli outlier da escludere, contenuta nel file `outliers_to_remove.txt`, è possibile rimuovere gli outlier presenti nella lista dal file delle coorti intersecate `commonVar_ITvarGM_yourCohort.vcf.gz`. Questa operazione consente di ripetere successivamente l'analisi PCA per visualizzare in modo più chiaro i cluster e/o la stratificazione delle popolazioni.

```bash
# Facoltativa rimozione degli outliers
bcftools view --force-samples -S ^/path/to/outliers_to_remove.txt \
  /path/to/commonVar_ITvarGM_yourCohort.vcf.gz \
  -Oz -o /path/to/no_out_commonVar_ITvarGM_yourCohort.vcf.gz
```

Una volta generato il file `no_out_commonVar_ITvarGM_yourCohort.vcf.gz`, è possibile rieseguire la PCA a partire dalla Sezione 6 e riprodurre lo scatter plot per verificare la distribuzione delle popolazioni dopo la rimozione degli outlier.

---

> **Documento riservato — Non condividere senza autorizzazione.**
