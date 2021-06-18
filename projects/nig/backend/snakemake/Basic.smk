# Import pymodules
import glob
import pandas as pd
import json

# Function for passing multiple parameters with same arguement to Gatk tools
def Mult_Params(patern='Dummy', flist=['a','b']):
    return ' '.join( [patern + ' ' + str(fname) for fname in flist] )

# Function to get samples to be processed by GenomicsDBImport
update = config["UPDATE"]["GDBI"]
def call_json(update=update):
    if not update:
        gvcf = glob.glob( 'gatk_gvcf/*g.vcf.gz')
    else:
        # All samples in .csv files
        sall  = set( pd.read_csv('fastq.csv').Sample )
        with open('gatk_db/callset.json') as f:
            data = json.load(f)
        f.close()
        # json_normalize is used to create a stacked dataframe from json `data`
        # sold is set of samples already processed
        sold = set( pd.json_normalize(data,record_path=['callsets']).sample_name.values )
        gvcf = [ 'gatk_gvcf/'+ name + '_sort_nodup.g.vcf.gz' for name in sall^sold ]
    return gvcf
