"""Validation gate: Ensure all per-asset models are cryptographically distinct."""

import os
import hashlib
from config.symbols import UNIVERSE

def get_file_hash(filepath: str) -> str:
    hasher = hashlib.md5()
    with open(filepath, 'rb') as f:
        buf = f.read()
        hasher.update(buf)
    return hasher.hexdigest()

def verify():
    model_dir = os.path.join(os.path.dirname(__file__), '..', 'data', 'models')
    
    hashes = {}
    duplicates = False
    
    for asset in UNIVERSE:
        path = os.path.join(model_dir, f"{asset}_1d.pkl")
        if not os.path.exists(path):
            print(f"MISSING: {asset}_1d.pkl")
            continue
            
        file_hash = get_file_hash(path)
        
        if file_hash in hashes:
            print(f"DUPLICATE DETECTED: {asset} has same hash as {hashes[file_hash]}")
            duplicates = True
        else:
            hashes[file_hash] = asset
            print(f"VERIFIED DISTINCT: {asset} (Hash: {file_hash[:8]}...)")
            
    if duplicates:
        print("FAILED: Duplicate models found. You are assigning the same object.")
        exit(1)
    else:
        print("SUCCESS: All models are cryptographically distinct.")
        
if __name__ == "__main__":
    verify()
