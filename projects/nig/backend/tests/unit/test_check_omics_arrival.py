"""Unit tests for :mod:`nig.scripts.check_omics_arrival` (#83)."""

import gzip
import json
import struct
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import yaml
from nig.scripts import check_omics_arrival as arrival

UUID = "0f1e2d3c"
SAMPLE = f"WGS1_{UUID}"
SEQUENCES = [("chr1", 1000), ("chr2", 800), ("chrM", 16)]
AS_INFO = '##INFO=<ID=AS_RAW_MQ,Number=1,Type=String,Description="x">\n'


def write_dict(path: Path, sequences: List[Tuple[str, int]] = SEQUENCES) -> Path:
    lines = ["@HD\tVN:1.6\n"] + [f"@SQ\tSN:{n}\tLN:{ln}\tM5:x\n" for n, ln in sequences]
    path.write_text("".join(lines))
    return path


def write_gvcf(
    folder: Path,
    sample: str = SAMPLE,
    contigs: List[Tuple[str, int]] = SEQUENCES,
    records: Optional[List[Tuple[str, int, str]]] = None,
    info: str = AS_INFO,
    tbi: bool = True,
) -> Path:
    gvcf = folder / f"{sample}.g.vcf.gz"
    header = ["##fileformat=VCFv4.2\n", '##ALT=<ID=NON_REF,Description="any">\n', info]
    header.append('##GATKCommandLine=<ID=HaplotypeCaller,CommandLine="HaplotypeCaller --reference /b/ref.fasta -ERC GVCF">\n')
    header += [f"##contig=<ID={n},length={ln}>\n" for n, ln in contigs]
    header.append("\t".join(["#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT", sample]) + "\n")
    if records is None:
        records = [("chr1", 1, "<NON_REF>"), ("chr1", 5, "T,<NON_REF>"), ("chr2", 3, "<NON_REF>")]
    body = [f"{c}\t{p}\t.\tA\t{alt}\t.\t.\tEND={p}\tGT\t0/0\n" for c, p, alt in records]
    with gzip.open(gvcf, "wt") as f:
        f.write("".join(header + body))
    if tbi:
        Path(f"{gvcf}.tbi").write_bytes(b"TBI\1")
    return gvcf


def write_bam(path: Path, sm: str = SAMPLE, sequences: List[Tuple[str, int]] = SEQUENCES) -> Path:
    text = "@HD\tVN:1.6\n" + "".join(f"@SQ\tSN:{n}\tLN:{ln}\n" for n, ln in sequences)
    text += f"@RG\tID:rg1\tSM:{sm}\n"
    data = b"BAM\1" + struct.pack("<i", len(text)) + text.encode()
    data += struct.pack("<i", len(sequences))
    for name, length in sequences:
        raw = name.encode() + b"\0"
        data += struct.pack("<i", len(raw)) + raw + struct.pack("<i", length)
    with gzip.open(path, "wb") as f:
        f.write(data)
    Path(f"{path}.bai").write_bytes(b"BAI\1")
    return path


def statuses(checks: List[arrival.Check]) -> Dict[str, str]:
    return {c.name: c.status for c in checks}


def details(checks: List[arrival.Check]) -> Dict[str, str]:
    return {c.name: c.detail for c in checks}


def joint_config(tmp_path: Path) -> Path:
    fasta = tmp_path / "ref.fasta"
    write_dict(tmp_path / "ref.dict")
    config = tmp_path / "joint.yaml"
    config.write_text(yaml.safe_dump({"genome": {"reference_id": "bundle-v1", "fasta": str(fasta)}}))
    return config


def test_valid_gvcf_passes(tmp_path: Path) -> None:
    gvcf = write_gvcf(tmp_path)
    checks = arrival.check_gvcf(gvcf, SEQUENCES, SAMPLE)
    assert {c.status for c in checks if c.name != "gvcf_reference"} == {"PASS"}
    assert "3 records on 2 contigs" in details(checks)["gvcf_records"]
    assert details(checks)["gvcf_reference"] == "/b/ref.fasta"


def test_contigs_must_equal_dict(tmp_path: Path) -> None:
    other_length = [("chr1", 1000), ("chr2", 801), ("chrM", 16)]
    gvcf = write_gvcf(tmp_path, contigs=other_length)
    s = statuses(arrival.check_gvcf(gvcf, SEQUENCES, SAMPLE))
    assert s["gvcf_contigs_eq_dict"] == "FAIL"

    ensembl = [("1", 1000), ("2", 800), ("MT", 16)]
    gvcf = write_gvcf(tmp_path, contigs=ensembl, records=[("1", 1, "<NON_REF>")])
    s = statuses(arrival.check_gvcf(gvcf, SEQUENCES, SAMPLE))
    assert s["gvcf_contigs_eq_dict"] == s["gvcf_record_contigs"] == "FAIL"


def test_sample_name_and_records(tmp_path: Path) -> None:
    records = [("chr2", 1, "<NON_REF>"), ("chr1", 2, "<NON_REF>"), ("chr1", 3, "T")]
    gvcf = write_gvcf(tmp_path, sample="WGS1", records=records)
    s = statuses(arrival.check_gvcf(gvcf, SEQUENCES, SAMPLE))
    assert s["gvcf_single_sample"] == "FAIL"
    assert s["gvcf_non_ref_records"] == "FAIL"
    assert s["gvcf_record_order"] == "FAIL"

    _, name_checks = arrival.expected_sample(gvcf, UUID)
    assert statuses(name_checks)["gvcf_name_dataset"] == "FAIL"
    sample, name_checks = arrival.expected_sample(write_gvcf(tmp_path), UUID)
    assert sample == SAMPLE and {c.status for c in name_checks} == {"PASS"}


def test_missing_index_fails_missing_as_warns(tmp_path: Path) -> None:
    gvcf = write_gvcf(tmp_path, info="", tbi=False)
    s = statuses(arrival.check_gvcf(gvcf, SEQUENCES, SAMPLE))
    assert s["gvcf_tbi"] == "FAIL"
    assert s["gvcf_as_annotations"] == "WARN"


def test_max_records_limits_the_scan(tmp_path: Path) -> None:
    gvcf = write_gvcf(tmp_path, records=[("chr1", 1, "<NON_REF>"), ("chr1", 2, "T")])
    s = statuses(arrival.check_gvcf(gvcf, SEQUENCES, SAMPLE, max_records=1))
    assert s["gvcf_non_ref_records"] == "PASS"


def test_bam_header(tmp_path: Path) -> None:
    s = statuses(arrival.check_bam(write_bam(tmp_path / "a.bam"), SEQUENCES, SAMPLE))
    assert set(s.values()) == {"PASS"}

    bam = write_bam(tmp_path / "b.bam", sm="WGS1", sequences=SEQUENCES[:2])
    Path(f"{bam}.bai").unlink()
    s = statuses(arrival.check_bam(bam, SEQUENCES, SAMPLE))
    assert s == {
        "bam_sq_eq_dict": "FAIL",
        "bam_refs_eq_dict": "FAIL",
        "bam_rg_sm": "FAIL",
        "bam_index": "FAIL",
    }


def test_bqsr_logs(tmp_path: Path) -> None:
    good = tmp_path / "good.log"
    good.write_text(" ".join(f"--knownSites /b/{k}" for k in arrival.KNOWN_SITES))
    assert set(statuses(arrival.check_logs([good], arrival.KNOWN_SITES)).values()) == {"PASS"}

    bad = tmp_path / "bad.log"
    bad.write_text(
        f"--knownSites /b/{arrival.KNOWN_SITES[0]}\n"
        "A USER ERROR has occurred: Input files reference and features have incompatible contigs\n"
    )
    s = statuses(arrival.check_logs([bad], arrival.KNOWN_SITES))
    assert s == {"bqsr_known_sites": "FAIL", "bqsr_contig_errors": "FAIL"}


def test_main_report_and_exit_code(tmp_path: Path, capsys: Any) -> None:
    config = joint_config(tmp_path)
    gvcf = write_gvcf(tmp_path)
    report = tmp_path / "report.json"
    argv = ["--gvcf", str(gvcf), "--dataset-uuid", UUID, "--joint-config", str(config)]

    assert arrival.main(argv + ["--json", str(report)]) == 0
    data = json.loads(report.read_text())
    assert (data["result"], data["reference_id"], data["expected_sample"]) == ("PASS", "bundle-v1", SAMPLE)
    assert data["dict"] == str(tmp_path / "ref.dict")
    assert "RESULT PASS" in capsys.readouterr().out

    write_dict(tmp_path / "ref.dict", SEQUENCES[:2])
    assert arrival.main(argv) == 1


def test_fetch_arrival_check_uses_the_requested_sample(
    monkeypatch: Any, tmp_path: Path
) -> None:
    from nig.tasks import omics_fetch_results as fetch

    monkeypatch.setattr(arrival, "JOINT_YAML", joint_config(tmp_path))
    gvcf = write_gvcf(tmp_path, info="")
    bam = write_bam(tmp_path / f"{SAMPLE}.bam")
    artifacts = {
        "GVCF": SimpleNamespace(local_path=str(gvcf)),
        "BAM": SimpleNamespace(local_path=str(bam)),
    }
    dataset = SimpleNamespace(uuid=UUID, omics_output_prefix=f"{SAMPLE}.g.vcf.gz")

    report = fetch._arrival_check(dataset, artifacts)

    assert report["result"] == "PASS"
    assert {c["name"]: c["status"] for c in report["checks"]}[
        "gvcf_as_annotations"
    ] == "WARN"
    saved = json.loads(tmp_path.joinpath(fetch.ARRIVAL_REPORT).read_text())
    assert saved["expected_sample"] == SAMPLE

    dataset.omics_output_prefix = f"WGS2_{UUID}.g.vcf.gz"
    report = fetch._arrival_check(dataset, artifacts)
    assert report["result"] == "FAIL"
    assert {"gvcf_single_sample", "bam_rg_sm"} <= set(report["failed"])
