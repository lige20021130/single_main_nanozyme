#!/usr/bin/env python3
import sys
import os
import importlib

def check_python_version():
    if sys.version_info < (3, 10):
        print(f"[ERROR] Python 3.10+ required, got {sys.version_info.major}.{sys.version_info.minor}")
        return False
    print(f"[OK] Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    return True

def check_dependencies():
    required = {
        "yaml": "pyyaml",
        "tkinter": "python-tk (built-in)",
    }
    optional = {
        "opendataloader_pdf": "opendataloader-pdf",
        "orjson": "orjson",
    }

    missing_required = []
    for mod, pkg in required.items():
        try:
            importlib.import_module(mod)
        except ImportError:
            missing_required.append(pkg)

    missing_optional = []
    for mod, pkg in optional.items():
        try:
            importlib.import_module(mod)
        except ImportError:
            missing_optional.append(pkg)

    if missing_required:
        print(f"[ERROR] Missing required packages: {', '.join(missing_required)}")
        print(f"        Run: pip install {' '.join(missing_required)}")
        return False

    print("[OK] Required dependencies installed")

    if missing_optional:
        print(f"[WARN] Optional packages not installed: {', '.join(missing_optional)}")
        print("       Some features may be limited (e.g., PDF parsing, fast JSON)")
    else:
        print("[OK] Optional dependencies installed")

    return True

def check_project_files():
    core_files = [
        "nanozyme_gui.py",
        "single_main_nanozyme_extractor.py",
        "extraction_pipeline.py",
        "nanozyme_preprocessor_midjson.py",
        "config_manager.py",
        "api_client.py",
        "numeric_validator.py",
        "nanozyme_models.py",
        "dependencies.py",
    ]

    missing = [f for f in core_files if not os.path.exists(f)]
    if missing:
        print(f"[ERROR] Missing core files: {', '.join(missing)}")
        print("        Please ensure you have the complete project")
        return False

    print(f"[OK] Core files present ({len(core_files)} files)")
    return True

def check_config():
    if os.path.exists("config.yaml"):
        print("[OK] config.yaml found")
        return True
    print("[WARN] config.yaml not found")
    print("       System will use default config (rule-only mode, no LLM/VLM)")
    print("       To enable AI extraction, create config.yaml with API keys")
    print("       See: usage_guide.md for configuration instructions")
    return True

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    os.environ['CUDA_VISIBLE_DEVICES'] = '0'
    os.environ['PYTHONWARNINGS'] = 'ignore:.*pin_memory.*:UserWarning'

    print("=" * 50)
    print("   Nanozyme Extraction System")
    print("=" * 50)
    print()
    print(f"Working directory: {script_dir}")
    print()

    print("--- Pre-flight checks ---")
    checks = [
        ("Python version", check_python_version),
        ("Dependencies", check_dependencies),
        ("Project files", check_project_files),
        ("Configuration", check_config),
    ]

    all_passed = True
    for name, check_fn in checks:
        if not check_fn():
            all_passed = False

    print()

    if not all_passed:
        print("[ERROR] Pre-flight checks failed. Please fix the issues above.")
        print("        See usage_guide.md for detailed help")
        print()
        input("Press Enter to exit...")
        return

    print("--- Starting GUI ---")
    print()

    try:
        import tkinter as tk
    except ImportError:
        print("[ERROR] tkinter not available. Please install python-tk")
        print("        Ubuntu/Debian: sudo apt-get install python3-tk")
        print("        Fedora: sudo dnf install python3-tkinter")
        print("        Windows: Usually included with Python installer")
        input("Press Enter to exit...")
        return

    try:
        from nanozyme_gui import NanozymeGUI
        root = tk.Tk()
        app = NanozymeGUI(root)
        root.mainloop()
    except Exception as e:
        print()
        print(f"[ERROR] GUI failed to start: {e}")
        print()
        import traceback
        traceback.print_exc()
        print()
        print("Troubleshooting:")
        print("  1. Make sure all dependencies are installed: pip install -r requirements.txt")
        print("  2. Make sure you're running from the project root directory")
        print("  3. See usage_guide.md for detailed help")
        print()
        input("Press Enter to exit...")

if __name__ == "__main__":
    main()
