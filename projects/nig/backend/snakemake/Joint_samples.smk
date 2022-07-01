include: "Basic.smk"

# Reference genome
refg=config["GENOME"]["hg38"]
gvcfs = call_json()
print('****Samples yet to be processed*****')
print(gvcfs)

# Check if GenomicsDBImport to run on new samples
update = config["UPDATE"]["GDBI"]
print('Update is')
print(update)

GDBI = '--genomicsdb-workspace-path -L hg38_resources/wgs_calling_regions.hg38.interval_list'
if update:
    GDBI = '--genomicsdb-update-workspace-path'

rule all:
        input: "/data/output/gatk_filtered_multisamples/multisample_filtered_vars.vcf",
            "all_samples.vcf.log"

rule GenomicsDBImport:
    input:
        inter=config["IFILES"]["inter"]
    output:
        "all_samples.vcf.log"
    params:
        p1 = Mult_Params( '-V' , gvcfs ),
        p2 = '--reader-threads 48',
        p3 = GDBI
    shell:
        '''gatk --java-options "-Xmx4g -Xms4g -DGATK_STACKTRACE_ON_USER_EXCEPTION=true" GenomicsDBImport \
        -R {refg} {params.p1} {params.p2} {params.p3} /data/output/gatk_db > all_samples.vcf.log 2>&1 '''

rule GenotypeGVCFs:
    input:
       i1=rules.GenomicsDBImport.log
    output:
        "/data/output/gatk_genotype_gvcf/multisample_vars.vcf.gz"
    log:
        "/data/output/gatk_genotype_gvcf/multisample_vars.vcf.log"
    benchmark:
       "/data/output/gatk_genotype_gvcf/multisample_vars.vcf.benchmark"
    params:
        p1="-G StandardAnnotation -G StandardHCAnnotation -G AS_StandardAnnotation ",
        p2="--filter-expression 'QD < 2.0 || FS > 30.0 || SOR > 3.0 || MQ < 40.0 || MQRankSum < -3.0 || \
        ReadPosRankSum < -3.0' ",
        p3='/data/output/gatk_db'
    shell:
        '''gatk --java-options "-Xmx10G -Xms2G -XX:ParallelGCThreads=2" GenotypeGVCFs -R {refg} -V gendb://{params.p3} -O {output} {params.p1} --tmp-dir tmp > {log} 2>&1 '''

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
