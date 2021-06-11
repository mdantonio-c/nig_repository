import os
import re
from pathlib import Path

import pandas as pd
import snakemake as smk
from restapi.connectors.celery import CeleryExt
from restapi.utilities.logs import log


@CeleryExt.task()
def launch_pipeline(
    self,
    file_list,
    isnake,  # it's true or isnake is an optional param?
    cores=None,
    force=False,
    dryrun=False,
):
    log.info("Start task [{}:{}]", self.request.id, self.name)
    # create a list of fastq files as csv file: fastq.csv
    # create symlinks for fastq files
    fastq = []

    wrkdir = Path("/snakemake")
    out_dir = Path("/data/output")

    slinkdir = Path(
        out_dir, "slinks"
    )  # TODO what will be the directory for symlinks? it will be a single one?
    slinkdir.mkdir(parents=True, exist_ok=True)

    # the pattern is check also in the file upload endpoint. This is an additional check
    pattern = r"([a-zA-Z0-9]+)_(R[12]).fastq.gz"
    for fl in file_list:
        filepath = Path(fl)
        fname = filepath.name
        if match := re.match(pattern, fname):
            file_label = match.group(1)
            fragment = match.group(2)

            # create a symlink in workdir folder
            try:
                symlink_path = Path(slinkdir, fname)
                symlink_path.symlink_to(
                    filepath
                )  # TODO what will be the slinks dir? it is the same for all or different for the different datasets?
            except FileExistsError:
                log.warning("{} has already a symlink", filepath)

            # create row for csv
            fastq_row = [file_label, fragment, filepath.parent]
            fastq.append(fastq_row)
        else:
            log.info(
                f"fastq: {fl} should follow correct nomenclature SampleName_R1/R2.fastq.gz"
            )

    # A dataframe is created
    df = pd.DataFrame(fastq, columns=["Sample", "Frag", "Path"])
    df["Reverse"] = "No"
    df.loc[df.Frag == "R2", "Reverse"] = "Yes"
    # fastq_csv_file = '/data/snakemake/NIG/fastq.csv'
    fastq_csv_file = Path(out_dir, "fastq.csv")
    df.to_csv(fastq_csv_file, index=None)
    log.info("*************************************")
    log.info("New file `fastq.csv' is now created")
    log.info(f"Total Number Of Fastq identified:{df.shape[0]}\n")

    # Launch snakemake
    config = [
        Path(wrkdir, "config.yaml")
    ]  # TODO it will be static or it has to be passed from the celery function?

    if not cores:
        cores = os.cpu_count()

    print(f"Calling Snakemake With {cores} cores")

    smk.snakemake(
        isnake,
        cores=cores,
        workdir=wrkdir,
        dryrun=dryrun,
        configfiles=config,
        forceall=force,
    )
