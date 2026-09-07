
from decimal import Decimal
import re

def test():
    strike = Decimal('2')
    strike_str = f"{strike:g}"
    symbol = "TLRY Jan 16 '26 $2 Call"
    # The replacement string has '$2'
    replacement = "$" + strike_str
    print(f"Replacement string: '{replacement}'")
    new_symbol = re.sub(r"\$\d+(?:\.\d+)?", replacement, symbol)
    print(f"New symbol: '{new_symbol}'")

    # Try again with escaped $ if needed
    replacement_escaped = replacement.replace("$", "\\$")
    new_symbol_escaped = re.sub(r"\$\d+(?:\.\d+)?", replacement_escaped, symbol)
    print(f"New symbol (escaped): '{new_symbol_escaped}'")

if __name__ == "__main__":
    test()
