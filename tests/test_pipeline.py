import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import pymupdf
from PIL import Image

from caza_toy.config import LABEL_H, LABEL_W
from caza_toy.pipeline import digit_matrix, image_to_zpl, prepare, render_label_pages, sample_label_pdf, sniff
from caza_toy.watch import files_in_zip


class PipelineTests(unittest.TestCase):
    def test_sniff_prefers_pdf(self):
        self.assertEqual(sniff(b"%PDF-1.4\n"), "pdf")
        self.assertEqual(sniff(b"\n^XA^XZ\n"), "zpl")
        self.assertEqual(sniff(b"hola"), "unknown")
        self.assertEqual(sniff(b"%PDF-1.4\n^XA"), "pdf")

    def test_unknown_file_is_rejected(self):
        with self.assertRaises(ValueError):
            prepare(b"esto no es una etiqueta", "caza toy")

    def test_black_bit_is_the_high_bit(self):
        image = Image.new("L", (8, 1), 255)
        image.putpixel((0, 0), 0)
        zpl = image_to_zpl(image)
        self.assertIn("^PW8", zpl)
        self.assertIn("^LL1", zpl)
        self.assertIn("^GFA,1,1,1,80", zpl)

    def test_sample_pdf_becomes_a_4x6_zpl_with_logo(self):
        prepared = prepare(sample_label_pdf(), "caza toy")
        self.assertEqual(prepared.kind, "pdf")
        self.assertEqual(prepared.pages, 1)
        self.assertTrue(prepared.stamped)
        self.assertIn(f"^PW{LABEL_W}", prepared.zpl)
        self.assertIn(f"^LL{LABEL_H}", prepared.zpl)
        self.assertIn("^GFA,", prepared.zpl)

    def test_black_label_is_not_stamped(self):
        document = pymupdf.open()
        page = document.new_page(width=288, height=432)
        page.draw_rect(page.rect, color=(0, 0, 0), fill=(0, 0, 0))
        data = document.tobytes()
        document.close()
        prepared = prepare(data, "caza toy")
        self.assertFalse(prepared.stamped)

    def test_letter_page_crops_to_the_label(self):
        document = pymupdf.open()
        page = document.new_page(width=612, height=792)
        page.draw_rect(pymupdf.Rect(72, 72, 360, 504), color=(0, 0, 0), fill=(0, 0, 0))
        data = document.tobytes()
        document.close()
        prepared = prepare(data, "caza toy")
        self.assertIn(f"^LL{LABEL_H}", prepared.zpl)
        self.assertFalse(prepared.stamped)

    def test_landscape_label_rotates_to_portrait(self):
        document = pymupdf.open()
        page = document.new_page(width=432, height=288)
        page.draw_rect(page.rect, color=(0, 0, 0), fill=(0, 0, 0))
        data = document.tobytes()
        document.close()
        pages = render_label_pages(data)
        self.assertEqual(pages[0].size, (LABEL_W, LABEL_H))
        prepared = prepare(data, "caza toy")
        self.assertFalse(prepared.stamped)

    def test_matrix_off_keeps_zpl_commands(self):
        prepared = prepare(b"^XA^FO40,40^A0N,30,30^FDGuia^FS^XZ", "caza toy", "guia.txt", matrix=False)
        self.assertEqual(prepared.kind, "zpl")
        self.assertIn("^FDGuia^FS", prepared.zpl)
        self.assertNotIn("^GFA,", prepared.zpl)

    def test_matrix_on_turns_zpl_and_pdf_into_digits(self):
        zpl = prepare(
            b"^XA^PW812^LL1218^FO40,40^A0N,40,40^FDGuia^FS^FO40,200^BCN,120,Y,N,N^FD123^FS^XZ",
            "caza toy",
            "guia.txt",
            matrix=True,
        )
        pdf = prepare(sample_label_pdf(), "caza toy", "guia.pdf", matrix=True)
        for prepared in (zpl, pdf):
            self.assertIn("^GFA,", prepared.zpl)
            self.assertIn(f"^PW{LABEL_W}", prepared.zpl)
            self.assertIn(f"^LL{LABEL_H}", prepared.zpl)
        self.assertNotIn("^FDGuia^FS", zpl.zpl)

    def test_digit_matrix_keeps_white_and_marks_black(self):
        image = Image.new("L", (LABEL_W, LABEL_H), 255)
        Image.Image.paste(image, Image.new("L", (80, 72), 0), (32, 48))
        mosaic = digit_matrix(image)
        self.assertEqual(mosaic.size, (LABEL_W, LABEL_H))
        self.assertEqual(mosaic.getpixel((4, 4)), 255)
        self.assertTrue(any(mosaic.getpixel((x, y)) == 0 for x in range(32, 96) for y in range(48, 96)))

    def test_zpl_round_trip_keeps_the_original_barcode(self):
        source = "^XA^PW812^LL1218^FO40,40^A0N,30,30^FDGuia^FS^XZ"
        prepared = prepare(source.encode(), "caza toy")
        self.assertEqual(prepared.kind, "zpl")
        self.assertIn("^FDGuia^FS", prepared.zpl)
        self.assertTrue(prepared.stamped)

    def test_txt_becomes_a_4x6_label(self):
        prepared = prepare(b"Pedido 15\nCaja azul", "caza toy", "nota.txt")
        self.assertEqual(prepared.kind, "text")
        self.assertEqual(prepared.pages, 1)
        self.assertIn(f"^PW{LABEL_W}", prepared.zpl)
        self.assertIn(f"^LL{LABEL_H}", prepared.zpl)
        self.assertTrue(prepared.stamped)

    def test_txt_with_zpl_stays_zpl(self):
        prepared = prepare(b"^XA^FO20,20^FDHola^FS^XZ\n", "caza toy", "guia.txt")
        self.assertEqual(prepared.kind, "zpl")
        self.assertIn("^FDHola^FS", prepared.zpl)

    def test_png_fits_the_label(self):
        image = Image.new("RGB", (120, 80), "white")
        image.putpixel((0, 0), (0, 0, 0))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        prepared = prepare(buffer.getvalue(), "caza toy", "foto.png")
        self.assertEqual(prepared.kind, "image")
        self.assertIn(f"^PW{LABEL_W}", prepared.zpl)
        self.assertIn(f"^LL{LABEL_H}", prepared.zpl)

    def test_csv_prints_one_label_per_row_and_raw_zpl(self):
        table = "Caja,ABC\ncodigo,\"^XA^FO10,10^FDZPL^FS^XZ\"\n"
        prepared = prepare(table.encode(), "caza toy", "envios.csv")
        self.assertEqual(prepared.kind, "csv")
        self.assertEqual(prepared.pages, 2)
        self.assertIn("^FDZPL^FS", prepared.zpl)
        self.assertIn(f"^PW{LABEL_W}", prepared.zpl)

    def test_zip_extracts_zpl_and_leaves_no_temp_dir(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("guias/envio.zpl", "^XA^FO10,10^FDDentro^FS^XZ\n")
            archive.writestr("guias/ignorar.docx", "no")
            archive.writestr("__MACOSX/._envio.zpl", "basura")
        before = set(Path(tempfile.gettempdir()).glob("cazatoy-*"))
        files = files_in_zip(buffer.getvalue())
        after = set(Path(tempfile.gettempdir()).glob("cazatoy-*"))
        self.assertEqual(before, after)
        self.assertEqual(files, [("envio.zpl", b"^XA^FO10,10^FDDentro^FS^XZ\n")])


if __name__ == "__main__":
    unittest.main()
