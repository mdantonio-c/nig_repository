import csv
import os
import re
import shutil
from pathlib import Path
from typing import List

import yaml
from nig.endpoints import INPUT_ROOT, OUTPUT_ROOT
from pandas import DataFrame
from restapi.config import DATA_PATH
from restapi.connectors import neo4j
from restapi.connectors.celery import CeleryExt, Task
from restapi.connectors.smtp.notifications import send_notification
from restapi.utilities.logs import log
from snakemake import snakemake


@CeleryExt.task(idempotent=True, autoretry_for=(ConnectionResetError,))
def launch_joint_analysis(
    self: Task[[List[str], str, bool], None],
    dataset_list: List[str],
    snakefile: str = "Joint_samples.smk",
    force: bool = False,
) -> None:
    task_id = self.request.id
    log.info("Start joint analysis task [{}:{}]", task_id, self.name)
    # create a job node related to the task
    graph = neo4j.get_instance()
    job = graph.JointAnalysisJob(uuid=task_id).save()

    # create a unique workdir for every celery task / and snakemake launch)
    wrkdir = DATA_PATH.joinpath("jobs", task_id)
    wrkdir.mkdir(parents=True, exist_ok=True)
    # copy the files used by snakemake in the work dir
    source_dir = Path("/snakemake")
    for snk_file in source_dir.glob("*"):
        if snk_file.is_file():
            shutil.copy(snk_file, wrkdir)

    config_file = wrkdir.joinpath("config.yaml")
    with open(config_file) as stream:
        job_config = yaml.safe_load(stream)

    # create the tmp dir used by gatk
    tmp_dir = wrkdir.joinpath("tmp")
    if not tmp_dir.exists():
        tmp_dir.mkdir()

    # get the file list from the dataset list
    pattern = r"([a-zA-Z0-9_-]+)_(R[12]).fastq.gz"
    fastq = []
    sample_datasets = {}
    duplicate_samples = {}
    for d in dataset_list:
        # get the path of the dataset directory
        dataset = graph.Dataset.nodes.get_or_none(uuid=d)
        owner = dataset.ownership.single()
        group = owner.belongs_to.single()
        study = dataset.parent_study.single()
        datasetDirectory = INPUT_ROOT.joinpath(group.uuid, study.uuid, dataset.uuid)
        # check if the directory exists
        if not datasetDirectory.exists():
            # an error should be raised?
            log.warning("Folder for dataset {} not found", d)
            continue

        for f in datasetDirectory.iterdir():
            fname = f.name
            match = re.match(pattern, fname)
            if not match:
                continue
            file_label = match.group(1)
            selected_dataset = sample_datasets.setdefault(file_label, dataset)
            if selected_dataset.uuid != dataset.uuid:
                duplicate_samples.setdefault(file_label, set()).update(
                    (selected_dataset.uuid, dataset.uuid)
                )
            output_path = OUTPUT_ROOT.joinpath(datasetDirectory.relative_to(INPUT_ROOT))
            fastq_row = [file_label, output_path]
            fastq.append(fastq_row)

        # mark that a joint analysis has been launched on this dataset
        dataset.joint_analysis = True
        # connect the dataset to the job node
        dataset.joint_analysis_job.connect(job)
        dataset.save()

    # A dataframe is created
    df = DataFrame(fastq, columns=["Sample", "OutputPath"])

    fastq_csv_file = wrkdir.joinpath("fastq.csv")
    df.to_csv(fastq_csv_file, index=False)
    log.info("*************************************")
    log.info("New file {} is now created", fastq_csv_file)
    log.info("Total Number Of Fastq identified:{}\n", df.shape[0])

    # Materialize platform metadata in the formats consumed by the reusable
    # standardization workflow. Sample IDs come from the FASTQ basename, which
    # is also the sample name written into the joint VCF by HaplotypeCaller.
    phenotype_groups = {
        str(name).strip().lower(): group
        for name, group in job_config.get("STANDARDIZATION", {})
        .get("phenotype_groups", {})
        .items()
    }
    sex_rows = {}
    group_rows = {}
    macroarea_rows = {}
    phenotype_samples = {}
    unmapped_phenotypes = set()

    def get_phenotype_groups(phenotype):
        keys = [phenotype.name.strip().lower()]
        for hpo in phenotype.hpo.all():
            keys.extend((hpo.hpo_id.strip().lower(), hpo.label.strip().lower()))

        groups = []
        for key in keys:
            configured = phenotype_groups.get(key, [])
            if isinstance(configured, str):
                configured = [configured]
            for group in configured:
                group = str(group).strip().lower()
                if group and group not in groups:
                    groups.append(group)
        return groups

    for sample, dataset in sample_datasets.items():
        phenotype = dataset.phenotype.single()
        if phenotype:
            phenotype_samples.setdefault(phenotype.uuid, set()).add(sample)
        tags = []
        if phenotype:
            sex_rows[sample] = phenotype.sex
            tags.append(phenotype.sex)
            groups = get_phenotype_groups(phenotype)
            tags.extend(groups)
            if not groups:
                unmapped_phenotypes.add(phenotype.name)
            birthplace = phenotype.birth_place.single()
            if birthplace and birthplace.macroarea:
                macroarea_rows[sample] = birthplace.macroarea
        group_rows[sample] = tags or ["unknown"]

    sex_file = wrkdir.joinpath("standardization_sex.csv")
    with open(sex_file, "w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["sample", "sex"])
        writer.writerows(sorted(sex_rows.items()))

    groups_file = wrkdir.joinpath("standardization_groups.tsv")
    with open(groups_file, "w") as stream:
        for sample, tags in sorted(group_rows.items()):
            stream.write(f"{sample}\t{','.join(tags)}\n")

    macroarea_file = wrkdir.joinpath("standardization_macroarea.tsv")
    if macroarea_rows:
        with open(macroarea_file, "w") as stream:
            stream.write("ID\tMACROAREA\n")
            for sample, macroarea in sorted(macroarea_rows.items()):
                stream.write(f"{sample}\t{macroarea}\n")

    parents = set()
    probands = set()
    for sample, dataset in sample_datasets.items():
        phenotype = dataset.phenotype.single()
        if not phenotype:
            continue
        father = phenotype.father.single()
        mother = phenotype.mother.single()
        if father and mother:
            father_samples = phenotype_samples.get(father.uuid, set())
            mother_samples = phenotype_samples.get(mother.uuid, set())
            if father_samples and mother_samples:
                probands.add(sample)
                parents.update(father_samples)
                parents.update(mother_samples)

    parents_file = wrkdir.joinpath("standardization_parents.txt")
    probands_file = wrkdir.joinpath("standardization_probands.txt")
    if parents and probands:
        parents_file.write_text("\n".join(sorted(parents)) + "\n")
        probands_file.write_text("\n".join(sorted(probands)) + "\n")

    job_config["relatedness"]["sex_metadata_csv"] = (
        str(sex_file) if sex_rows else ""
    )
    job_config["annotation"]["outliers_groups_file"] = str(groups_file)
    job_config["covariates"]["macroarea_file"] = (
        str(macroarea_file) if macroarea_rows else ""
    )
    job_config["trio"].update(
        {
            "enabled": bool(parents and probands),
            "parents_file": str(parents_file) if parents else "",
            "probands_file": str(probands_file) if probands else "",
        }
    )
    with open(config_file, "w") as stream:
        yaml.safe_dump(job_config, stream, sort_keys=False)

    if unmapped_phenotypes:
        log.warning(
            "No standardization group mapping matched phenotype name or HPO: {}",
            sorted(unmapped_phenotypes),
        )
    if duplicate_samples:
        log.warning(
            "Duplicate joint sample IDs found; metadata follows the first dataset, "
            "matching Basic.smk: {}",
            {sample: sorted(uuids) for sample, uuids in duplicate_samples.items()},
        )

    # Launch snakemake
    config = [config_file]

    cores = os.cpu_count()
    log.info("Calling Snakemake with {} cores and forceall {}", cores, force)
    snakefile_path = wrkdir.joinpath(snakefile)

    # https://snakemake.readthedocs.io/en/stable/api_reference/snakemake.html
    successful = snakemake(
        snakefile_path,
        cores=cores,
        workdir=wrkdir,
        configfiles=config,
        forceall=force,
        use_conda=True,
        # Go on with independent jobs if a job fails. (default: False)
        keepgoing=True,
        # force the re-creation of incomplete files (default False)
        force_incomplete=True,
        # lock the working directory when executing the workflow (default True)
        lock=False,
    )

    if not successful:
        raise RuntimeError("Joint analysis or VCF standardization failed")

    log.info(f"job {task_id} completed")

    return None
