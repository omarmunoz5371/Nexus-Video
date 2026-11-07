#!/usr/bin/env python3
"""Nexus Video CLI — pack management and media conversion tool.

Commands:
  detect    Show detected display properties from /sys/class/graphics/fb0
  discover  List all discovered packs (builtin + custom)
  validate  Validate one or all packs using ffprobe
  convert   Convert a pack's source videos to built media
  loop      Generate a seamless loop from a source intro video
  check     Run quality checks on a source, loop, or converted output pack
  manifest  Print the full manifest as JSON

Usage examples:
  python3 nexus_video_cli.py detect
  python3 nexus_video_cli.py discover
  python3 nexus_video_cli.py validate
  python3 nexus_video_cli.py validate --pack mechanical_core
  python3 nexus_video_cli.py convert --pack my_custom --scale-mode fill
  python3 nexus_video_cli.py loop --src sources/nexus_signature/intro_source.mp4 \\
                                  --dst packs/builtin/nexus_signature/loop.mp4 \\
                                  --strategy palindrome
  python3 nexus_video_cli.py check --source sources/nexus_signature/intro_source.mp4
  python3 nexus_video_cli.py check --loop packs/builtin/nexus_signature/loop.mp4
  python3 nexus_video_cli.py check --output build/nexus_signature
  python3 nexus_video_cli.py manifest
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Allow running directly from the project root without installing the package
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent))

from nexus_video import __version__
from nexus_video.check import (
    CheckResult, check_loop_video, check_output_pack, check_source_video,
)
from nexus_video.config import BUILD_DIR, BUILTIN_DIR, CUSTOM_DIR, SCALE_MODES
from nexus_video.convert import ConversionError, convert_pack, validate_output
from nexus_video.detect import DisplayDetectionError, detect_display
from nexus_video.loop import LoopError, LoopStrategy, generate_loop
from nexus_video.packs import ValidationResult, discover_packs, generate_manifest, validate_pack

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [nexus-video] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("nexus_video_cli")


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _ok(s: str) -> str:   return f"\033[92m{s}\033[0m"
def _warn(s: str) -> str: return f"\033[93m{s}\033[0m"
def _err(s: str) -> str:  return f"\033[91m{s}\033[0m"
def _dim(s: str) -> str:  return f"\033[2m{s}\033[0m"
def _bold(s: str) -> str: return f"\033[1m{s}\033[0m"


def _print_validation(result: ValidationResult, indent: int = 2) -> None:
    pad = " " * indent
    status = _ok("VALID") if result.valid else _err("INVALID")
    print(f"{pad}Status: {status}")
    for e in result.errors:
        print(f"{pad}  {_err('✗')} {e}")
    for w in result.warnings:
        print(f"{pad}  {_warn('!')} {w}")
    for label, info in (("intro", result.intro_info), ("loop", result.loop_info)):
        if info:
            print(
                f"{pad}  {_dim(label)}: {info.duration:.1f}s  "
                f"{info.width}×{info.height}  codec={info.codec}"
                + (f"  {_warn('[audio]')}" if info.has_audio else "")
            )


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------

def cmd_detect(args: argparse.Namespace) -> int:
    try:
        info = detect_display()
    except DisplayDetectionError as exc:
        print(_err(f"Detection failed: {exc}"))
        return 1

    print(_bold("Display"))
    print(f"  Resolution : {info.width}×{info.height}")
    print(f"  Bits/pixel : {info.bpp}")
    print(f"  Stride     : {info.stride} bytes/row")
    print(f"  Frame size : {info.frame_bytes:,} bytes")
    print(f"  Framebuffer: {info.fb_path}")
    if info.is_supported:
        print(f"  Pipeline   : {_ok('RGB565 ✓')}")
    elif info.needs_rgb32_pipeline:
        print(f"  Pipeline   : {_warn('32-bit detected — not yet supported in Phase 2')}")
    else:
        print(f"  Pipeline   : {_err(f'bpp={info.bpp} not supported')}")
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    packs = discover_packs()
    if not packs:
        print(_warn("No packs discovered."))
        return 0

    print(_bold(f"Discovered {len(packs)} pack(s):"))
    for pack in packs:
        badge = _dim("[builtin]") if pack.pack_type == "builtin" else _ok("[custom]")
        tm    = _warn(" [trademark pending]") if pack.meta.get("distribution") == "pending_trademark_review" else ""
        print(f"  {badge} {_bold(pack.pack_id)} — {pack.name}{tm}")
        print(f"    {_dim(str(pack.pack_dir))}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    packs = discover_packs()
    if not packs:
        print(_warn("No packs found."))
        return 0

    target = args.pack
    if target:
        packs = [p for p in packs if p.pack_id == target]
        if not packs:
            print(_err(f"Pack '{target}' not found."))
            return 1

    all_valid = True
    for pack in packs:
        badge = _dim("[builtin]") if pack.pack_type == "builtin" else _ok("[custom]")
        print(f"\n{badge} {_bold(pack.pack_id)} ({pack.pack_dir})")
        result = validate_pack(pack.pack_dir)
        _print_validation(result)
        if not result.valid:
            all_valid = False

    return 0 if all_valid else 2


def cmd_convert(args: argparse.Namespace) -> int:
    packs = discover_packs()
    target = args.pack
    if target:
        packs = [p for p in packs if p.pack_id == target]
        if not packs:
            print(_err(f"Pack '{target}' not found."))
            return 1

    if not packs:
        print(_warn("No packs to convert."))
        return 0

    try:
        display_info = detect_display()
    except DisplayDetectionError as exc:
        log.warning("Display detection failed (%s) — using 800×480 fallback", exc)
        from nexus_video.detect import DisplayInfo
        from nexus_video.config import FALLBACK_WIDTH, FALLBACK_HEIGHT, FALLBACK_BPP, FALLBACK_STRIDE
        display_info = DisplayInfo(FALLBACK_WIDTH, FALLBACK_HEIGHT, FALLBACK_BPP, FALLBACK_STRIDE)

    if not display_info.is_supported:
        print(_err(f"Display bpp={display_info.bpp} is not supported (need 16-bit RGB565)."))
        return 1

    scale_mode = args.scale_mode
    exit_code = 0

    for pack in packs:
        print(f"\nConverting {_bold(pack.pack_id)} [{scale_mode}] → {display_info.width}×{display_info.height}")
        output_dir = BUILD_DIR / pack.pack_id
        try:
            convert_pack(
                pack_dir=pack.pack_dir,
                output_dir=output_dir,
                display_info=display_info,
                scale_mode=scale_mode,
            )
        except ConversionError as exc:
            print(_err(f"  Conversion failed: {exc}"))
            exit_code = 3
            continue

        errors = validate_output(output_dir, display_info)
        if errors:
            for e in errors:
                print(_err(f"  Output validation: {e}"))
            exit_code = 3
        else:
            print(_ok(f"  Done → {output_dir}"))

    return exit_code


def cmd_loop(args: argparse.Namespace) -> int:
    src = Path(args.src)
    dst = Path(args.dst)
    if not src.exists():
        print(_err(f"Source not found: {src}"))
        return 1

    strategy = args.strategy
    duration = args.duration
    kwargs = {}
    if args.segment_start is not None:
        kwargs["segment_start"] = args.segment_start
    if args.fade is not None:
        kwargs["fade_seconds"] = args.fade

    print(f"Generating {_bold(strategy)} loop: {src.name} → {dst}")
    try:
        generate_loop(src=src, dst=dst, strategy=strategy, duration=duration, **kwargs)
    except LoopError as exc:
        print(_err(f"  Loop generation failed: {exc}"))
        return 3

    print(_ok(f"  Done → {dst} ({dst.stat().st_size / 1024:.1f} KB)"))
    return 0


def _print_check_results(results: list[CheckResult], indent: int = 2) -> int:
    """Print check results. Returns the number of hard errors."""
    pad = " " * indent
    errors = 0
    for r in results:
        if r.passed:
            print(f"{pad}{_ok('✓')} {r.name}: {_dim(r.message)}")
        elif r.severity == "warning":
            print(f"{pad}{_warn('!')} {r.name}: {r.message}")
        else:
            print(f"{pad}{_err('✗')} {r.name}: {r.message}")
            errors += 1
    return errors


def cmd_check(args: argparse.Namespace) -> int:
    exit_code = 0

    if args.source:
        path = Path(args.source)
        print(f"\n{_bold('Source video')} {_dim(str(path))}")
        results = check_source_video(path)
        if _print_check_results(results) > 0:
            exit_code = 2

    if args.loop:
        path = Path(args.loop)
        print(f"\n{_bold('Loop video')} {_dim(str(path))}")
        results = check_loop_video(path)
        if _print_check_results(results) > 0:
            exit_code = 2

    if args.output:
        out_dir = Path(args.output)
        try:
            display = detect_display()
        except DisplayDetectionError:
            from nexus_video.detect import DisplayInfo
            from nexus_video.config import FALLBACK_WIDTH, FALLBACK_HEIGHT, FALLBACK_BPP, FALLBACK_STRIDE
            display = DisplayInfo(FALLBACK_WIDTH, FALLBACK_HEIGHT, FALLBACK_BPP, FALLBACK_STRIDE)
        print(f"\n{_bold('Output pack')} {_dim(str(out_dir))} [{display.width}×{display.height}]")
        results = check_output_pack(out_dir, display)
        if _print_check_results(results) > 0:
            exit_code = 2

    if not (args.source or args.loop or args.output):
        print(_warn("Specify --source, --loop, or --output (or any combination)."))
        return 1

    return exit_code


def cmd_manifest(args: argparse.Namespace) -> int:
    manifest = generate_manifest(validate=not args.no_validate)
    print(json.dumps(manifest, indent=2, default=str))
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nexus_video_cli.py",
        description=f"Nexus Video {__version__} — pack management and conversion",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("detect",   help="Show detected display properties")
    sub.add_parser("discover", help="List all packs")

    val = sub.add_parser("validate", help="Validate packs using ffprobe")
    val.add_argument("--pack", help="Validate only this pack id")

    conv = sub.add_parser("convert", help="Convert a pack to built media")
    conv.add_argument("--pack",       help="Convert only this pack id (default: all custom packs)")
    conv.add_argument("--scale-mode", choices=SCALE_MODES, default="fit",
                      help="Scale mode for conversion (default: fit)")

    lp = sub.add_parser("loop", help="Generate a seamless loop from an intro source video")
    lp.add_argument("--src",      required=True, help="Source intro video path")
    lp.add_argument("--dst",      required=True, help="Output loop video path")
    lp.add_argument("--strategy", choices=[s.value for s in LoopStrategy],
                    default=LoopStrategy.PALINDROME, help="Loop strategy (default: palindrome)")
    lp.add_argument("--duration", type=float, default=5.0,
                    help="Target loop duration in seconds (default: 5)")
    lp.add_argument("--segment-start", type=float, default=None,
                    help="[palindrome/crossfade] Start of segment in source (default: last N seconds)")
    lp.add_argument("--fade",     type=float, default=None,
                    help="[crossfade only] Crossfade duration in seconds (default: 0.5)")

    ck = sub.add_parser("check", help="Run quality checks on source, loop, or output pack")
    ck.add_argument("--source", metavar="PATH", help="Check a source intro video")
    ck.add_argument("--loop",   metavar="PATH", help="Check a loop video (includes continuity PSNR)")
    ck.add_argument("--output", metavar="DIR",  help="Check a converted output pack directory")

    mf = sub.add_parser("manifest", help="Print full manifest as JSON")
    mf.add_argument("--no-validate", action="store_true",
                    help="Skip ffprobe validation (faster, structural check only)")

    return p


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()

    handlers = {
        "detect":   cmd_detect,
        "discover": cmd_discover,
        "validate": cmd_validate,
        "convert":  cmd_convert,
        "loop":     cmd_loop,
        "check":    cmd_check,
        "manifest": cmd_manifest,
    }
    fn = handlers.get(args.command)
    if fn is None:
        parser.print_help()
        sys.exit(1)

    sys.exit(fn(args))


if __name__ == "__main__":
    main()
