import os
import random
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, os.environ.get("BULKSMS_API", str(HERE / ".." / ".." / "Personal_Co_code" / "bulksms-api")))
from app import exports

random.seed(254)
#The names are random Kenyan names and do not reflect real persons
NAMES = ["Wanjiku", "Otieno", "Achieng", "Kamau", "Njeri", "Mutua", "Chebet", "Kiprono", "Akinyi", "Mwangi"]
ROWS = [[f"2547{random.randint(10**7, 10**8 - 1)}", random.choice(NAMES), random.randint(100, 9000)] for _ in range(50)]

out = HERE / "payloads"
out.mkdir(exist_ok=True)
for fmt in ("xlsx", "xlsm", "xlsb", "xls", "ods", "numbers"):
    path = out / f"personalised.{fmt}"
    exports.write_file(fmt, str(path), ["phone_number", "name", "amount"], ROWS)
    print(f"wrote {path.relative_to(HERE)} ({path.stat().st_size:,} bytes)")
