import unittest

from PIL import Image, ImageDraw

from caza_toy.logo import find_white_origin, stamp_bitmap, stamp_zpl


class LogoTests(unittest.TestCase):
    def test_white_page_prefers_the_top_right(self):
        image = Image.new("L", (200, 300), 255)
        origin = find_white_origin(image, 40, 20, margin=4)
        self.assertIsNotNone(origin)
        x, y = origin
        self.assertGreaterEqual(x, 140)
        self.assertLessEqual(y, 20)

    def test_black_page_has_no_gap(self):
        image = Image.new("L", (200, 300), 0)
        self.assertIsNone(find_white_origin(image, 40, 20, margin=4))

    def test_stamp_avoids_a_black_block(self):
        image = Image.new("L", (400, 500), 255)
        ImageDraw.Draw(image).rectangle((220, 0, 399, 499), fill=0)
        stamped, placed = stamp_bitmap(image, "caza toy")
        self.assertTrue(placed)
        self.assertTrue(any(stamped.getpixel((x, y)) == 0 for x in range(0, 180) for y in range(0, 80)))
        self.assertEqual(stamped.getpixel((300, 250)), 0)

    def test_zpl_logo_stays_above_the_barcode(self):
        zpl = "^XA^PW812^LL1218^FO40,900^BY3^BCN,200,Y,N,N^FD123456789012^FS^XZ"
        output, placed = stamp_zpl(zpl, "caza toy")
        self.assertTrue(placed)
        self.assertIn("^FD123456789012^FS", output)
        self.assertIn("^FDcaza toy^FS", output)
        self.assertEqual(output.count("^XA"), 1)
        self.assertTrue(output.strip().endswith("^XZ"))
        fo = output.split("^FDcaza toy")[0].rfind("^FO")
        coords = output[fo + 3 :].split("^", 1)[0]
        _x, y = coords.split(",")
        self.assertLess(int(y), 860)

    def test_full_box_is_left_alone(self):
        zpl = "^XA^PW812^LL200^FO0,0^GB812,200,8^FS^XZ"
        output, placed = stamp_zpl(zpl, "caza toy")
        self.assertFalse(placed)
        self.assertEqual(output, zpl)

    def test_graphic_zpl_is_not_stamped_again(self):
        zpl = "^XA^GFA,1,1,1,00^XZ"
        output, placed = stamp_zpl(zpl, "caza toy")
        self.assertFalse(placed)
        self.assertNotIn("caza toy", output)


if __name__ == "__main__":
    unittest.main()
