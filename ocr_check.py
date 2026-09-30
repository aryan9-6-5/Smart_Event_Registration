"""Show what OCR reads from a payment screenshot and how the app would classify it.

Usage:  python ocr_check.py path/to/screenshot.png
Read-only: does not touch the database, uploads or email.
"""
import sys

import app

sys.stdout.reconfigure(encoding='utf-8')  # the rupee sign breaks Windows' default console encoding


def main(path):
    text = app.read_image_text(path)
    print("=== Raw OCR text " + "=" * 50)
    print(text if text.strip() else "(nothing read - is Tesseract installed? TESSERACT_CMD=%s)" % app.TESSERACT_CMD)
    print("=" * 68)

    candidate, confident = app.extract_transaction_id(path, text=text)
    print(f"Transaction ID : {candidate!r} ({'trusted' if confident else 'NOT trusted -> manual review'})")

    amounts = app.extract_payment_amounts(path, text)
    expected = app.get_expected_fee()
    paid, status = app.classify_amount(amounts, expected)
    print(f"Amounts found  : {[str(a) for a in amounts]}")
    print(f"Expected fee   : {expected}  (config fee = {app.fee_display()!r})")
    print(f"Classification : {status}  (paid = {paid})")
    print(f"Student sees   : {app.amount_message(paid, status)!r}")


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
