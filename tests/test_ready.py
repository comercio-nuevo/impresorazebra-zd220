import unittest

from caza_toy.ready import ready_image, ready_zpl


class ReadyLabelTests(unittest.TestCase):
    def test_care_label_has_the_words_and_a_dark_icon(self):
        image = ready_image("cuidado")
        self.assertEqual(image.size, (812, 1218))
        self.assertLess(image.getpixel((20, 20)), 128)
        self.assertEqual(image.getpixel((40, 560)), 255)
        self.assertLess(image.getpixel((20, 1100)), 128)
        zpl = ready_zpl("cuidado")
        self.assertIn("^GFA,", zpl)
        self.assertIn("^PW812^LL1218", zpl)

    def test_unknown_label_is_rejected(self):
        with self.assertRaises(ValueError):
            ready_zpl("otra")


if __name__ == "__main__":
    unittest.main()
