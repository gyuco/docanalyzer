"""Fabbrica finte scansioni da un PDF nativo, con degradazioni realistiche.

La verita di riferimento resta nota: e il testo del PDF di partenza, quindi si
puo misurare quanto perde l'OCR invece di limitarsi a verificare che giri.

    python make_scan.py IN.pdf OUT.pdf [--dpi N] [--skew GRADI] [--jpeg Q]
                                       [--blur R] [--noise S] [--gray]
"""
from __future__ import annotations

import argparse
import io
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageFilter


def degrade(img: Image.Image, a: argparse.Namespace) -> Image.Image:
    if a.gray:
        img = img.convert("L")
    if a.skew:
        # expand=True evita di tagliare gli angoli; il bianco simula il vetro
        # dello scanner attorno al foglio storto.
        fill = 255 if img.mode == "L" else (255, 255, 255)
        img = img.rotate(a.skew, resample=Image.BICUBIC, expand=True, fillcolor=fill)
    if a.blur:
        img = img.filter(ImageFilter.GaussianBlur(a.blur))
    if a.noise:
        arr = np.asarray(img).astype(np.int16)
        arr += np.random.normal(0, a.noise, arr.shape).astype(np.int16)
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode=img.mode)
    return img


def encode(img: Image.Image, quality: int) -> bytes:
    """Serializza l'immagine per l'inserimento nella pagina.

    Con --jpeg la codifica DEVE restare JPEG fino al PDF: passare da PNG
    manterrebbe gli artefatti ma buttereebbe via la compressione, che e meta
    del punto di simulare una scansione (file leggeri, qualita scadente).
    """
    buf = io.BytesIO()
    if quality:
        img.convert("L" if img.mode == "L" else "RGB").save(
            buf, "JPEG", quality=quality
        )
    else:
        img.save(buf, "PNG")
    return buf.getvalue()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("src", type=Path)
    p.add_argument("dst", type=Path)
    p.add_argument("--dpi", type=int, default=150)
    p.add_argument("--skew", type=float, default=0.0, help="gradi di rotazione")
    p.add_argument("--jpeg", type=int, default=0, help="qualita 1-95, 0 = off")
    p.add_argument("--blur", type=float, default=0.0, help="raggio gaussiano")
    p.add_argument("--noise", type=float, default=0.0, help="sigma del rumore")
    p.add_argument("--gray", action="store_true", help="scala di grigi")
    a = p.parse_args()

    out = pymupdf.open()
    with pymupdf.open(a.src) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=a.dpi)
            img = degrade(Image.open(io.BytesIO(pix.tobytes("png"))), a)
            data = encode(img, a.jpeg)
            # La pagina segue le proporzioni dell'immagine degradata: con skew
            # e expand=True non coincidono piu con quelle dell'originale.
            w, h = img.size
            scale = page.rect.width / w
            new = out.new_page(width=page.rect.width, height=h * scale)
            new.insert_image(new.rect, stream=data)
    out.save(a.dst)
    mb = a.dst.stat().st_size / 1e6
    print(f"{a.dst.name:22} {mb:6.1f} MB  dpi={a.dpi} skew={a.skew} "
          f"jpeg={a.jpeg or '-'} blur={a.blur or '-'} noise={a.noise or '-'}")


if __name__ == "__main__":
    main()
