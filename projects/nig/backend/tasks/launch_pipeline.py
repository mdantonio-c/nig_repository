import os
import re
import shutil
from pathlib import Path
from typing import List

import pandas as pd
import snakemake as smk
from restapi.connectors.celery import CeleryExt
from restapi.utilities.logs import log


@CeleryExt.task()
def launch_pipeline(
    self: CeleryExt.TaskType,
    file_list: List[str],
) -> None:
    log.info("Start task [{}:{}]", self.request.id, self.name)
    # create the workdir --> it has to be unique for every celery task (and snakemake launch)
    wrkdir = Path("/data/output", self.request.id)
    wrkdir.mkdir(parents=True, exist_ok=True)
    # copy the files used by snakemake in the work dir
    source_dir = Path("/snakemake")
    for snk_file in source_dir.glob("*"):
        shutil.copy(snk_file, wrkdir)

    # create a list of fastq files as csv file: fastq.csv
    # create symlinks for fastq files
    fastq = []

    # symlinks are useful now that the input path is in the csv?
    slinkdir = Path(wrkdir, "slinks")
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
                # it is the same for all or different for the different datasets?
                symlink_path.symlink_to(filepath)
            except FileExistsError:
                log.warning("{} has already a symlink", filepath)

            # create row for csv
            fastq_row = [file_label, fragment, filepath.parent]
            fastq.append(fastq_row)
        else:
            log.info(
                "fastq {} should follow correct naming convention SampleName_R1/R2.fastq.gz",
                fl,
            )

    # A dataframe is created
    df = pd.DataFrame(fastq, columns=["Sample", "Frag", "InputPath"])
    df["Reverse"] = "No"
    df.loc[df.Frag == "R2", "Reverse"] = "Yes"
    # fastq_csv_file = '/data/snakemake/NIG/fastq.csv'
    fastq_csv_file = Path(wrkdir, "fastq.csv")
    df.to_csv(fastq_csv_file, index=False)
    log.info("*************************************")
    log.info("New file {} is now created", fastq_csv_file)
    log.info("Total Number Of Fastq identified:{}\n", df.shape[0])

    # Launch snakemake
    config = [Path(wrkdir, "config.yaml")]

    # TODO this param can be in the config? it should be passed as argument for the celery task? or it's ok the simple cpu count?
    cores = os.cpu_count()
    log.info("Calling Snakemake with {} cores", cores)
    snakefile = f"{wrkdir}/Single_Sample_V2.smk"

    smk.snakemake(
        snakefile,
        cores=cores,
        workdir=wrkdir,
        configfiles=config,
    )

    return None
