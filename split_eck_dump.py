import argparse
import json
import logging
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def patch_file(path: Path) -> None:
    """Patch the given file by replacing prototype-related strings."""
    try:
        with path.open("r", encoding="utf-8") as src, tempfile.NamedTemporaryFile(
            "w", delete=False, dir=path.parent, encoding="utf-8"
        ) as tmp:
            temp_path = Path(tmp.name)
            for line in src:
                line = line.replace("__proto__", "__pt-field__")
                line = line.replace("prototype", "pt-field")
                tmp.write(line)

        temp_path.replace(path)

    except Exception as exc:
        logger.error("Error patching file %s: %s", path, exc)


def minify_json_files(root: Path):
    """Minify all JSON files under the provided root directory."""
    minified_count = 0
    total_before_bytes = 0
    total_after_bytes = 0

    for json_file in root.rglob("*.json"):
        if not json_file.is_file():
            continue

        try:
            before_bytes = json_file.stat().st_size
            with json_file.open("r", encoding="utf-8") as src:
                data = json.load(src)
            minified_text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
            minified_bytes = minified_text.encode("utf-8")
            candidate_after_bytes = len(minified_bytes)

            if candidate_after_bytes < before_bytes:
                with json_file.open("wb") as dst:
                    dst.write(minified_bytes)
                after_bytes = candidate_after_bytes
                saved_bytes = before_bytes - after_bytes
                saved_pct = (saved_bytes / before_bytes) * 100 if before_bytes else 0
                minified_count += 1
                relative_path = json_file.relative_to(root)
                logger.info(
                    "Minified JSON %s: %s -> %s bytes (saved %s bytes, %.2f%%)",
                    relative_path,
                    before_bytes,
                    after_bytes,
                    saved_bytes,
                    saved_pct,
                )
            else:
                after_bytes = before_bytes

            total_before_bytes += before_bytes
            total_after_bytes += after_bytes
        except json.JSONDecodeError as exc:
            logger.warning("Skipping invalid JSON file %s: %s", json_file, exc)
        except Exception as exc:
            logger.error("Error minifying file %s: %s", json_file, exc)

    total_saved_bytes = total_before_bytes - total_after_bytes
    logger.info(
        "Total JSON size change for %s: before=%.2f MB, after=%.2f MB, saved=%.2f MB",
        root.name,
        total_before_bytes / (1024 * 1024),
        total_after_bytes / (1024 * 1024),
        total_saved_bytes / (1024 * 1024),
    )


def find_elasticsearch_roots(extracted_path: Path) -> list[Path]:
    """Find all directories under the extracted path that match the pattern for Elasticsearch diagnostics."""

    roots = []

    elastic_system_path = extracted_path / "elastic-system" / "elasticsearch"
    if elastic_system_path.is_dir():
        for subdir in elastic_system_path.iterdir():
            if subdir.is_dir():
                roots.append(subdir)
    else:
        logger.warning("Directory not found: %s", elastic_system_path)

    return roots


def patch_target_files(elastic_root: Path):
    """Patch the target files under the given Elasticsearch root directory."""

    FILES_TO_PATCH = ["cluster_state.json", "mapping.json"]

    for path in elastic_root.rglob("*"):
        if path.is_file() and path.name in FILES_TO_PATCH:
            logger.info("Patching file: %s", path)
            patch_file(path)


def build_output_zip_path(
    input_zip_path: Path,
    elastic_root: Path,
    patched: bool = False,
    minified: bool = False,
) -> Path:
    """Build the output zip file path based on the input zip path and the Elasticsearch root directory."""
    output_name = f"{input_zip_path.stem}-{elastic_root.name}"
    if patched:
        output_name += "-patched"
    if minified:
        output_name += "-minified"
    output_name += input_zip_path.suffix
    return input_zip_path.with_name(output_name)


def build_api_diagnostics_dir_name() -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"api-diagnostics-{timestamp}"


def process_zip(
    zip_path: Path,
    patch: bool = False,
    minify: bool = False,
) -> None:
    """Process the given zip file by extracting it, finding Elasticsearch diagnostic directories, optionally patching and minifying files, and creating new zip files for each Elasticsearch instance."""
    with tempfile.TemporaryDirectory(prefix="eck-diag-") as temp_dir:
        logger.info("Extracting zip file to temporary directory: %s", temp_dir)
        extracted_path = Path(temp_dir)
        with zipfile.ZipFile(zip_path, "r") as archive:
            archive.extractall(extracted_path)

        logger.info(
            "Finding Elasticsearch diagnostic directories under: %s", extracted_path
        )

        elastic_roots = find_elasticsearch_roots(extracted_path)

        root_names = [root.name for root in elastic_roots]
        logger.info(
            "Found %s Elasticsearch diagnostic directories to process: %s",
            len(elastic_roots),
            ", ".join(root_names),
        )

        for root in elastic_roots:
            if patch:
                patch_target_files(root)
            else:
                logger.info(
                    "Skipping patch step under %s (use --patch to enable)", root
                )

            if minify:
                minify_json_files(root)
            else:
                logger.info(
                    "Skipping minify step under %s (use --minify to enable)", root
                )

        api_diagnostics_dir_name = build_api_diagnostics_dir_name()

        for root in elastic_roots:
            output_zip_path = build_output_zip_path(
                zip_path, root, patched=patch, minified=minify
            )
            logger.info(
                "Splitting zip file for instance %s with patch=%s, minify=%s -> %s",
                root.name,
                patch,
                minify,
                output_zip_path,
            )
            with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
                for file_path in root.rglob("*"):
                    if file_path.is_file():
                        arcname = Path(
                            api_diagnostics_dir_name
                        ) / file_path.relative_to(root)
                        archive.write(file_path, arcname)


def main() -> None:
    parser = argparse.ArgumentParser(description="Patch ECK diagnostic zip files")
    parser.add_argument(
        "zip_path", type=Path, help="Path to the ECK diagnostic zip file"
    )
    parser.add_argument(
        "--patch",
        action="store_true",
        help="Patch target files (cluster_state.json and mapping.json)",
    )
    parser.add_argument(
        "--minify",
        action="store_true",
        help="Minify all .json files under extracted Elasticsearch directories",
    )
    args = parser.parse_args()

    zip_path = args.zip_path

    if not zip_path.is_file():
        logger.error("The provided path does not exist or is not a file: %s", zip_path)
        return

    if not zipfile.is_zipfile(zip_path):
        logger.error("The provided file is not a valid zip archive: %s", zip_path)
        return

    logger.info("Processing zip file: %s", zip_path)

    process_zip(zip_path, patch=args.patch, minify=args.minify)


if __name__ == "__main__":
    main()
