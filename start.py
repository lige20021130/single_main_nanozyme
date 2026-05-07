#!/usr/bin/env python3
import sys
import os
import subprocess

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    os.environ['CUDA_VISIBLE_DEVICES'] = '0'
    os.environ['PYTHONWARNINGS'] = 'ignore:.*pin_memory.*:UserWarning'
    
    print("="*50)
    print("   Nanozyme Extraction System")
    print("="*50)
    print()
    print(f"Using Python: {sys.executable}")
    print(f"Python version: {sys.version}")
    print(f"Working directory: {script_dir}")
    print()
    print("Starting GUI...")
    print()
    
    try:
        subprocess.run([sys.executable, "nanozyme_gui.py"], check=True)
    except subprocess.CalledProcessError as e:
        print()
        print(f"[ERROR] Program exited with code: {e.returncode}")
        print()
        print("Troubleshooting:")
        print("1. Make sure dependencies are installed: pip install -r requirements.txt")
        print("2. Make sure config.yaml exists")
        print()
        input("Press Enter to exit...")
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print()
        print(f"[ERROR] {e}")
        print()
        input("Press Enter to exit...")

if __name__ == "__main__":
    main()
