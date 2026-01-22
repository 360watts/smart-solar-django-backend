import os
import sys

def find_files_with_null_bytes(root_dir):
    for dirpath, dirnames, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename.endswith('.py'):
                filepath = os.path.join(dirpath, filename)
                try:
                    with open(filepath, 'rb') as f:
                        content = f.read()
                        if b'\x00' in content:
                            print(filepath)
                except Exception as e:
                    print(f"Error reading {filepath}: {e}")

if __name__ == "__main__":
    root_dir = sys.argv[1] if len(sys.argv) > 1 else '.'
    find_files_with_null_bytes(root_dir)