from __future__ import annotations

import argparse
import json
import platform
import sys
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from game_discovery import __version__


def _doctor() -> int:
    result = {
        "application": "game-discovery-ml",
        "version": __version__,
        "python_version": platform.python_version(),
        "python_supported": sys.version_info >= (3, 11) and sys.version_info < (3, 13),
        "status": "ready"
        if sys.version_info >= (3, 11) and sys.version_info < (3, 13)
        else "blocked",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["python_supported"] else 2


def _load_config(path: Path) -> tuple[dict, Path]:
    import yaml

    resolved = path.resolve()
    config = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise TypeError(f"Configuration must contain a YAML mapping: {resolved}")
    return config, resolved.parent.parent


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(path)


def _existing_interaction_parse(
    interaction_rows_path: Path,
    quality_path: Path,
    quarantine_path: Path,
    source_file_hash: str,
) -> dict[str, int] | None:
    import duckdb
    import pyarrow as pa
    import pyarrow.parquet as pq

    if (
        not interaction_rows_path.is_file()
        or interaction_rows_path.with_name(f"{interaction_rows_path.name}.part").exists()
        or not quality_path.is_file()
        or not quarantine_path.is_file()
    ):
        return None
    try:
        metadata = pq.read_metadata(interaction_rows_path)
        prior_quality = json.loads(quality_path.read_text(encoding="utf-8"))
        expected_rows = int(prior_quality["valid_interaction_rows_before_deduplication"])
        if metadata.num_rows != expected_rows:
            return None
        escaped_path = interaction_rows_path.resolve().as_posix().replace("'", "''")
        connection = duckdb.connect()
        distinct, minimum, maximum = connection.execute(
            "SELECT count(DISTINCT source_file_hash), min(source_file_hash), max(source_file_hash) "
            f"FROM read_parquet('{escaped_path}')"
        ).fetchone()
        connection.close()
        if distinct != 1 or minimum != source_file_hash or maximum != source_file_hash:
            return None
        counts = prior_quality["invalid_or_quarantined_records_by_reason"]
        parsed_counts = {str(key): int(value) for key, value in counts.items()}
        parsed_counts["valid_interaction_rows"] = int(
            prior_quality.get(
                "valid_interaction_rows",
                prior_quality["valid_interaction_rows_before_deduplication"],
            )
        )
        return parsed_counts
    except (OSError, ValueError, KeyError, duckdb.Error, pa.ArrowException):
        return None


def _data_download(config_path: Path, requested_source: str | None) -> int:
    from game_discovery.data.download import FILES, download_one, verify_download

    config, root = _load_config(config_path)
    raw_dir = root / config.get("paths", {}).get("raw", "data/raw")
    manifest_path = root / "artifacts/manifests/source_manifest.json"
    source_config = config.get("source", {})
    source = requested_source or source_config.get("download", "auto")
    manifest = {
        "dataset": "UCSD McAuley Lab Steam Video Game and Bundle Data",
        "dataset_page": "https://cse.ucsd.edu/~jmcauley/datasets.html#steam_data",
        "files": [],
        "download_source_requested": source,
        "citation_note": "Cite the associated Steam dataset research as directed by the publisher.",
        "redistribution_permission": "unresolved; local research processing only until reviewed",
    }
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous.get("dataset") != manifest["dataset"]:
            raise RuntimeError(f"Refusing to replace unrelated source manifest: {manifest_path}")
        manifest = previous
        manifest["download_source_requested"] = source
    for filename in FILES:
        existing = next((item for item in manifest["files"] if item["filename"] == filename), None)
        if existing:
            verify_download(raw_dir / filename, existing["sha256"], check_gzip=False)
            continue
        evidence = download_one(raw_dir, filename, source)
        manifest["files"].append(asdict(evidence))
        _write_json(manifest_path, manifest)
        print(json.dumps(asdict(evidence), indent=2, sort_keys=True))
    return 0


def _data_prepare(config_path: Path) -> int:
    from game_discovery.data.download import FILES, verify_download
    from game_discovery.data.parse import prepare_interactions, prepare_items
    from game_discovery.data.quality import prepare_quality

    config, root = _load_config(config_path)
    raw_dir = root / config.get("paths", {}).get("raw", "data/raw")
    processed = root / config.get("paths", {}).get("processed", "data/processed")
    manifest_path = root / "artifacts/manifests/source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_files = {entry["filename"]: entry for entry in manifest.get("files", [])}
    missing = [filename for filename in FILES if filename not in source_files]
    if missing:
        raise RuntimeError(f"Source manifest is missing downloaded files: {', '.join(missing)}")

    interactions_source = source_files["steam_reviews.json.gz"]
    games_source = source_files["steam_games.json.gz"]
    # Download acceptance already checked SHA-256 against upstream and gzip through EOF.
    # Recheck local size here; the parser below consumes the entire gzip stream again.
    verify_download(
        raw_dir / "steam_reviews.json.gz",
        interactions_source["sha256"],
        expected_bytes=interactions_source["bytes"],
        check_sha256=False,
        check_gzip=False,
    )
    verify_download(
        raw_dir / "steam_games.json.gz",
        games_source["sha256"],
        expected_bytes=games_source["bytes"],
        check_sha256=False,
        check_gzip=False,
    )
    interaction_rows_path = processed / "interactions_raw.parquet"
    quarantine_path = root / "private/events/quarantine/reviews_malformed.jsonl.gz"
    quality_path = root / "artifacts/manifests/data_quality.json"
    parse_counts = _existing_interaction_parse(
        interaction_rows_path, quality_path, quarantine_path, interactions_source["sha256"]
    )
    if parse_counts is None:
        parse_counts = prepare_interactions(
            raw_dir / "steam_reviews.json.gz",
            interaction_rows_path,
            quarantine_path,
            root / "private/mappings/user_identity_hmac.key",
            interactions_source["sha256"],
        )
    else:
        print(
            "reusing completed private interaction parse from Parquet and preparation evidence",
            flush=True,
        )
    items_path = processed / "items_raw.parquet"
    metadata_counts = prepare_items(
        raw_dir / "steam_games.json.gz", items_path, games_source["sha256"]
    )
    mode = str(config.get("mode", "smoke"))
    sample_path = processed / mode / "interactions.parquet"
    quality, stats = prepare_quality(
        interaction_rows_path=interaction_rows_path,
        items_path=items_path,
        cleaned_interactions_path=processed / "cleaned/interactions.parquet",
        cleaned_items_path=processed / "cleaned/items.parquet",
        sampled_interactions_path=sample_path,
        config=config,
        parse_counts=parse_counts,
        metadata_counts=metadata_counts,
        quality_output=quality_path,
        stats_output=root / "artifacts/manifests/dataset_stats.json",
        profile_output=root / "artifacts/reports/data_profile.html",
    )
    _write_json(
        root / "artifacts/manifests/preparation_manifest.json",
        {
            "review_source_sha256": interactions_source["sha256"],
            "metadata_source_sha256": games_source["sha256"],
            "interaction_rows_before_deduplication": parse_counts.get("valid_interaction_rows", 0),
            "deduplicated_interaction_rows": quality["deduplicated_interaction_rows"],
            "mode": mode,
            "sampling_fraction": stats["sampling_fraction"],
            "prepared_at": datetime.now().astimezone().isoformat(),
        },
    )
    print(
        json.dumps(
            {"data_quality": quality, "dataset_stats": stats}, indent=2, sort_keys=True, default=str
        )
    )
    return 0


def _data_split(config_path: Path) -> int:
    from game_discovery.data.split import freeze_global_split

    config, root = _load_config(config_path)
    mode = str(config.get("mode", "smoke"))
    processed = root / config.get("paths", {}).get("processed", "data/processed")
    manifest = freeze_global_split(
        processed / mode / "interactions.parquet",
        processed / "splits" / mode,
        root / "artifacts/manifests/split_manifest.json",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True, default=str))
    return 0


def _evaluate(split: str, config_path: Path) -> int:
    from game_discovery.evaluation.baselines import evaluate_validation_baselines

    if split != "validation":
        raise RuntimeError(
            "Final test evaluation is gated until a frozen validation selection record exists"
        )
    config, root = _load_config(config_path)
    mode = str(config.get("mode", "smoke"))
    report = evaluate_validation_baselines(
        root / "data/processed/splits" / mode,
        root / "artifacts/manifests/split_manifest.json",
        root / "artifacts/reports/validation_baselines.json",
        root / "private/evaluation/validation_baselines.parquet",
    )
    als_training_report = root / "artifacts/reports/als_training.json"
    combined: dict[str, object] = {"baselines": report}
    if als_training_report.exists():
        from game_discovery.evaluation.als import evaluate_als_grid

        combined["als"] = evaluate_als_grid(
            root / "data/processed/splits" / mode,
            root / "artifacts/manifests/split_manifest.json",
            als_training_report,
            root / "artifacts/reports/validation_baselines.json",
            root / "private/evaluation/validation_baselines.parquet",
            root / "artifacts/reports/validation_als.json",
            root / "private/evaluation/validation_als.parquet",
        )
    item_item_training = root / "artifacts/reports/item_item_training.json"
    if item_item_training.exists():
        from game_discovery.evaluation.item_item import evaluate_item_item

        combined["item_item"] = evaluate_item_item(
            root / "data/processed/splits" / mode,
            root / "artifacts/manifests/split_manifest.json",
            item_item_training,
            root / "artifacts/reports/validation_baselines.json",
            root / "private/evaluation/validation_baselines.parquet",
            root / "artifacts/reports/validation_item_item.json",
            root / "private/evaluation/validation_item_item.parquet",
        )
    content_training = root / "artifacts/reports/static_metadata_training.json"
    if content_training.exists():
        from game_discovery.evaluation.item_item import evaluate_item_item

        combined["static_metadata"] = evaluate_item_item(
            root / "data/processed/splits" / mode,
            root / "artifacts/manifests/split_manifest.json",
            content_training,
            root / "artifacts/reports/validation_baselines.json",
            root / "private/evaluation/validation_baselines.parquet",
            root / "artifacts/reports/validation_static_metadata.json",
            root / "private/evaluation/validation_static_metadata.parquet",
        )
    if als_training_report.exists() and item_item_training.exists() and content_training.exists():
        from game_discovery.evaluation.hybrid import evaluate_validation_hybrids

        combined["hybrids"] = evaluate_validation_hybrids(
            root / "data/processed/splits" / mode,
            root / "artifacts/manifests/split_manifest.json",
            als_training_report,
            item_item_training,
            content_training,
            root / "artifacts/reports/validation_baselines.json",
            root / "private/evaluation/validation_baselines.parquet",
            root / "artifacts/reports/validation_hybrids.json",
            root / "private/evaluation/validation_hybrids.parquet",
        )
    print(json.dumps(combined, indent=2, sort_keys=True, default=str))
    return 0


def _train(config_path: Path) -> int:
    from game_discovery.models.als import train_als_grid
    from game_discovery.models.content import train_static_metadata_tfidf
    from game_discovery.models.item_item import train_item_item

    config, root = _load_config(config_path)
    mode = str(config.get("mode", "smoke"))
    report = train_als_grid(
        root / "data/processed/splits" / mode / "train.parquet",
        root / "artifacts/manifests/split_manifest.json",
        root / "private/experiments/als",
        root / "artifacts/reports/als_training.json",
    )
    item_item_report = train_item_item(
        root / "data/processed/splits" / mode / "train.parquet",
        root / "artifacts/manifests/split_manifest.json",
        root / "private/experiments/item_item/similarity.npz",
        root / "artifacts/reports/item_item_training.json",
    )
    content_report = train_static_metadata_tfidf(
        root / "data/processed/splits" / mode / "train.parquet",
        root / "data/processed/cleaned/items.parquet",
        root / "artifacts/manifests/split_manifest.json",
        root / "private/experiments/static_metadata/features.npz",
        root / "artifacts/reports/static_metadata_training.json",
    )
    print(
        json.dumps(
            {
                "als": report,
                "item_item": item_item_report,
                "static_metadata": content_report,
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="game-discovery",
        description="Game-interest discovery project tools.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check the local Python runtime for project work.")
    data = commands.add_parser("data", help="Download and prepare historical dataset files.")
    data_commands = data.add_subparsers(dest="data_command", required=True)
    download = data_commands.add_parser(
        "download", help="Download the two source files and record provenance."
    )
    download.add_argument("--config", type=Path, required=True)
    download.add_argument("--source", choices=("auto", "publisher", "mirror"))
    prepare = data_commands.add_parser(
        "prepare", help="Parse files and produce private Parquet plus quality reports."
    )
    prepare.add_argument("--config", type=Path, required=True)
    split_command = data_commands.add_parser(
        "split", help="Freeze global chronological windows from the configured sample."
    )
    split_command.add_argument("--config", type=Path, required=True)
    evaluate = commands.add_parser("evaluate", help="Evaluate models on a frozen temporal split.")
    evaluate.add_argument("--split", choices=("validation", "test"), required=True)
    evaluate.add_argument("--config", type=Path, default=Path("configs/portfolio.yaml"))
    train = commands.add_parser("train", help="Train configured CPU recommendation models.")
    train.add_argument("--config", type=Path, default=Path("configs/portfolio.yaml"))
    args = parser.parse_args(argv)
    if args.command == "doctor":
        return _doctor()
    if args.command == "data" and args.data_command == "download":
        return _data_download(args.config, args.source)
    if args.command == "data" and args.data_command == "prepare":
        return _data_prepare(args.config)
    if args.command == "data" and args.data_command == "split":
        return _data_split(args.config)
    if args.command == "evaluate":
        return _evaluate(args.split, args.config)
    if args.command == "train":
        return _train(args.config)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
