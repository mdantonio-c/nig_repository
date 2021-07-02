import os
import re
import shutil
from pathlib import Path
from typing import List

import pandas as pd
import snakemake as smk
from nig.endpoints import GROUP_DIR
from restapi.connectors.celery import CeleryExt
from restapi.utilities.logs import log

OUTPUT_ROOT = "/data/output"


@CeleryExt.task()
def launch_pipeline(
    self: CeleryExt.TaskType,
    file_list: List[str],
    snakefile: str = "Single_Sample_V2.smk",
    force: bool = False,
) -> None:
    task_id = self.request.id  # type: ignore
    log.info("Start task [{}:{}]", task_id, self.name)
    # create a unique workdir for every celery task / and snakemake launch)
    wrkdir = Path("/data/jobs", task_id)
    wrkdir.mkdir(parents=True, exist_ok=True)
    # copy the files used by snakemake in the work dir
    source_dir = Path("/snakemake")
    for snk_file in source_dir.glob("*"):
        if snk_file.is_file():
            shutil.copy(snk_file, wrkdir)

    # create a list of fastq files as csv file: fastq.csv
    # create symlinks for fastq files
    fastq = []

    # the pattern is check also in the file upload endpoint. This is an additional check
    pattern = r"([a-zA-Z0-9]+)_(R[12]).fastq.gz"
    for fl in file_list:
        filepath = Path(fl)
        fname = filepath.name
        if match := re.match(pattern, fname):
            file_label = match.group(1)
            fragment = match.group(2)

            # get the input path
            input_path = filepath.parent
            # create the output path
            output_path = Path(OUTPUT_ROOT, input_path.relative_to(GROUP_DIR))

            # create row for csv
            fastq_row = [file_label, fragment, input_path, output_path]
            fastq.append(fastq_row)
        else:
            log.info(
                "fastq {} should follow correct naming convention SampleName_R1/R2.fastq.gz",
                fl,
            )

    # A dataframe is created
    df = pd.DataFrame(fastq, columns=["Sample", "Frag", "InputPath", "OutputPath"])
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
    snakefile_path = Path(wrkdir, snakefile)

    smk.snakemake(
        snakefile_path, cores=cores, workdir=wrkdir, configfiles=config, forceall=force
    )

    return None
