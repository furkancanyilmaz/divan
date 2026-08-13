"""Small local-only QR rendering helper for Divan sync pairing.

The encoder is vendored from Project Nayuki under the MIT License in
``qrcodegen.py``.  Returning a matrix instead of HTML keeps the API response
inert; the web UI paints the cells itself and never injects pairing data as
markup.
"""

from qrcodegen import QrCode


MAX_PAIRING_TEXT_BYTES = 2048


def pairing_qr_matrix(text):
    value = str(text or "")
    if not value:
        raise ValueError("eşleme kodu boş")
    if len(value.encode("utf-8")) > MAX_PAIRING_TEXT_BYTES:
        raise ValueError("eşleme kodu QR için çok uzun")
    qr = QrCode.encode_text(value, QrCode.Ecc.MEDIUM)
    size = qr.get_size()
    return {
        "size": size,
        "rows": [
            "".join("1" if qr.get_module(x, y) else "0"
                    for x in range(size))
            for y in range(size)
        ],
    }
