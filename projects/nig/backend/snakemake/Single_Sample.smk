include: "Basic.smk"

# Here goes the inputs list
df = pd.read_csv('fastq.csv')
# Collect paired and single samples
pair = df[ df.Reverse=='Yes' ] ; sing = df[ ~df.Sample.isin(pair.Sample) ]


# Reference genome
refg = config["GENOME"]["hg38"]

wildcard_constraints:
    Pw = '|'.join([re.escape(x) for x in pair.Sample]),
    Sw = '|'.join([re.escape(x) for x in sing.Sample])

rule all:
	input: expand("{O}/fastqc/{S}_{F}_fastqc.html",zip, O=df.OutputPath, S=df.Sample,F=df.Frag),\
    expand("{O}/gatk_gvcf/{S}_sort_nodup.g.vcf.gz",zip, O=df.OutputPath, S=df.Sample)


rule Fastqc:
    message:
        "Running fastqc tool on input fastq files"
    input:
        "{O}/{S}_{F}.fastq.gz"
    output:
        "{O}/fastqc/{S}_{F}_fastqc.html"
    log:
        "{O}/fastqc/{S}_{F}_fastqc.log"
    benchmark:
        "{O}/fastqc/{S}_{F}_fastqc.benchmark"
    threads:
        config["THREAD"]["fastqc"]
    shell:
        "fastqc -o {wildcards.O}/fastqc -t {threads} -f fastq --extract {input} > {log} 2>&1"

rule Seqtk:
    message:
        "Running `seqtk seq` on input fastq files"
    input:
        rules.Fastqc.input
    output:
        temp("{O}/seqtk/{S}_{F}.converted.gz")
    shell:
        "seqtk seq -Q33 -V {input} | gzip > {output} "

ruleorder: BwaP > BwaS

rule BwaS:
    message:
        "Creating sam files for unpaired samples"
    input:
        i="{O}/seqtk/{Sw}_R1.converted.gz"
    output:
        temp("{O}/bwa/{Sw}.sam")
    log:
        "{O}/bwa/{Sw}.log"
    benchmark:
        "{O}/bwa/{Sw}.benchmark"
    threads:
        config["THREAD"]["bwa"]
    params:
        config["PARAMS"]["bwas"]
    shell:
        "bwa mem -t {threads} {params} {refg} {input.i} 1> {output} 2> {log} "

rule BwaP:
    message:
        "Creating sam files for paired samples"
    input:
        i1 = "{O}/seqtk/{Pw}_R1.converted.gz",
        i2 = "{O}/seqtk/{Pw}_R2.converted.gz"
    output:
        temp("{O}/bwa/{Pw}.sam")
    log:
        "{O}/bwa/{Pw}.log"
    benchmark:
        "{O}/bwa/{Pw}.benchmark"
    threads:
        config["THREAD"]["bwa"]
    params:
        config["PARAMS"]["bwap"]
    shell:
        "seqtk mergepe {input.i1} {input.i2} | bwa mem -p -t {threads} {params} {refg} - 1> {output} 2> {log}"

rule Samblaster:
    message:
        "Doing `samblast` for all samples"
    input:
        "{O}/bwa/{S}.sam"
    output:
        temp("{O}/bwa/{S}_samblaster.sam")
    log:
        "{O}/bwa/{S}_samblaster.log"
    benchmark:
        "{O}/bwa/{S}_samblaster.benchmark"
    threads:
        config["THREAD"]["samtool"]
    shell:
        "samblaster -i {input} -r --ignoreUnmated -o {output} > {log} 2>&1"

rule Samsort:
    message:
        "Doing `samsort` for all samples"
    input:
        "{O}/bwa/{S}_samblaster.sam"
    output:
        temp("{O}/bwa/{S}_sort_nodup.bam")
    log:
        "{O}/bwa/{S}_sort_nodup.sam.log"
    benchmark:
        "{O}/bwa/{S}_sort_nodup.sam.benchmark"
    threads:
        config["THREAD"]["samtool"]
    shell:
        "samtools sort -@ {threads} -m100G {input} -O BAM -o {output} > {log} 2>&1"

rule Samindex:
    input:
        rules.Samsort.output
    output:
        "{O}/bwa/{S}_sort_nodup.bai"
    threads:
        config["THREAD"]["samview"]
    shell:
        "samtools index -@ {threads}  {input} {output}"

rule BaseRecalibrator:
    input:
        bam=rules.Samsort.output,
        bai=rules.Samindex.output,
        inter=config["IFILES"]["inter"]
    output:
        recaldat="{O}/gatk_bsr/{S}_sort_nodup.recaldat"
    log:
        "{O}/gatk_bsr/{S}_sort_nodup.recaldat.log"
    benchmark:
        "{O}/gatk_bsr/{S}_sort_nodup.recaldat.benchmark"
    params:
        jv = config["JAVA"]["brc"],
        p1=Mult_Params('--known-sites',[ config["IFOLDER"]["gatk"]+name for name in config["IFILES"]["dbsnp"] ])
    shell:
        '''gatk {params.jv} BaseRecalibrator --input {input.bam} --output {output} \
        --reference {refg} {params.p1} --use-original-qualities -L {input.inter} > {log} 2>&1'''

rule ApplyBQSR:
    input:
        bam=rules.Samsort.output,
        rec=rules.BaseRecalibrator.output,
        inter=config["IFILES"]["inter"]
    output:
        temp("{O}/gatk_bsr/{S}_sort_nodup.bqsr.bam")
    log:
        "{O}/gatk_bsr/{S}_sort_nodup.bqsr.log"
    benchmark:
        "{O}/gatk_bsr/{S}_sort_nodup.bqsr.benchmark"
    params:
        jv = config["JAVA"]["absq"],
        p1 = Mult_Params( '--static-quantized-quals' , config["PARAMS"]["absq"] ),
        p2 = '--use-original-qualities'
    shell:
        '''gatk {params.jv} ApplyBQSR --input {input.bam} --output {output} --reference {refg} \
        --bqsr {input.rec}  {params.p1} {params.p2} -L {input.inter} > {log} 2>&1'''

rule HaplotypeCaller:
    input:
        bam=rules.ApplyBQSR.output,
        inter=config["IFILES"]["inter"]
    output:
        "{O}/gatk_gvcf/tmp_{S}_sort_nodup.g.vcf.gz"
    log:
        "{O}/gatk_gvcf/{S}_sort_nodup.g.vcf.log"
    benchmark:
        "{O}/gatk_gvcf/tmp_{S}_sort_nodup.g.vcf.benchmark"
    threads:
        config["THREAD"]["hapcal"]
    params:
        jv = config["JAVA"]["hapl"],
        p1 = Mult_Params( '-G' , config["PARAMS"]["hapl_g"] ) ,
        p2 = Mult_Params( '-GQB' , config["PARAMS"]["hapl_gqb"] ) ,
        p3 = '-native-pair-hmm-threads'
    shell:
        '''gatk {params.jv} HaplotypeCaller -R {refg} -I {input.bam} --intervals {input.inter} \
        -O {output} -ERC GVCF {params.p1} {params.p2} {params.p3} {threads}  > {log} 2>&1'''

rule Rename:
    input:
        rules.HaplotypeCaller.output
    output:
        "{O}/gatk_gvcf/{S}_sort_nodup.g.vcf.gz"
    shell:
        '''mv {input} {output}; mv {input}.tbi {output}.tbi'''
