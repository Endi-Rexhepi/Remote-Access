from argon2 import PasswordHasher
import argon2
from pathlib import Path
import getpass
import sys


PASS_FILE = Path(__file__).parent / "server.pass"

if PASS_FILE.is_file():
    answer = input("server.pass already exists. Overwrite? (yes/no): ").strip().lower()
    if answer != "yes":
        print("Cancelled. The existing file was not changed")
        raise SystemExit(0)
while True:
    password = getpass.getpass("Enter the password: ")
    confirm_password = getpass.getpass("Confirm the password: ")
    if (password == confirm_password) and (len(password) >= 8) and (len(password) <= 40):
        ph = PasswordHasher()
        password_hash = ph.hash(password)
        try:
            # Write the hashed password on the file server.pass
            PASS_FILE.write_text(password_hash, encoding='utf-8')
            # Read the hashed password from the file server.pass
            hash_password = PASS_FILE.read_text(encoding='utf-8')
            ph.verify(hash_password, password)
        except (argon2.exceptions.VerifyMismatchError, argon2.exceptions.InvalidHashError, OSError) as e:
            print(f"The password hashing failed: {e}")
            PASS_FILE.unlink(missing_ok=True)
            sys.exit(1)
        else:    
            print("The new password is set!")
            break
    else:
        print("Passwords must match. Password must be between 8-40 characters")

