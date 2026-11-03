# Import pymodules
import glob
import pandas as pd
import json
from pathlib import Path

OUTPUT_ROOT = "/data/output"

# Function for passing multiple parameters with same arguement to Gatk tools
def Mult_Params(patern='Dummy', flist=['a','b']):
    return ' '.join( [patern + ' ' + str(fname) for fname in flist] )
