"""Select the gVCFs to import into a joint GenomicsDB workspace.

Plain Python (no Snakemake or NIG imports) so it can be unit tested; imported
by ``Joint_samples.smk`` from the workflow directory.
"""

import csv
import json
from pathlib import Path
from typing import Dict, List, Set


def imported_samples(callset_file: Path) -> Set[str]:
    """Sample names already in the workspace (empty if it does not exist)."""
    if not Path(callset_file).is_file():
        return set()
    with open(callset_file) as f:
        data = json.load(f)
    return {callset["sample_name"] for callset in data.get("callsets", [])}


def call_json(manifest: Path, callset_file: Path, update: bool) -> List[str]:
    """gVCF paths to import, read from the manifest ``Gvcf`` column.

    Samples are matched exactly; in update mode only samples not yet in the
    workspace are imported (``sall - sold``). A sample listed more than once
    keeps its first gVCF.
    """
    gvcf_by_sample: Dict[str, str] = {}
    with open(manifest, newline="") as f:
        for row in csv.DictReader(f):
            gvcf_by_sample.setdefault(row["Sample"], row["Gvcf"])
    sall = set(gvcf_by_sample)
    sold = imported_samples(callset_file) if update else set()
    return [gvcf_by_sample[s] for s in sorted(sall - sold)]
