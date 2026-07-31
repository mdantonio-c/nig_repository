import os

include: "Basic.smk"

# Reference genome
refg=config["GENOME"]["hg38"]
gvcfs = call_json()
print('****Samples yet to be processed*****')
print(gvcfs)

if not gvcfs:
    print("No new samples to import. Skipping GenomicsDBImport.")

# Check if GenomicsDBImport to run on new samples
update = config["UPDATE"]["GDBI"]
print('Update is')
print(update)

GDBI = '-L /resources/hg38_resources/wgs_calling_regions.hg38.interval_list --genomicsdb-workspace-path '
if update:
    GDBI = '--genomicsdb-update-workspace-path'

if gvcfs:
    # Force regeneration by removing the stale marker
    if os.path.exists("all_samples.vcf.log"):
        os.remove("all_samples.vcf.log")

rule all:
    input:
        "/data/output/gatk_filtered_multisamples/multisample_filtered_vars.vcf",
        "all_samples.vcf.log" if gvcfs else []

rule GenomicsDBImport:
    input:
        inter=config["IFILES"]["inter"],
        gvcfs=gvcfs
    output:
        "all_samples.vcf.log"
    params:
        p1 = Mult_Params( '-V' , gvcfs ),
        p2 = '--reader-threads 48',
        p3 = GDBI,
	p4 = '--batch-size 50'
    shell:
        '''gatk --java-options "-Xmx88g -Xms10g -DGATK_STACKTRACE_ON_USER_EXCEPTION=true" GenomicsDBImport \
        -R {refg} {params.p1} {params.p2} {params.p3} /data/output/gatk_db {params.p4} 2>&1 | tee {output} && sync && touch {output} '''

rule GenotypeGVCFs:
    input:
       i1="all_samples.vcf.log" if gvcfs else []
    output:
        "/data/output/gatk_genotype_gvcf/multisample_vars.vcf.gz"
    log:
        "/data/output/gatk_genotype_gvcf/multisample_vars.vcf.log"
    benchmark:
       "/data/output/gatk_genotype_gvcf/multisample_vars.vcf.benchmark"
    params:
        p1="-G StandardAnnotation -G AS_StandardAnnotation ",
        p2="--filter-expression 'QD < 2.0 || FS > 30.0 || SOR > 3.0 || MQ < 40.0 || MQRankSum < -3.0 || \
        ReadPosRankSum < -3.0' ",
        p3='/data/output/gatk_db',
        p4=config["IFILES"]["inter"]
    shell:
        '''gatk --java-options "-Xmx88g -Xms10g " GenotypeGVCFs -R {refg} -V gendb://{params.p3} -L {params.p4} -O {output} {params.p1} > {log} 2>&1 '''

rule VariantFiltration:
    input:
        i1=rules.GenotypeGVCFs.output,
        i2=config["IFILES"]["inter"]
    output:
        "/data/output/gatk_filtered_multisamples/multisample_filtered_vars.vcf"
    log:
        "/data/output/gatk_filtered_multisamples/multisample_filtered_vars.log"
    benchmark:
        "/data/output/gatk_filtered_multisamples/multisample_filtered_vars.benchmark"
    params:
        p1=config["PARAMS"]["vrfl"]
    shell:
        '''gatk --java-options "-Xms3g" VariantFiltration -V {input.i1} \
        -L {input.i2} --filter-expression {params.p1} --filter-name "HardFiltered" -O {output} > {log} 2>&1'''
