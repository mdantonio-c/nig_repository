# Import pymodules
import glob
import pandas as pd
import json
from pathlib import Path

OUTPUT_ROOT = "/data/output"

# Function for passing multiple parameters with same arguement to Gatk tools
def Mult_Params(patern='Dummy', flist=['a','b']):
    return ' '.join( [patern + ' ' + str(fname) for fname in flist] )

# Function to get samples to be processed by GenomicsDBImport
update = config["UPDATE"]["GDBI"]
def call_json(update=update):
    if not update:
        # get all the vcf
        gvcf = glob.glob( OUTPUT_ROOT + '/*/*/*/gatk_gvcf/*g.vcf.gz')
    else:
        # All samples in .csv files
        df = pd.read_csv('fastq.csv')
        sall  = set( df.Sample )

        callset_file = Path ( OUTPUT_ROOT,'gatk_db','callset.json')
        if callset_file.is_file():
            with open(callset_file) as f:
                data = json.load(f)
            f.close()
            # json_normalize is used to create a stacked dataframe from json `data`
            # sold is set of samples already processed
            sold = set( pd.json_normalize(data,record_path=['callsets']).sample_name.values )
            samples_to_joint = [ name for name in sall^sold ]
        else:
            #first run
            samples_to_joint = [ name for name in sall]
        gvcf = []
        for s in samples_to_joint:
            output_path = df[df['Sample'].str.contains(s)]['OutputPath'].values[0]
            gvcf.append(f"{output_path}/gatk_gvcf/{s}_sort_nodup.g.vcf.gz")
    return gvcf
