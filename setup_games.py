#!/usr/bin/env python3
"""
Extract DOS game ZIPs to English-named directories,
detect main executables, and generate per-game dosbox-x configs.
"""

import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
BIN_DIR = BASE_DIR / "bin"
GAMES_DIR = BASE_DIR / "games"
CONF_DIR = BASE_DIR / "conf"
MAPPING_FILE = GAMES_DIR / "mapping.json"
TEMPLATE_CONF = BASE_DIR / "dosbox-x.conf"

# Known runtime/setup executables to exclude from auto-detection
EXCLUDED_EXES = {
    # DOS extenders / runtimes
    "DOS4GW.EXE", "PMODEW.EXE", "CWSDPMI.EXE", "DPMI16BI.OVL",
    # Setup / install / config tools
    "SETUP.EXE", "INSTALL.EXE", "SETSOUND.EXE", "SETVIDEO.EXE",
    "CONFIG.EXE", "SETUP.BAT", "INSTALL.BAT", "INSTMAIN.EXE",
    # Graphics / sound drivers
    "GRPDRV.EXE", "FMDRV.COM", "CDDRV.COM", "DMOUSE.COM",
    "VBE_READ.EXE", "VBE_RITE.EXE", "UVCONFIG.EXE", "SVGA.COM",
    "NULCDROM.COM", "ADRV688.DIG", "JAMMER.DIG", "AILDRVR.LST",
    # KOEI / common intros (only when MAIN.EXE exists)
    "OPEN.EXE", "END.EXE", "SIMCGA.EXE", "GRP600C.EXE", "GRP480C.EXE",
    # Misc tools / non-game
    "README.EXE", "COPYRIG.EXE", "TITLE.EXE", "HELP.COM",
    "MARK.EXE", "TV.EXE", "MIDIFORM.EXE", "MSSW95.EXE",
    "HOSPMIDI.BAT", "DirectDraw_Compatibility_Tool.exe", "WINMAIN.EXE",
    # Archivers (sometimes bundled in old game zips)
    "ARJ.EXE", "PKZIP.EXE", "PKUNZIP.EXE", "LHA.EXE", "RAR.EXE",
    # Launchers that are not the actual game
    "_PLAY.BAT", "SAVEPLAY.BAT",
    # KOEI runtime / misc
    "TIMERPC.COM", "SAN486.COM", "SAN4.COM", "SAN5.COM", "SAN586.COM",
    "KOEI.COM", "RTK2.COM", "TENSHOU.COM", "TENSHOUW.COM",
    "SBOPL2.COM", "MKFILE.COM", "TFDED.COM", "REKO3.COM",
    "BGMSEQ.COM", "CDX.EXE", "S.EXE", "ASMDRV.EXE",
    # Data files mistaken as executables
    "PASS.ORI", "DM1.LCK", "DM2.LCK",
    "JH1.BDB", "JH2.BDB", "JH4.BDB", "BH1.BDB", "BH2.BDB", "BH4.BDB",
    "BEG1.BD1", "BEG1.BD2", "BEG1.BD3", "BEG1.BD4", "BEG1.BDB",
    "FS.LBB", "DIG.INI", "DEBRF.TMP",
    # Joystick / hardware loaders
    "B50LOAD.EXE", "MK2LOAD.EXE", "DOWNLOAD.EXE",
    "LOADFLCS.BAT", "LOADTQS.BAT", "LOADTQS2.BAT", "LOADTQS3.BAT",
    "LOAD.BAT",
    # Alternate / non-DOS versions
    "PAL!.EXE", "PALS!.EXE", "sdlpal.exe",
    # Sound / graphics setup drivers
    "SOUND_PM.EXE", "LOADPATS.EXE",
    # Batch files that are not game launchers
    "20.BAT", "10.BAT", "S.BAT", "C.BAT", "JOGAR.BAT",
}


def ensure_pypinyin():
    try:
        import pypinyin
        return pypinyin
    except ImportError:
        print("pypinyin not found, installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pypinyin", "-q"])
        import pypinyin
        return pypinyin


def to_pinyin_slug(name: str, pypinyin_mod) -> str:
    """Convert Chinese game name to a safe English directory name."""
    # Remove .zip extension
    base = re.sub(r'\.zip$', '', name, flags=re.IGNORECASE)
    # Convert to pinyin
    py = pypinyin_mod.lazy_pinyin(base)
    slug = '_'.join(py)
    # Remove/replace unsafe chars
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[-\s]+', '_', slug)
    slug = slug.strip('_').lower()
    # Truncate if too long
    if len(slug) > 40:
        slug = slug[:40]
    return slug


def find_main_executable(game_dir: Path) -> Optional[str]:
    """Heuristic to find the main executable in a game directory."""
    all_files = []
    for root, _dirs, files in os.walk(game_dir):
        for f in files:
            fupper = f.upper()
            if fupper.endswith(('.EXE', '.COM', '.BAT')):
                full = Path(root) / f
                rel = full.relative_to(game_dir)
                # Skip files in deep subdirs (likely tools)
                parts = rel.parts
                if len(parts) > 2:
                    continue
                # Skip files inside dosbox/ subdirectories
                if any(p.upper() == 'DOSBOX' for p in parts[:-1]):
                    continue
                all_files.append((full, rel, fupper))

    if not all_files:
        return None

    # Priority 1: launcher BAT files in root or one level deep
    launcher_names = {'PLAY.BAT', 'START.BAT', 'RUN.BAT', 'GAME.BAT', 'GO.BAT',
                      'MENZO.BAT', 'AUTOEXEC.BAT', 'MAIN.BAT', 'GO2.BAT'}
    for _full, rel, fupper in all_files:
        if fupper in launcher_names:
            return str(rel)

    # Priority 2: largest EXE/COM not in exclusion list
    candidates = []
    for full, rel, fupper in all_files:
        if fupper in EXCLUDED_EXES:
            continue
        if fupper.endswith(('.EXE', '.COM')):
            try:
                size = full.stat().st_size
                candidates.append((size, str(rel)))
            except OSError:
                continue

    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1]

    # Fallback: any non-excluded executable
    for _full, rel, fupper in all_files:
        if fupper not in EXCLUDED_EXES:
            return str(rel)

    # Last resort: first BAT file
    for _full, rel, fupper in all_files:
        if fupper.endswith('.BAT'):
            return str(rel)

    return None


def extract_zip(zip_path: Path, target_dir: Path) -> bool:
    """Extract a zip file to target_dir. Returns True on success."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(target_dir)
        return True
    except zipfile.BadZipFile:
        print(f"  WARNING: Bad ZIP file, skipping: {zip_path.name}")
        return False
    except Exception as e:
        print(f"  WARNING: Failed to extract {zip_path.name}: {e}")
        return False


def generate_config(game_dir_name: str, exe_path: str, conf_path: Path) -> None:
    """Generate a dosbox-x config based on the template."""
    if not TEMPLATE_CONF.exists():
        print(f"  WARNING: Template config not found at {TEMPLATE_CONF}")
        return

    template = TEMPLATE_CONF.read_text(encoding='utf-8')

    # Replace [autoexec] section
    autoexec_re = re.compile(r'^\[autoexec\].*?(?=^\[|\Z)', re.MULTILINE | re.DOTALL)
    new_autoexec = f"""[autoexec]
# Auto-generated for {game_dir_name}
mount c {GAMES_DIR}
c:
cd {game_dir_name}
{exe_path}

"""

    if autoexec_re.search(template):
        config = autoexec_re.sub(new_autoexec, template)
    else:
        config = template + "\n" + new_autoexec

    conf_path.write_text(config, encoding='utf-8')


def scan_existing_dirs() -> dict:
    """Scan jy/ and xj/ and any other dirs in BASE_DIR that aren't bin/games/conf."""
    mapping = {}
    for item in BASE_DIR.iterdir():
        if not item.is_dir():
            continue
        if item.name in ('bin', 'games', 'conf', '.claude'):
            continue
        # Heuristic: if it has DOS game files, treat it as a game
        exe = find_main_executable(item)
        if exe:
            mapping[item.name] = {
                "dir": item.name,
                "exe": exe,
                "source": "existing_dir",
                "favorite": False
            }
    return mapping


def main():
    pypinyin_mod = ensure_pypinyin()

    GAMES_DIR.mkdir(exist_ok=True)
    CONF_DIR.mkdir(exist_ok=True)

    mapping = {}
    used_slugs = set()

    # Handle existing directories first
    existing = scan_existing_dirs()
    for name, info in existing.items():
        mapping[name] = info
        used_slugs.add(info["dir"])
        print(f"[EXISTING] {name} -> {info['dir']} (exe: {info['exe']})")

    # Process ZIP files
    zips = sorted([f for f in BIN_DIR.iterdir() if f.suffix.lower() == '.zip'])
    print(f"\nFound {len(zips)} ZIP files in {BIN_DIR}\n")

    for zip_path in zips:
        original_name = zip_path.stem  # name without .zip
        slug = to_pinyin_slug(original_name, pypinyin_mod)

        # Handle collisions
        base_slug = slug
        counter = 1
        while slug in used_slugs:
            slug = f"{base_slug}_{counter}"
            counter += 1

        used_slugs.add(slug)
        target_dir = GAMES_DIR / slug

        print(f"[ZIP] {original_name} -> {slug}")

        if target_dir.exists() and any(target_dir.iterdir()):
            print(f"  Directory already exists, skipping extraction")
        else:
            target_dir.mkdir(exist_ok=True)
            ok = extract_zip(zip_path, target_dir)
            if not ok:
                mapping[original_name] = {
                    "dir": slug,
                    "exe": None,
                    "error": "bad_zip",
                    "favorite": False
                }
                continue

        exe = find_main_executable(target_dir)
        if exe:
            print(f"  Detected exe: {exe}")
        else:
            print(f"  WARNING: Could not detect main executable")

        mapping[original_name] = {
            "dir": slug,
            "exe": exe,
            "favorite": False
        }

    # Generate configs
    print(f"\nGenerating configs in {CONF_DIR}...")
    for original_name, info in mapping.items():
        if info.get("error") or not info.get("exe"):
            continue
        conf_path = CONF_DIR / f"{info['dir']}.conf"
        generate_config(info["dir"], info["exe"], conf_path)
        info["config"] = str(conf_path.relative_to(BASE_DIR))

    # Write mapping
    MAPPING_FILE.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\nMapping saved to {MAPPING_FILE}")
    print(f"Total games: {len(mapping)}")
    print(f"Games with detected exe: {sum(1 for v in mapping.values() if v.get('exe'))}")


if __name__ == "__main__":
    main()
