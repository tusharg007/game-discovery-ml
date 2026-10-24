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
    if split == "test":
        config, root = _load_config(config_path)
        mode = str(config.get("mode", "smoke"))
        from game_discovery.evaluation.final_test import evaluate_frozen_candidate_on_test

        report = evaluate_frozen_candidate_on_test(
            root / "data/processed/splits" / mode,
            root / "artifacts/manifests/split_manifest.json",
            root / "MODEL_SELECTION.json",
            root / "models/release/selected_candidate",
            root / "artifacts/reports/final_test.json",
            root / "private/evaluation/final_test.parquet",
        )
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return 0
    if split != "validation":
        raise RuntimeError(
            "Split must be validation or test; test uses the frozen selection and release bundle"
        )
    from game_discovery.evaluation.baselines import evaluate_validation_baselines

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


def _export_release(config_path: Path, output_dir: Path | None = None) -> int:
    from game_discovery.serving.bundle import export_selected_bundle

    config, root = _load_config(config_path)
    mode = str(config.get("mode", "smoke"))
    directory = output_dir or root / "models/release/selected_candidate"
    report = export_selected_bundle(
        root / "data/processed/splits" / mode,
        root / "data/processed/cleaned/items.parquet",
        root / "MODEL_SELECTION.json",
        root / "artifacts/manifests/split_manifest.json",
        directory,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _verify_release(bundle_dir: Path) -> int:
    import numpy as np
    import psutil

    from game_discovery.serving.bundle import RecommendationBundle

    bundle = RecommendationBundle(bundle_dir)
    examples = [
        bundle.recommend([], k=5),
        bundle.recommend([str(bundle.item_ids[0])], k=5),
        bundle.recommend([str(bundle.item_ids[0]), str(bundle.item_ids[1])], k=5),
    ]
    if any(len(result["recommendations"]) > 5 for result in examples):
        raise RuntimeError("Release smoke returned more recommendations than requested")
    size = bundle.manifest["bundle_file_bytes"]
    if size >= 100 * 1024 * 1024:
        raise RuntimeError(f"Release bundle exceeds the 100 MiB target: {size} bytes")
    if bundle.manifest["user_factors_exported"] or bundle.manifest["user_identifiers_exported"]:
        raise RuntimeError("Release manifest claims that private user data is present")
    parity_profiles = [bundle.item_ids[:1].tolist(), bundle.item_ids[:3].tolist()]
    for seed_ids in parity_profiles:
        seed_indices = [bundle.item_index[item] for item in seed_ids]
        reference_scores = np.zeros(len(bundle.item_ids), dtype=np.float32)
        for seed_index in seed_indices:
            reference_scores += np.asarray(
                (bundle.features @ bundle.features.getrow(seed_index).T).toarray()
            ).ravel()
        candidates = np.asarray(
            [index for index, item_id in enumerate(bundle.item_ids) if item_id not in seed_ids],
            dtype=np.int32,
        )
        content_order = candidates[
            np.lexsort((bundle.item_ids[candidates], -reference_scores[candidates]))
        ]
        popularity_order = candidates[
            np.argsort(
                np.asarray(
                    [bundle.catalog[index]["recent_30d_interactions"] for index in candidates]
                )
                * -1,
                kind="stable",
            )
        ]
        content_rank = np.zeros(len(bundle.item_ids), dtype=np.float32)
        popularity_rank = np.zeros(len(bundle.item_ids), dtype=np.float32)
        content_rank[content_order] = np.arange(len(candidates), 0, -1) / len(candidates)
        popularity_rank[popularity_order] = np.arange(len(candidates), 0, -1) / len(candidates)
        weight = float(bundle.manifest["content_rank_weight"])
        combined = (1.0 - weight) * popularity_rank + weight * content_rank
        expected = bundle.item_ids[
            candidates[np.lexsort((bundle.item_ids[candidates], -combined[candidates]))[:20]]
        ].tolist()
        actual = [row["item_id"] for row in bundle.recommend(seed_ids, k=20)["recommendations"]]
        if expected != actual:
            raise RuntimeError(
                "Serving rank order differs from the independent fixed-profile reference"
            )
    comparison_path = bundle_dir.parent / "alternates/als"
    als_parity: dict[str, object] | None = None
    if comparison_path.exists():
        from game_discovery.serving.als import ALSComparisonModel

        als = ALSComparisonModel(comparison_path)
        if (
            als.manifest["user_factors_exported"]
            or als.manifest["user_identifiers_exported"]
            or als.manifest["training_histories_exported"]
        ):
            raise RuntimeError("ALS comparison artifact claims to contain private user data")
        als_parity = als.verify_implicit_parity(als.item_ids[:3].tolist(), k=5)
        if not als_parity["ids_match"] or not als_parity["scores_allclose"]:
            raise RuntimeError(
                "Custom ALS inference differs from implicit.recommend(recalculate_user=True)"
            )
    result = {
        "status": "verified locally",
        "model_version": bundle.manifest["model_version"],
        "catalog_items": len(bundle.catalog),
        "feature_matrix_shape": list(bundle.features.shape),
        "bundle_file_bytes": size,
        "bundle_limit_bytes": 100 * 1024 * 1024,
        "baseline_process_rss_mib": psutil.Process().memory_info().rss / (1024**2),
        "smoke_profiles": ["empty", "one seed", "two seeds"],
        "fixed_profile_rank_parity": True,
        "als_comparison_parity": als_parity,
        "user_factors_exported": False,
        "user_identifiers_exported": False,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _export_als_comparison(training_report: Path, output_dir: Path) -> int:
    from game_discovery.serving.als import export_als_comparison_model

    report = export_als_comparison_model(training_report, output_dir)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _monitor_replay(scenario: str, output: Path) -> int:
    from game_discovery.monitoring.drift import run_monitor_replay

    report = run_monitor_replay(scenario, output)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _promotion_demo(validation_hybrids: Path, validation_baselines: Path, output: Path) -> int:
    from tempfile import TemporaryDirectory

    from game_discovery.monitoring.promotion import PromotionLedger, evaluate_promotion_gate

    hybrids = json.loads(validation_hybrids.read_text(encoding="utf-8"))
    baselines = json.loads(validation_baselines.read_text(encoding="utf-8"))
    if (
        hybrids.get("evaluation_split") != "validation"
        or baselines.get("evaluation_split") != "validation"
    ):
        raise RuntimeError("promotion demo accepts validation reports only")
    champion_name = "hybrid_recent30_content_w10"
    candidate_name = "recent_popularity_30d"
    champion_metrics = hybrids["models"][champion_name]["warm_catalog_ranking"]
    candidate_metrics = baselines["models"][candidate_name]["warm_catalog_ranking"]
    gate = evaluate_promotion_gate(champion_metrics, candidate_metrics)
    with TemporaryDirectory(prefix="game-discovery-promotion-demo-") as temporary_directory:
        demo_dir = Path(temporary_directory)
        ledger_dir = demo_dir / "registry"
        artifact_dir = ledger_dir / "artifacts"
        artifact_dir.mkdir(parents=True)
        initial_artifact = artifact_dir / "champion.fixture"
        regressing_artifact = artifact_dir / "rejected.fixture"
        promoted_artifact = artifact_dir / "candidate.fixture"
        initial_artifact.write_bytes(b"synthetic champion fixture")
        regressing_artifact.write_bytes(b"synthetic regressing fixture")
        promoted_artifact.write_bytes(b"synthetic accepted fixture")
        ledger = PromotionLedger(ledger_dir)
        ledger.initialize("fixture-champion-v1", initial_artifact)
        rejection = ledger.promote(
            "fixture-rejected-v2",
            regressing_artifact,
            {"mean_ndcg@10": 1.0},
            {"mean_ndcg@10": 0.97},
        )
        accepted = ledger.promote(
            "fixture-candidate-v2",
            promoted_artifact,
            {"mean_ndcg@10": 1.0},
            {"mean_ndcg@10": 1.01},
        )
        rollback = ledger.rollback("fixture-champion-v1")
        rollback_demo = {
            "event_stream": "synthetic_test",
            "rejected_version_preserved": rejection["version"]
            in [row["version"] for row in ledger.read()["rejected_candidates"]],
            "active_after_rejection": rejection["active_version"],
            "active_after_acceptance": accepted["active_version"],
            "active_after_rollback": rollback["active_version"],
        }
    report = {
        "event_stream": "offline_validation",
        "evaluation_split": "validation",
        "fitting_cutoff": hybrids["fitting_cutoff"],
        "champion": champion_name,
        "candidate": candidate_name,
        "candidate_artifact_description": "Training-only 30-day popularity counts; no user factors or IDs.",
        "promotion_gate": gate,
        "synthetic_test_rollback": rollback_demo,
        "active_model_unchanged": not gate["accepted"],
        "final_test_read": False,
        "note": "This demonstration evaluates the frozen validation window only; it does not modify the release bundle or selection record.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
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
    export_command = commands.add_parser(
        "export", help="Refit the frozen validation choice and export an item-only bundle."
    )
    export_command.add_argument("--config", type=Path, default=Path("configs/portfolio.yaml"))
    export_command.add_argument("--output", type=Path)
    verify = commands.add_parser("verify-release", help="Verify a local model bundle and smoke it.")
    verify.add_argument("--bundle", type=Path, default=Path("models/release/selected_candidate"))
    export_als = commands.add_parser(
        "export-als-comparison",
        help="Export item-only ALS factors as an optional comparison model.",
    )
    export_als.add_argument(
        "--training-report", type=Path, default=Path("artifacts/reports/als_training.json")
    )
    export_als.add_argument("--output", type=Path, default=Path("models/release/alternates/als"))
    monitor = commands.add_parser(
        "monitor", help="Replay drift checks and promotion lifecycle examples."
    )
    monitor_commands = monitor.add_subparsers(dest="monitor_command", required=True)
    replay = monitor_commands.add_parser("replay", help="Run an isolated synthetic drift replay.")
    replay.add_argument(
        "--scenario",
        choices=(
            "stable-control",
            "unknown-item-shift",
            "fallback-rate-shift",
            "score-shift",
            "popularity-shift",
        ),
        required=True,
    )
    replay.add_argument("--output", type=Path)
    promotion_demo = monitor_commands.add_parser(
        "promotion-demo", help="Demonstrate a validation-only regression rejection."
    )
    promotion_demo.add_argument(
        "--validation-hybrids", type=Path, default=Path("artifacts/reports/validation_hybrids.json")
    )
    promotion_demo.add_argument(
        "--validation-baselines",
        type=Path,
        default=Path("artifacts/reports/validation_baselines.json"),
    )
    promotion_demo.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/deployment/rejected_candidate_validation.json"),
    )
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
    if args.command == "export":
        return _export_release(args.config, args.output)
    if args.command == "verify-release":
        return _verify_release(args.bundle)
    if args.command == "export-als-comparison":
        return _export_als_comparison(args.training_report, args.output)
    if args.command == "monitor" and args.monitor_command == "replay":
        output = args.output or Path(f"artifacts/reports/monitor_replay_{args.scenario}.json")
        return _monitor_replay(args.scenario, output)
    if args.command == "monitor" and args.monitor_command == "promotion-demo":
        return _promotion_demo(args.validation_hybrids, args.validation_baselines, args.output)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
