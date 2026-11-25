include: "Basic.smk"

import sys
sys.path.insert(0, workflow.basedir)
from joint_inputs import call_json

# Per study type settings, resolved by launch_joint_analysis (joint_run.yaml)
joint = config["JOINT"]
print('Joint analysis for {} with reference {}'.format(joint["study_type"], joint["reference_id"]))

# Reference genome
refg = joint["fasta"]
# create/update, decided by the task on the existence of the workspace of this type
update = joint["update"]
gvcfs = call_json("joint.csv", Path(joint["workspace"], "callset.json"), update)
print('****Samples yet to be processed*****')
print(gvcfs)

print('Update is')
print(update)

GDBI = '-L ' + joint["intervals"] + ' --genomicsdb-workspace-path '
if update:
    GDBI = '--genomicsdb-update-workspace-path'

rule all:
        input: joint["filtered_dir"] + "/multisample_filtered_vars.vcf",
            "all_samples.vcf.log"

rule GenomicsDBImport:
    input:
        inter=joint["intervals"]
    output:
        "all_samples.vcf.log"
    params:
        p1 = Mult_Params( '-V' , gvcfs ),
        p2 = '--reader-threads {}'.format(joint["reader_threads"]),
        p3 = GDBI,
        p4 = '--batch-size {}'.format(joint["batch_size"]),
        heap = joint["java_heap"],
        ws = joint["workspace"]
    shell:
        '''gatk --java-options "{params.heap} -DGATK_STACKTRACE_ON_USER_EXCEPTION=true" GenomicsDBImport \
        -R {refg} {params.p1} {params.p2} {params.p3} {params.ws} {params.p4} > all_samples.vcf.log 2>&1 '''

rule GenotypeGVCFs:
    input:
       i1=rules.GenomicsDBImport.output
    output:
        joint["genotype_dir"] + "/multisample_vars.vcf.gz"
    log:
        joint["genotype_dir"] + "/multisample_vars.vcf.log"
    benchmark:
       joint["genotype_dir"] + "/multisample_vars.vcf.benchmark"
    params:
        p1=Mult_Params( '-G', joint["annotations"] ) + ' ',
        p2="--filter-expression 'QD < 2.0 || FS > 30.0 || SOR > 3.0 || MQ < 40.0 || MQRankSum < -3.0 || \
        ReadPosRankSum < -3.0' ",
        p3=joint["workspace"],
        heap = joint["java_heap"]
    shell:
        '''gatk --java-options "{params.heap} " GenotypeGVCFs -R {refg} -V gendb://{params.p3} -O {output} {params.p1} > {log} 2>&1 '''

rule VariantFiltration:
    input:
        i1=rules.GenotypeGVCFs.output,
        i2=joint["intervals"]
    output:
        joint["filtered_dir"] + "/multisample_filtered_vars.vcf"
    log:
        joint["filtered_dir"] + "/multisample_filtered_vars.log"
    benchmark:
        joint["filtered_dir"] + "/multisample_filtered_vars.benchmark"
    params:
        p1=config["PARAMS"]["vrfl"]
    shell:
        '''gatk --java-options "-Xms3g" VariantFiltration -V {input.i1} \
        -L {input.i2} --filter-expression {params.p1} --filter-name "HardFiltered" -O {output} > {log} 2>&1'''
