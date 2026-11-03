"""J4: selection of the gVCFs to import into the GenomicsDB workspace."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import List

import nig


def load_joint_inputs() -> ModuleType:
    # plain module of the Snakemake workflow, not part of the nig package
    path = Path(nig.__file__).parent / "snakemake" / "joint_inputs.py"
    spec = importlib.util.spec_from_file_location("joint_inputs", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


joint_inputs = load_joint_inputs()


def manifest(path: Path, rows: List[List[str]]) -> Path:
    lines = ["Sample,Dataset,Gvcf"] + [",".join(r) for r in rows]
    path.write_text("\n".join(lines) + "\n")
    return path


def callset(path: Path, samples: List[str]) -> Path:
    data = {"callsets": [{"sample_name": s, "row_idx": i} for i, s in enumerate(samples)]}
    path.write_text(json.dumps(data))
    return path


def test_samples_are_matched_exactly(tmp_path: Path) -> None:
    # S1 is a substring of S10: the old str.contains picked the wrong row
    csv = manifest(
        tmp_path / "joint.csv",
        [["S10", "d3", "/o/d3/S10.g.vcf.gz"], ["S1", "d1", "/o/d1/S1.g.vcf.gz"]],
    )

    gvcfs = joint_inputs.call_json(csv, tmp_path / "missing.json", update=False)

    assert gvcfs == ["/o/d1/S1.g.vcf.gz", "/o/d3/S10.g.vcf.gz"]


def test_update_imports_only_new_samples(tmp_path: Path) -> None:
    csv = manifest(
        tmp_path / "joint.csv",
        [["A", "d1", "/o/A.g.vcf.gz"], ["B", "d2", "/o/B.g.vcf.gz"]],
    )
    # C is in the workspace but not in this run: the old symmetric
    # difference (sall ^ sold) tried to import it again
    cs = callset(tmp_path / "callset.json", ["A", "C"])

    assert joint_inputs.call_json(csv, cs, update=True) == ["/o/B.g.vcf.gz"]


def test_update_without_callset_imports_all(tmp_path: Path) -> None:
    csv = manifest(tmp_path / "joint.csv", [["A", "d1", "/o/A.g.vcf.gz"]])

    assert joint_inputs.call_json(csv, tmp_path / "none.json", update=True) == [
        "/o/A.g.vcf.gz"
    ]


def test_create_ignores_an_existing_callset(tmp_path: Path) -> None:
    csv = manifest(tmp_path / "joint.csv", [["A", "d1", "/o/A.g.vcf.gz"]])
    cs = callset(tmp_path / "callset.json", ["A"])

    assert joint_inputs.call_json(csv, cs, update=False) == ["/o/A.g.vcf.gz"]


def test_duplicate_sample_keeps_its_first_gvcf(tmp_path: Path) -> None:
    csv = manifest(
        tmp_path / "joint.csv",
        [["A", "d1", "/o/d1/A.g.vcf.gz"], ["A", "d2", "/o/d2/A.g.vcf.gz"]],
    )

    assert joint_inputs.call_json(csv, tmp_path / "none.json", update=False) == [
        "/o/d1/A.g.vcf.gz"
    ]
