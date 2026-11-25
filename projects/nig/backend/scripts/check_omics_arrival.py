#!/usr/bin/env python3
"""Read-only check of the Omics outputs of a genome dataset (#83).

Verifies that a gVCF (and optionally its BAM and BQSR logs) produced by the
Omics ``nig/germline`` endpoint matches the NIG genome reference bundle, so
that it can be imported by the genome joint analysis without conversion:

* gVCF ``##contig`` and BAM ``@SQ`` identical (name, length, order) to the
  bundle ``.dict``; records only on known contigs, in ``.dict`` order;
* single sample ``SM = <sample>_<dataset_uuid>`` in gVCF and BAM read groups;
* BAM ``@PG`` of ``pbrun fq2bam``: reference, three known-sites and intervals
    inside the expected versioned Omics bundle (root from genome settings);
* ``<NON_REF>`` declared and present as last ALT of every scanned record;
* ``.tbi`` index present and not older than the gVCF;
* allele-specific (AS_*) annotations, needed by ``-G AS_StandardAnnotation``
  in the joint (J9: reported as a warning until decided);
* the three bundle known-sites named in the BQSR logs, no contig errors;
* optionally, a real ``GenomicsDBImport`` in a temporary workspace.

Pure standard library except the optional GenomicsDBImport (``gatk``).
Exit status 1 if any check FAILs. Example, in the backend/celery container:

    python3 /code/nig/scripts/check_omics_arrival.py \\
        --gvcf /data/output/.../omics/WGS1_<uuid>.g.vcf.gz --dataset-uuid <uuid> \\
        --bam /data/output/.../omics/WGS1_<uuid>.bam --bqsr-log bqsr.log \\
        --genomicsdb-interval chr20:30000000-30100000 --json report.json
"""

import argparse
import gzip
import json
import re
import shlex
import struct
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional, Tuple

import yaml

JOINT_YAML = Path(__file__).resolve().parents[1] / "snakemake" / "joint.yaml"
GVCF_SUFFIX = ".g.vcf.gz"
NON_REF = "<NON_REF>"
# basenames of the bundle known-sites (manifest of nig-grch38p14-dbsnp157-chr-v1)
KNOWN_SITES = [
    "dbsnp_157_grch38p14_nig_chr.vcf.gz",
    "Mills_and_1000G_gold_standard.indels.grch38p14_nig_chr.vcf.gz",
    "1000G_omni2.5.grch38p14_nig_chr.vcf.gz",
]
CONTIG_ERROR = re.compile(
    r"incompatible contigs|not (present|found) in the sequence dictionary"
    r"|sequence dictionar(y|ies)\b.*\b(differ|mismatch|incompatible)",
    re.IGNORECASE,
)
CONTIG_HEADER = re.compile(r"^##contig=<ID=([^,>]+)(?:,length=(\d+))?")
INFO_HEADER = re.compile(r"^##INFO=<ID=([^,>]+)")
# GATK4 writes no ##reference: the FASTA is in the tool command line
REFERENCE_DECL = re.compile(r"^##reference=(\S+)|(?:--reference|\s-R)[ =]([^\s\",]+)")

Sequence = Tuple[str, int]


@dataclass
class Check:
    name: str
    status: str  # PASS | WARN | FAIL
    detail: str


def ok(name: str, cond: bool, detail: str, fail: str = "FAIL") -> Check:
    return Check(name, "PASS" if cond else fail, detail)


def genome_settings(config_file: Path = JOINT_YAML) -> Dict[str, str]:
    with open(config_file) as f:
        return yaml.safe_load(f)["genome"]


def read_dict(path: Path) -> List[Sequence]:
    sequences = []
    with open(path) as f:
        for line in f:
            if line.startswith("@SQ"):
                tags = dict(t.split(":", 1) for t in line.rstrip("\n").split("\t")[1:])
                sequences.append((tags["SN"], int(tags["LN"])))
    return sequences


def compare_sequences(found: List[Sequence], expected: List[Sequence]) -> str:
    """Empty string if identical, otherwise the first difference."""
    if found == expected:
        return ""
    for i, (f, e) in enumerate(zip(found, expected)):
        if f != e:
            return f"position {i + 1}: {f[0]}:{f[1]} != {e[0]}:{e[1]}"
    return f"{len(found)} sequences != {len(expected)} in .dict"


def expected_sample(gvcf: Path, dataset_uuid: Optional[str]) -> Tuple[str, List[Check]]:
    checks = []
    name = gvcf.name
    sample = name[: -len(GVCF_SUFFIX)] if name.endswith(GVCF_SUFFIX) else name
    checks.append(ok("gvcf_name", name.endswith(GVCF_SUFFIX), name))
    if dataset_uuid:
        checks.append(
            ok(
                "gvcf_name_dataset",
                sample.endswith(f"_{dataset_uuid}") and len(sample) > len(dataset_uuid) + 1,
                f"expected <sample>_{dataset_uuid}{GVCF_SUFFIX}, found {name}",
            )
        )
    return sample, checks


def check_gvcf(
    gvcf: Path, sequences: List[Sequence], sample: str, max_records: int = 0
) -> List[Check]:
    checks = []
    tbi = Path(f"{gvcf}.tbi")
    checks.append(ok("gvcf_tbi", tbi.is_file() and tbi.stat().st_size > 0, str(tbi)))
    if tbi.is_file():
        checks.append(
            ok(
                "gvcf_tbi_fresh",
                tbi.stat().st_mtime >= gvcf.stat().st_mtime,
                "index not older than gVCF",
                fail="WARN",
            )
        )
    contigs: List[Sequence] = []
    info_ids: List[str] = []
    samples: List[str] = []
    non_ref_declared = False
    references: List[str] = []
    order = {name: i for i, (name, _) in enumerate(sequences)}
    records = bad_alt = unknown = unsorted = 0
    first_bad = ""
    last = -1
    seen = set()
    with gzip.open(gvcf, "rt") as f:
        for line in f:
            if line.startswith("##"):
                m = CONTIG_HEADER.match(line)
                if m:
                    contigs.append((m.group(1), int(m.group(2) or -1)))
                m = INFO_HEADER.match(line)
                if m:
                    info_ids.append(m.group(1))
                if line.startswith("##ALT=<ID=NON_REF"):
                    non_ref_declared = True
                m = REFERENCE_DECL.search(line)
                if m and (m.group(1) or m.group(2)) not in references:
                    references.append(m.group(1) or m.group(2))
                continue
            if line.startswith("#CHROM"):
                samples = line.rstrip("\n").split("\t")[9:]
                continue
            if max_records and records >= max_records:
                break
            records += 1
            chrom, pos, _, _, alt = line.split("\t", 5)[:5]
            if alt.split(",")[-1] != NON_REF:
                bad_alt += 1
                first_bad = first_bad or f"{chrom}:{pos} ALT={alt}"
            idx = order.get(chrom)
            if idx is None:
                unknown += 1
            elif idx < last:
                unsorted += 1
            else:
                last = idx
                seen.add(chrom)

    diff = compare_sequences(contigs, sequences)
    checks.append(ok("gvcf_contigs_eq_dict", not diff, diff or f"{len(contigs)} ##contig = .dict"))
    checks.append(ok("gvcf_single_sample", samples == [sample], f"samples {samples}, expected [{sample}]"))
    checks.append(ok("gvcf_non_ref_header", non_ref_declared, "##ALT=<ID=NON_REF>"))
    scope = f"first {records}" if max_records else f"all {records}"
    checks.append(ok("gvcf_records", records > 0, f"{scope} records on {len(seen)} contigs"))
    checks.append(ok("gvcf_non_ref_records", bad_alt == 0, f"{bad_alt} records without trailing {NON_REF} {first_bad}".strip()))
    checks.append(ok("gvcf_record_contigs", unknown == 0, f"{unknown} records on contigs not in .dict"))
    checks.append(ok("gvcf_record_order", unsorted == 0, f"{unsorted} records out of .dict order"))
    as_ids = sorted(i for i in info_ids if i.startswith("AS_"))
    checks.append(
        ok("gvcf_as_annotations", bool(as_ids), ",".join(as_ids) or "no AS_* INFO (J9)", fail="WARN")
    )
    checks.append(
        Check("gvcf_reference", "INFO", " | ".join(references) or "not declared")
    )
    return checks


def read_bam_header(bam: Path) -> Tuple[str, List[Sequence]]:
    """SAM text header and binary reference list of a BAM (BGZF = gzip)."""
    with gzip.open(bam, "rb") as f:
        if f.read(4) != b"BAM\1":
            raise ValueError(f"{bam} is not a BAM file")
        (l_text,) = struct.unpack("<i", f.read(4))
        text = f.read(l_text).decode().rstrip("\0")
        (n_ref,) = struct.unpack("<i", f.read(4))
        refs = []
        for _ in range(n_ref):
            (l_name,) = struct.unpack("<i", f.read(4))
            name = f.read(l_name).decode().rstrip("\0")
            (l_ref,) = struct.unpack("<i", f.read(4))
            refs.append((name, l_ref))
    return text, refs


def check_bam(bam: Path, sequences: List[Sequence], sample: str) -> List[Check]:
    text, refs = read_bam_header(bam)
    sq: List[Sequence] = []
    sms = set()
    for line in text.splitlines():
        tags = dict(t.split(":", 1) for t in line.split("\t")[1:] if ":" in t)
        if line.startswith("@SQ"):
            sq.append((tags["SN"], int(tags["LN"])))
        elif line.startswith("@RG"):
            sms.add(tags.get("SM"))
    diff = compare_sequences(sq, sequences)
    checks = [
        ok("bam_sq_eq_dict", not diff, diff or f"{len(sq)} @SQ = .dict"),
        ok("bam_refs_eq_dict", refs == sequences, f"{len(refs)} binary references"),
        ok("bam_rg_sm", sms == {sample}, f"@RG SM {sorted(map(str, sms))}, expected {sample}"),
    ]
    for index in (Path(f"{bam}.bai"), bam.with_suffix(".bai")):
        if index.is_file():
            return checks + [ok("bam_index", True, str(index))]
    return checks + [ok("bam_index", False, f"{bam}.bai not found")]


def check_fq2bam_pg(text: str, reference_id: str, reference_root: str) -> List[Check]:
    """Validate only fq2bam resource paths, never execute or report its full CL.

    These are paths on Omics, not local paths: use POSIX lexical containment,
    reject traversal, and do not resolve them against the NIG filesystem.
    """
    root = PurePosixPath(reference_root)
    if (
        not root.is_absolute()
        or any(p in (".", "..") for p in reference_root.split("/"))
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", reference_id)
    ):
        return [ok("bam_pg_config", False, "invalid Omics reference root or reference_id")]
    bundle = root / reference_id / "bundle"
    programs = []
    for line in text.splitlines():
        if not line.startswith("@PG\t"):
            continue
        tags = dict(t.split(":", 1) for t in line.split("\t")[1:] if ":" in t)
        if tags.get("PN") == "pbrun fq2bam" or tags.get("ID") == "pbrun fq2bam":
            programs.append(tags)
    checks = [ok("bam_pg_fq2bam", len(programs) == 1, f"{len(programs)} fq2bam @PG entries, expected 1")]
    if len(programs) != 1:
        return checks
    try:
        tokens = shlex.split(programs[0].get("CL", ""))
    except ValueError:
        return checks + [ok("bam_pg_command", False, "malformed fq2bam CL")]
    if len(tokens) < 2 or PurePosixPath(tokens[0]).name != "pbrun" or tokens[1] != "fq2bam":
        return checks + [ok("bam_pg_command", False, "missing pbrun fq2bam command")]

    paths: Dict[str, List[str]] = {"--ref": [], "--knownSites": [], "--interval-file": []}
    for i, token in enumerate(tokens[2:], start=2):
        option, sep, value = token.partition("=")
        if option not in paths:
            continue
        if not sep:
            value = tokens[i + 1] if i + 1 < len(tokens) and not tokens[i + 1].startswith("-") else ""
        paths[option].append(value)

    def inside_bundle(value: str) -> bool:
        path = PurePosixPath(value)
        return (
            path.is_absolute()
            and not any(p in (".", "..") for p in value.split("/"))
            and bundle in path.parents
        )

    for option, name, count in (
        ("--ref", "bam_pg_ref", 1),
        ("--knownSites", "bam_pg_known_sites", 3),
        ("--interval-file", "bam_pg_intervals", 1),
    ):
        found = paths[option]
        valid = len(found) == count and len(set(found)) == count and all(inside_bundle(p) for p in found)
        checks.append(ok(name, valid, f"{option}: {json.dumps(found)}; expected {count} distinct path(s) inside {bundle}/"))
    return checks


def check_bam_pg(
    bam: Path, reference_id: str, reference_root: str, samtools: str = "samtools"
) -> List[Check]:
    """Read only the header, without adding samtools' own @PG to the output."""
    proc = subprocess.run(
        [samtools, "view", "--no-PG", "-H", str(bam)],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode:
        return [ok("bam_pg_read", False, f"samtools header read failed (rc={proc.returncode})")]
    return check_fq2bam_pg(proc.stdout, reference_id, reference_root)


def check_logs(logs: Iterable[Path], known_sites: List[str]) -> List[Check]:
    text = "\n".join(Path(p).read_text(errors="replace") for p in logs)
    missing = [k for k in known_sites if k not in text]
    errors = [line.strip()[:200] for line in text.splitlines() if CONTIG_ERROR.search(line)]
    return [
        ok("bqsr_known_sites", not missing, f"missing {missing}" if missing else f"{len(known_sites)} known-sites named"),
        ok("bqsr_contig_errors", not errors, errors[0] if errors else "none"),
    ]


def check_genomicsdb(gvcf: Path, fasta: str, interval: str, sample: str, gatk: str) -> List[Check]:
    with tempfile.TemporaryDirectory(prefix="omics-arrival-") as tmp:
        ws = Path(tmp, "ws")
        cmd = [
            gatk, "--java-options", "-Xmx4g", "GenomicsDBImport", "-R", fasta,
            "-V", str(gvcf), "-L", interval, "--genomicsdb-workspace-path", str(ws),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or [""]
            return [ok("genomicsdb_import", False, f"rc={proc.returncode} {tail[0][:200]}")]
        callset = json.loads(ws.joinpath("callset.json").read_text())
        names = [c["sample_name"] for c in callset.get("callsets", [])]
        return [ok("genomicsdb_import", names == [sample], f"{interval}: callset {names}")]


def build_report(args: argparse.Namespace) -> Dict[str, object]:
    settings = genome_settings(args.joint_config)
    fasta = args.fasta or settings["fasta"]
    dict_file = args.dict or str(Path(fasta).with_suffix(".dict"))
    sequences = read_dict(Path(dict_file))
    gvcf = Path(args.gvcf)
    sample, checks = expected_sample(gvcf, args.dataset_uuid)
    sample = args.expected_sample or sample
    checks += check_gvcf(gvcf, sequences, sample, args.max_records)
    if args.bam:
        checks += check_bam(Path(args.bam), sequences, sample)
        checks += check_bam_pg(
            Path(args.bam), settings["reference_id"],
            args.omics_reference_root or settings.get("omics_reference_root", ""), args.samtools,
        )
    if args.bqsr_log:
        checks += check_logs([Path(p) for p in args.bqsr_log], KNOWN_SITES)
    if args.genomicsdb_interval:
        checks += check_genomicsdb(gvcf, fasta, args.genomicsdb_interval, sample, args.gatk)
    failed = [c.name for c in checks if c.status == "FAIL"]
    return {
        "report_type": "nig_omics_arrival_check",
        "reference_id": settings["reference_id"],
        "dict": dict_file,
        "gvcf": str(gvcf),
        "expected_sample": sample,
        "result": "FAIL" if failed else "PASS",
        "failed": failed,
        "checks": [asdict(c) for c in checks],
    }


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--gvcf", required=True, help="<sample>_<dataset_uuid>.g.vcf.gz")
    parser.add_argument("--dataset-uuid", help="check the gVCF name/SM suffix")
    parser.add_argument("--expected-sample", help="override SM (default: gVCF name)")
    parser.add_argument("--bam", help="Omics BAM (index .bam.bai or .bai beside it)")
    parser.add_argument("--omics-reference-root", help="override genome omics_reference_root from joint.yaml")
    parser.add_argument("--samtools", default="samtools", help="samtools executable for BAM @PG")
    parser.add_argument("--bqsr-log", action="append", help="BQSR log/command line, repeatable")
    parser.add_argument("--genomicsdb-interval", help="run GenomicsDBImport on this interval")
    parser.add_argument("--max-records", type=int, default=0, help="0 = scan all records")
    parser.add_argument("--joint-config", type=Path, default=JOINT_YAML)
    parser.add_argument("--fasta", help="default: genome fasta of joint.yaml")
    parser.add_argument("--dict", help="default: .dict beside the fasta")
    parser.add_argument("--gatk", default="gatk")
    parser.add_argument("--json", type=Path, help="write the report as JSON")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    report = build_report(args)
    for c in report["checks"]:  # type: ignore[union-attr]
        print(f"{c['status']:4} {c['name']}: {c['detail']}")
    print(f"RESULT {report['result']} ({report['reference_id']})")
    if args.json:
        args.json.write_text(json.dumps(report, indent=2))
    return 1 if report["result"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
